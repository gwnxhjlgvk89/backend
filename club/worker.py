import asyncio
import json
import logging
import signal
import hashlib

from redis.asyncio import Redis
from sqlalchemy import select

from club.config import settings
from club.db import make_engine, sessions
from club.jobs import run_one
from club.models import Job, Outbox
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
    for payload in coalesced.values():
        if payload["event"] == "catalog":
            pipe.delete(f"{settings().redis_prefix}:catalog")
        pipe.publish(f"{settings().redis_prefix}:events", json.dumps(payload))
    await pipe.execute()
    async with factory() as db, db.begin():
        from sqlalchemy import update

        await db.execute(update(Outbox).where(Outbox.id.in_([r.id for r in rows])).values(delivered=True))


async def main():
    engine = make_engine()
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
                try:
                    await deliver(factory, redis)
                except Exception as exc:
                    logger.warning("outbox_retry type=%s", type(exc).__name__)
                await asyncio.sleep(0.25)

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
