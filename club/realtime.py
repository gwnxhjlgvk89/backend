import asyncio
import json
import logging
import os
from collections import deque

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect
from redis.exceptions import RedisError
from sqlalchemy import select

from club.config import settings
from club.errors import DomainError
from club.models import User
from club.security import claims

logger = logging.getLogger(__name__)


class PreparedMessage(dict):
    """Share one encoded payload across all recipients in this process."""

    def __init__(self, message):
        super().__init__(message)
        self.encoded = json.dumps(message, ensure_ascii=False, separators=(",", ":"))


class Hub:
    def __init__(self):
        self.connections = {}  # websocket -> (user id, version, bounded queue)
        self.by_user = {}
        self.seen = set()
        self.recent = deque()

    def add(self, ws, uid, ver, queue):
        self.connections[ws] = (uid, ver, queue)
        self.by_user.setdefault(uid, set()).add(ws)

    def remove(self, ws):
        item = self.connections.pop(ws, None)
        if item:
            uid = item[0]
            self.by_user[uid].discard(ws)
            if not self.by_user[uid]:
                del self.by_user[uid]

    def dispatch(self, message):
        eid = message.get("event_id")
        if eid is not None:
            if eid in self.seen:
                return
            self.seen.add(eid)
            self.recent.append(eid)
            if len(self.recent) > 10000:
                self.seen.remove(self.recent.popleft())
        user_id = message.get("user_id")
        message = PreparedMessage(message)
        targets = list(self.by_user.get(user_id, ())) if user_id is not None else list(self.connections)
        for ws in targets:
            uid, ver, queue = self.connections[ws]
            if message.get("event") == "session_revoked" and message.get("version", ver + 1) <= ver:
                continue
            if message.get("user_id") not in (None, uid):
                continue
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                self.remove(ws)
                asyncio.create_task(ws.close(code=1013, reason="resync required"))

    async def subscriber(self, redis):
        while True:
            try:
                async with redis.pubsub() as sub:
                    await sub.subscribe(f"{settings().redis_prefix}:events")
                    self.dispatch({"event": "resync"})
                    async for item in sub.listen():
                        if item["type"] == "message":
                            self.dispatch(json.loads(item["data"]))
            except (RedisError, ValueError):
                logger.warning("event_subscription_retry")
                await asyncio.sleep(2)

    async def revalidate(self, factory):
        # Snapshot the exact sessions before querying, so a concurrent new login
        # cannot be closed by an older account-version snapshot.
        observed = list(self.connections.items())
        ids = list({item[0] for _, item in observed})
        if not ids:
            return
        async with factory() as db:
            rows = (
                await db.execute(select(User.id, User.active, User.token_version).where(User.id.in_(ids)))
            ).all()
        accounts = {uid: (active, version) for uid, active, version in rows}
        closing = []
        for ws, session in observed:
            if self.connections.get(ws) != session:
                continue
            uid, version, _ = session
            if accounts.get(uid) != (True, version):
                closing.append(asyncio.wait_for(ws.close(code=1008, reason="session expired"), timeout=3))
        await asyncio.gather(*closing, return_exceptions=True)

    async def validation_loop(self, factory):
        failures = 0
        while True:
            await asyncio.sleep(10)
            try:
                await self.revalidate(factory)
                failures = 0
            except Exception as exc:
                logger.warning("ws_validation_retry type=%s", type(exc).__name__)
                failures += 1
                if failures >= 3:
                    await asyncio.gather(
                        *(
                            asyncio.wait_for(
                                ws.close(code=1013, reason="verification unavailable"), timeout=3
                            )
                            for ws in list(self.connections)
                        ),
                        return_exceptions=True,
                    )

    async def serve(self, ws: WebSocket):
        ticket = ws.query_params.get("ticket", "")
        if not 20 <= len(ticket) <= 100:
            await ws.close(code=1008)
            return
        try:
            raw = await ws.app.state.redis.getdel(f"{settings().redis_prefix}:ticket:{ticket}")
            if not raw:
                await ws.close(code=1008)
                return
            data = claims(raw)
            uid = int(data["sub"])
            async with ws.app.state.sessions() as db:
                u = await db.get(User, uid)
                if not u or not u.active or u.token_version != data["ver"]:
                    await ws.close(code=1008)
                    return
        except (RedisError, DomainError, ValueError):
            await ws.close(code=1008)
            return
        await ws.accept()
        queue = asyncio.Queue(maxsize=16)
        self.add(ws, uid, data["ver"], queue)

        async def send():
            while True:
                message = await queue.get()
                if message.get("event") == "session_revoked":
                    await ws.close(code=1008)
                    return
                encoded = message.encoded if isinstance(message, PreparedMessage) else json.dumps(message)
                await asyncio.wait_for(ws.send_text(encoded), timeout=3)

        sender = asyncio.create_task(send())
        try:
            await ws.send_json(
                {"event": "resync", **({"worker_id": os.getpid()} if settings().club_env == "test" else {})}
            )
            while True:
                payload = await asyncio.wait_for(ws.receive_text(), timeout=45)
                if len(payload) > 256:
                    break
                claims(raw)  # enforce token expiry for long-lived connections
                if json.loads(payload).get("event") == "ping":
                    # Database versions are checked in one periodic batch per
                    # process; 1500 simultaneous heartbeats must not take 1500
                    # pool slots away from registrations. Pub/Sub revokes early.
                    queue.put_nowait({"event": "pong"})
        except Exception as exc:
            logger.info(json.dumps({"event": "ws_receive_closed", "cause": type(exc).__name__}))
        finally:
            self.remove(ws)
            sender.cancel()
            await asyncio.gather(sender, return_exceptions=True)
            try:
                await ws.close()
            except (RuntimeError, WebSocketDisconnect):
                pass
