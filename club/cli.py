import argparse
import asyncio
from datetime import timedelta
import json

from sqlalchemy import func, select

from club.config import settings
from club.initial_passwords import initial_password
from club.db import make_engine, sessions
from club.models import Activity, Club, User, utcnow
from club.services import consistency


async def main(args):
    engine = make_engine()
    factory = sessions(engine)
    try:
        async with factory() as db, db.begin():
            if args.action == "init":
                if not await db.get(Activity, 1):
                    db.add(Activity(id=1))
            elif args.action == "admin":
                password = initial_password(args.name)
                db.add(
                    User(
                        username=args.username,
                        name=args.name,
                        role="super_admin",
                        password_plaintext=password,
                    )
                )
            elif args.action == "seed":
                if settings().club_env == "production":
                    raise SystemExit("Seeding production is forbidden")
                if await db.scalar(select(func.count()).select_from(User)):
                    raise SystemExit("Seed requires an empty v2 database; existing data was not changed")
                db.add(
                    User(
                        username="admin",
                        name="本地管理员",
                        role="super_admin",
                        password_plaintext="ClubDemo2026!",
                        must_change_password=False,
                    )
                )
                for i in range(1, args.students + 1):
                    db.add(
                        User(
                            username=f"student{i:04d}",
                            name=f"测试学生{i}",
                            role="student",
                            major="计算机",
                            class_name="测试一班",
                            password_plaintext="ClubDemo2026!",
                            must_change_password=False,
                        )
                    )
                names = ["摄影", "篮球", "合唱", "机器人", "羽毛球", "街舞", "志愿服务"]
                for i in range(1, 43):
                    db.add(
                        Club(
                            id=i,
                            name=f"{names[(i - 1) % 7]}社 · {i}",
                            category=names[(i - 1) % 7],
                            capacity=40,
                            remaining=40,
                            description="在这里认识志同道合的伙伴，一起探索兴趣，参与每周活动。",
                            location="学生活动中心",
                            schedule="每周三 16:00–18:00",
                        )
                    )
                a = await db.get(Activity, 1)
                if not a:
                    a = Activity(id=1)
                    db.add(a)
                a.starts_at, a.ends_at = utcnow() - timedelta(hours=1), utcnow() + timedelta(days=7)
                a.allow_cancel, a.cancel_until, a.state = True, a.ends_at, "published"
                print(
                    "Local demo: admin / student0001; password: ClubDemo2026! (synthetic test credentials only)"
                )
            elif args.action == "check":
                discrepancies = await consistency(db)
                print(json.dumps({"consistent": not discrepancies, "discrepancies": discrepancies}))
                if discrepancies:
                    raise SystemExit(1)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["init", "seed", "admin", "check"])
    p.add_argument("--students", type=int, default=1500)
    p.add_argument("--username", default="admin")
    p.add_argument("--name", default="管理员")
    asyncio.run(main(p.parse_args()))
