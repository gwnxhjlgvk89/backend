"""Synthetic TEST-only fixture CLI. No HTTP test endpoint is exposed."""

import argparse
import asyncio
from datetime import timedelta
import json

from redis.asyncio import Redis
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.engine import make_url

from club.config import settings
from club.db import make_engine, sessions
from club.models import Activity, Club, Enrollment, Favorite, Idempotency, Outbox, User, utcnow
from club.security import hash_password
from club.services import consistency


async def main(args):
    if (
        settings().club_env != "test"
        or make_url(settings().database_url).database != "club_test"
        or settings().redis_prefix != "club:test"
    ):
        raise SystemExit("Only an explicit club_test environment is permitted")
    engine = make_engine()
    factory = sessions(engine)
    redis = Redis.from_url(settings().redis_url)
    try:
        async with factory() as db, db.begin():
            others = await db.scalar(
                select(func.count()).select_from(User).where(~User.username.like("load%"))
            )
            if others:
                raise ValueError("Non-load users exist; fixture refuses to modify this database")
            if args.action == "seed":
                if await db.scalar(select(func.count()).select_from(User)):
                    raise ValueError("Seed needs empty users")
                hashed = await hash_password("SyntheticLoad2026!")
                db.add_all(
                    [
                        User(
                            id=i,
                            username=f"load{i:04d}",
                            name=f"Synthetic {i}",
                            password_hash=hashed,
                            must_change_password=False,
                        )
                        for i in range(1, 3001)
                    ]
                )
                db.add_all(
                    [Club(id=i, name=f"Load club {i}", capacity=100, remaining=100) for i in range(1, 43)]
                )
                a = await db.get(Activity, 1)
                if not a:
                    a = Activity(id=1)
                    db.add(a)
                a.state = "published"
                a.starts_at = utcnow() - timedelta(hours=1)
                a.ends_at = utcnow() + timedelta(days=1)
            elif args.action == "passwords":
                # Explicit TEST fixture only: unique salts, never reuse a hash across accounts.
                users = list((await db.scalars(select(User).order_by(User.id))).all())
                for user in users:
                    user.password_hash = await hash_password("SyntheticLoad2026!")
                print(json.dumps({"synthetic_passwords_updated": len(users), "algorithm": "argon2id"}))
            elif args.action == "details":
                import random

                rng = random.Random(1214)
                for club in (await db.scalars(select(Club))).all():
                    club.description = "合成社团介绍，仅用于性能验证。\n" + "".join(
                        rng.choice("校园活动社团学习交流科学运动艺术实践合作创造阅读音乐") for _ in range(680)
                    )
                    club.category = "校园活动"
                    club.location = f"合成活动室 {club.id}"
                    club.schedule = "每周社团活动时间"
                print(json.dumps({"synthetic_detail_characters": 680, "cover_images": False}))
            elif args.action == "prepare":
                for model in (Favorite, Idempotency, Enrollment, Outbox):
                    await db.execute(delete(model))
                # Realistic total capacity for uniform and popular-club tests.
                capacity = 1 if args.scenario == "last_seat" else 100
                await db.execute(
                    update(Club).values(capacity=capacity, remaining=capacity, version=Club.version + 1)
                )
            elif args.action == "check":
                mismatch = await consistency(db)
                enrolled = await db.scalar(select(func.count()).select_from(Enrollment))
                status = dict(
                    (
                        await db.execute(
                            text(
                                "SHOW GLOBAL STATUS WHERE Variable_name IN ('Threads_connected','Max_used_connections','Innodb_row_lock_waits','Innodb_row_lock_time','Innodb_buffer_pool_wait_free')"
                            )
                        )
                    ).all()
                )
                result = {"enrollments": enrolled, "inconsistencies": mismatch, "mysql": status}
                if args.timings:
                    from datetime import timezone

                    rows = (
                        await db.execute(
                            select(Outbox.payload, Outbox.created_at).where(
                                Outbox.payload["event"].as_string() == "quota"
                            )
                        )
                    ).all()
                    result["quota_timings"] = [
                        [p["club_id"], p["version"], created.replace(tzinfo=timezone.utc).timestamp()]
                        for p, created in rows
                    ]
                print(json.dumps(result))
        if args.action == "prepare":
            async for key in redis.scan_iter(f"{settings().redis_prefix}:limit:enrollment:*"):
                await redis.delete(key)
    finally:
        await redis.aclose()
        await engine.dispose()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["seed", "prepare", "check", "passwords", "details"])
    p.add_argument("--scenario", default="uniform", choices=["uniform", "last_seat", "hot_club"])
    p.add_argument("--timings", action="store_true")
    asyncio.run(main(p.parse_args()))
