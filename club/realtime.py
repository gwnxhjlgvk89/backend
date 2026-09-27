import asyncio
import json
import logging
from collections import deque

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect
from redis.exceptions import RedisError

from club.config import settings
from club.errors import DomainError
from club.models import User
from club.security import claims

logger = logging.getLogger(__name__)


class Hub:
    def __init__(self):
        self.connections = {}  # websocket -> (user id, bounded queue)
        self.seen = set()
        self.recent = deque()

    def dispatch(self, message):
        eid = message.get("event_id")
        if eid is not None:
            if eid in self.seen:
                return
            self.seen.add(eid)
            self.recent.append(eid)
            if len(self.recent) > 10000:
                self.seen.remove(self.recent.popleft())
        for ws, (uid, ver, queue) in list(self.connections.items()):
            if message.get("event") == "session_revoked" and message.get("version", ver + 1) <= ver:
                continue
            if message.get("user_id") not in (None, uid):
                continue
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                self.connections.pop(ws, None)
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
        self.connections[ws] = (uid, data["ver"], queue)

        async def send():
            while True:
                message = await queue.get()
                if message.get("event") == "session_revoked":
                    await ws.close(code=1008)
                    return
                await asyncio.wait_for(ws.send_json(message), timeout=3)

        sender = asyncio.create_task(send())
        try:
            await ws.send_json({"event": "resync"})
            while True:
                payload = await asyncio.wait_for(ws.receive_text(), timeout=45)
                if len(payload) > 256:
                    break
                claims(raw)  # enforce token expiry for long-lived connections
                if json.loads(payload).get("event") == "ping":
                    # Pub/Sub may miss revocations during reconnects. Heartbeats
                    # also validate the authoritative account version.
                    async with ws.app.state.sessions() as db:
                        u = await db.get(User, uid)
                        if not u or not u.active or u.token_version != data["ver"]:
                            await ws.close(code=1008)
                            break
                    queue.put_nowait({"event": "pong"})
        except Exception:
            pass
        finally:
            self.connections.pop(ws, None)
            sender.cancel()
            await asyncio.gather(sender, return_exceptions=True)
            try:
                await ws.close()
            except (RuntimeError, WebSocketDisconnect):
                pass
