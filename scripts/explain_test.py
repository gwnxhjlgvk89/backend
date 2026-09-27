"""Read query plans only from the isolated synthetic TEST database."""

import asyncio
import json

from sqlalchemy import text
from sqlalchemy.engine import make_url

from club.config import settings
from club.db import make_engine


async def main():
    if settings().club_env != "test" or make_url(settings().database_url).database != "club_test":
        raise SystemExit("Only club_test is allowed")
    queries = {
        "enrollment_identity": "SELECT u.id, e.club_id, i.response FROM v2_users u LEFT JOIN v2_enrollments e ON e.student_id=u.id LEFT JOIN v2_idempotency i ON i.user_id=u.id AND i.`key`='synthetic-review' WHERE u.id=1 FOR UPDATE",
        "student_page": "SELECT id,username,name FROM v2_users WHERE role='student' ORDER BY id LIMIT 30",
        "outbox_delivery": "SELECT id,payload FROM v2_outbox WHERE delivered=0 ORDER BY id LIMIT 5000",
    }
    engine = make_engine()
    try:
        async with engine.connect() as connection:
            plans = {
                name: [dict(r) for r in (await connection.execute(text("EXPLAIN " + sql))).mappings()]
                for name, sql in queries.items()
            }
        print(json.dumps(plans, default=str, indent=2))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
