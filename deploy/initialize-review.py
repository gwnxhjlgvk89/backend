"""Initialize ONLY an empty, isolated review database; never seed a formal roster."""

import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets

from sqlalchemy import func, select
from sqlalchemy.engine import make_url

from club.config import settings
from club.db import make_engine, sessions
from club.initial_passwords import initial_password
from club.models import Activity, Audit, Base, Club, User, utcnow


CLUBS = [
    (
        "光影摄影社",
        "艺术创作",
        30,
        "校园创作空间",
        "每周三 16:00–17:30",
        "从构图、光线和手机摄影入门，开展校园主题拍摄与作品交流。无需专业相机，欢迎零基础同学。",
        [],
    ),
    (
        "羽毛球社",
        "体育运动",
        40,
        "校园体育活动区",
        "每周二 16:00–17:30",
        "学习握拍、发球和基础步法，分组练习并开展友谊赛。参加活动需穿运动鞋，可自备球拍。",
        [],
    ),
    (
        "篮球社",
        "体育运动",
        40,
        "校园篮球活动区",
        "每周四 16:00–17:30",
        "以运球、投篮和团队配合练习为主，按基础分组训练。重视安全与团队协作，欢迎篮球爱好者。",
        [],
    ),
    (
        "悦读文学社",
        "人文阅读",
        35,
        "校园阅读空间",
        "每周三 16:00–17:00",
        "每月共读一本书，交流阅读感受，尝试诗歌、短篇与校园随笔创作。无需写作基础，愿意分享即可。",
        [],
    ),
    (
        "合唱与音乐社",
        "艺术创作",
        45,
        "校园音乐活动室",
        "每周五 16:00–17:30",
        "从呼吸、节奏和基础发声开始，练习合唱与小组表演。无需乐器或考级经历，活动以共同练习为主。",
        [],
    ),
    (
        "编程与机器人社",
        "科技实践",
        25,
        "校园科技活动室",
        "每周二 16:00–17:30",
        "通过小项目学习编程思维、传感器与机器人控制，分组完成作品展示。本体验社团设置计算机专业限制，用于体验资格提示。",
        ["计算机"],
    ),
    (
        "绿色志愿者社",
        "公益实践",
        50,
        "学生活动交流区",
        "每周四 16:00–17:00",
        "围绕校园环保、图书整理和文明宣传开展志愿实践。活动前统一说明分工和注意事项，欢迎热心公益的同学。",
        [],
    ),
    (
        "手作与创意社",
        "艺术创作",
        30,
        "校园创意活动室",
        "每周五 16:00–17:30",
        "体验纸艺、拼贴和旧物改造，从简单作品开始学习设计与制作。使用安全基础工具，作品可在社团内交流展示。",
        [],
    ),
]


def guard(config, ends_at):
    url = make_url(config.database_url)
    if (
        config.club_env != "production"
        or url.database != "club_v2_review"
        or url.host not in {"127.0.0.1", "localhost"}
        or config.redis_prefix != "club:review:v1"
    ):
        raise SystemExit("Requires isolated club_v2_review and club:review:v1 in production configuration")
    if ends_at.tzinfo is None or ends_at <= datetime.now(timezone.utc):
        raise SystemExit("Review deadline must be timezone-aware and in the future")


async def main(args):
    config = settings()
    ends_at = datetime.fromisoformat(args.ends_at.replace("Z", "+00:00"))
    guard(config, ends_at)
    path = Path(args.credentials)
    if path.exists() or not path.parent.is_dir() or path.parent.stat().st_mode & 0o077:
        raise SystemExit("Use a new credential file inside an existing private (0700) directory")
    users = [
        {
            "username": "admin",
            "name": "系统管理员",
            "role": "super_admin",
            "password": secrets.token_urlsafe(24),
            "major": "",
        },
        {"username": "review01", "name": "体验同学甲", "role": "student", "major": "计算机"},
        {"username": "review02", "name": "体验同学乙", "role": "student", "major": "艺术"},
        {"username": "review03", "name": "体验同学丙", "role": "student", "major": "计算机"},
    ]
    engine = make_engine()
    created = False
    try:
        async with sessions(engine)() as db, db.begin():
            # Every application table must be empty, including jobs and audit history.
            for table in Base.metadata.sorted_tables:
                if await db.scalar(select(func.count()).select_from(table)):
                    raise SystemExit("Review database is not empty; nothing was changed")
            for item in users:
                item.setdefault("password", initial_password(item["name"]))
                item["must_change_password"] = True
                user = User(
                    username=item["username"],
                    name=item["name"],
                    role=item["role"],
                    password_plaintext=item["password"],
                    major=item["major"],
                    class_name="体验班" if item["role"] == "student" else "",
                    must_change_password=True,
                )
                db.add(user)
                await db.flush()
                item["id"] = user.id
            club_ids = []
            for name, category, capacity, location, schedule, description, majors in CLUBS:
                club = Club(
                    name=name,
                    category=category,
                    capacity=capacity,
                    remaining=capacity,
                    location=location + "（模拟）",
                    schedule=schedule,
                    description=description
                    + "\n\n以上为模拟社团资料，仅用于功能体验；正式社团、地点及时间以学校发布为准。",
                    allowed_majors=majors,
                )
                db.add(club)
                await db.flush()
                club_ids.append(club.id)
            db.add(
                Activity(
                    id=1,
                    name="社团填报体验（模拟数据）",
                    state="draft",
                    starts_at=utcnow(),
                    ends_at=ends_at.astimezone(timezone.utc).replace(tzinfo=None),
                    cancel_until=ends_at.astimezone(timezone.utc).replace(tzinfo=None),
                    allow_cancel=True,
                )
            )
            db.add(
                Audit(
                    actor_id=users[0]["id"],
                    action="review.initialize",
                    target="club_v2_review",
                    summary={
                        "synthetic": True,
                        "club_ids": club_ids,
                        "usernames": [u["username"] for u in users],
                    },
                )
            )
            document = {
                "url": config.public_url,
                "database": "club_v2_review",
                "synthetic": True,
                "ends_at": ends_at.isoformat(),
                "users": users,
                "club_ids": club_ids,
            }
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            created = True
            with os.fdopen(fd, "w") as stream:
                json.dump(document, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
        print("Initialized review database: 8 clubs, 3 students, 1 administrator; activity remains draft")
    except BaseException:
        if created:
            path.unlink(missing_ok=True)
        raise
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials", required=True)
    parser.add_argument("--ends-at", required=True)
    asyncio.run(main(parser.parse_args()))
