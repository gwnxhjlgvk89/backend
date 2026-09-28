"""Initialize a verified empty new database, with a private random bootstrap credential."""

import asyncio
import json
import os
from pathlib import Path
import secrets
import sys

from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from club.config import settings
from club.db import make_engine, sessions
from club.models import Activity, User, Club, Enrollment


async def main():
    s = settings()
    if make_url(s.database_url).database not in {"club_v2_prod", "club_v2_verify"}:
        raise SystemExit("Only the two explicit new-deployment databases are permitted")
    path = Path(sys.argv[1])
    if path.exists():
        raise SystemExit("Refusing to replace existing credentials")
    password = secrets.token_urlsafe(24)
    engine = make_engine()
    try:
        async with sessions(engine)() as db, db.begin():
            for model in (Activity, User, Club, Enrollment):
                if await db.scalar(select(func.count()).select_from(model)):
                    raise SystemExit("Database not empty; refusing initialization")
            db.add(Activity(id=1, state="draft"))
            db.add(
                User(
                    username="admin",
                    name="系统管理员",
                    role="super_admin",
                    password_plaintext=password,
                    must_change_password=True,
                )
            )
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(
                    {
                        "url": s.public_url,
                        "username": "admin",
                        "password": password,
                        "must_change_password": True,
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        print("Initialized one administrator and one draft activity; credential saved privately")
    finally:
        await engine.dispose()


asyncio.run(main())
