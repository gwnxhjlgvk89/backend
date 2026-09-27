import asyncio
import json
import logging
import signal
import hashlib
import time
from datetime import datetime, timezone

from redis.asyncio import Redis
from sqlalchemy import select

from club.config import settings
from club.db import make_engine, sessions
from club.jobs import run_one
from club.models import Job, Outbox, utcnow
from club.services import iso

logger = logging.getLogger("club.worker")


async def deliver(factory, redis):
    async with factory() as db:
        rows = list(
            (
                await db.scalars(
                    select(Outbox).where(Outbox.delivered.is_(False)).order_by(Outbox.id).limit(5000)
                )
            ).all()
        )
    if not rows:
        return
    coalesced = {}
    for row in rows:
        p = row.payload
        key = (p["event"], p.get("club_id"), p.get("user_id"))
        previous = coalesced.get(key)
        if previous and p.get("version", 0) < previous.get("version", 0):
            continue
        coalesced[key] = {**p, "event_id": row.id, "enqueued_at": iso(row.created_at)}
    pipe = redis.pipeline(transaction=False)
    quotas = [p for p in coalesced.values() if p["event"] == "quota"]
    if quotas:
        # A single bounded frame prevents a 42-club burst from overflowing each
        # client's queue before its sender gets a chance to run.
        pipe.publish(
            f"{settings().redis_prefix}:events",
            json.dumps(
                {
                    "event": "quota_delta",
                    "rows": [[p[k] for k in ("club_id", "remaining", "version")] for p in quotas],
                    "event_id": max(p["event_id"] for p in quotas),
                    "t": int(
                        datetime.fromisoformat(
                            min(p["enqueued_at"] for p in quotas).replace("Z", "+00:00")
                        ).timestamp()
                        * 1000
                    ),
                    "p": int(utcnow().replace(tzinfo=timezone.utc).timestamp() * 1000),
                },
                separators=(",", ":"),
            ),
        )
    for payload in coalesced.values():
        if payload["event"] == "quota":
            continue
        if payload["event"] == "catalog":
            pipe.delete(f"{settings().redis_prefix}:catalog")
        pipe.publish(f"{settings().redis_prefix}:events", json.dumps(payload))
    await pipe.execute()
    async with factory() as db, db.begin():
        from sqlalchemy import update

        await db.execute(update(Outbox).where(Outbox.id.in_([r.id for r in rows])).values(delivered=True))


async def main():
    # Includes the long-lived leader connection; independent of API pool sizes.
    engine = make_engine(pool_size=5, max_overflow=5)
    factory = sessions(engine)
    redis = Redis.from_url(settings().redis_url, decode_responses=True, socket_timeout=2)
    stopped = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, stopped.set)
    # MySQL advisory lock prevents two background workers from duplicating jobs.
    async with engine.connect() as leader:
        from sqlalchemy import text

        lock_name = (
            "club_worker_"
            + hashlib.sha256((settings().database_url + settings().redis_prefix).encode()).hexdigest()[:40]
        )
        if not await leader.scalar(text("SELECT GET_LOCK(:name, 0)"), {"name": lock_name}):
            raise RuntimeError("Another worker is already running")
        async with factory() as db, db.begin():
            for job in await db.scalars(select(Job).where(Job.state == "running")):
                job.state = "queued"

        async def notifications():
            while not stopped.is_set():
                started = time.monotonic()
                try:
                    await deliver(factory, redis)
                except Exception as exc:
                    logger.warning("outbox_retry type=%s", type(exc).__name__)
                await asyncio.sleep(max(0.01, 0.25 - (time.monotonic() - started)))

        task = asyncio.create_task(notifications())
        try:
            while not stopped.is_set():
                if not await leader.scalar(
                    text("SELECT IS_USED_LOCK(:name)=CONNECTION_ID()"), {"name": lock_name}
                ):
                    raise RuntimeError("Worker leadership lost")
                try:
                    await run_one(factory)
                except Exception as exc:
                    logger.warning("job_retry type=%s", type(exc).__name__)
                await asyncio.sleep(1)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await leader.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": lock_name})
    await redis.aclose()
    await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
