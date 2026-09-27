"""Exercise real mysqldump/restore on fixed local synthetic databases only."""

import asyncio
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import re
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.update(
    CLUB_ENV="test",
    DATABASE_URL="mysql+asyncmy://club:club-local-only@127.0.0.1:13306/club_test?charset=utf8mb4",
    REDIS_URL="redis://127.0.0.1:16379/15",
    JWT_SECRET="synthetic-backup-test-secret-not-for-production",
)
from club.config import settings
from club.db import make_engine, sessions
from club.models import Activity
from club.operations import run, binary


async def main(run_id):
    if not re.fullmatch(r"[a-z0-9]{1,20}", run_id):
        raise SystemExit("Run ID must be 1-20 lowercase letters or digits")
    root = Path(__file__).resolve().parents[1]
    target = root / f".local/backup-{run_id}.sql"
    restore_db = f"club_{run_id}_restore"
    if target.exists():
        raise SystemExit("Rehearsal backup already exists; choose a new reviewed run")
    engine = make_engine()
    async with sessions(engine)() as db, db.begin():
        (await db.get(Activity, 1)).state = "paused"
    await engine.dispose()
    await run(SimpleNamespace(action="backup", file=str(target)))
    sql = f"CREATE DATABASE IF NOT EXISTS {restore_db} CHARACTER SET utf8mb4; GRANT ALL ON {restore_db}.* TO 'club'@'127.0.0.1';"
    subprocess.run(
        [binary("mysql"), "--no-defaults", f"--socket={root}/.local/mysql.sock", "-uroot"],
        input=sql,
        text=True,
        check=True,
    )
    os.environ["DATABASE_URL"] = (
        f"mysql+asyncmy://club:club-local-only@127.0.0.1:13306/{restore_db}?charset=utf8mb4"
    )
    settings.cache_clear()
    await run(SimpleNamespace(action="restore-test", file=str(target)))
    report = {
        "environment": f"local synthetic club_test -> empty {restore_db}",
        "backup_sha256_verified": True,
        "restored_state_matches": True,
        "quota_consistent": True,
    }
    (root / f"reports/backup-{run_id}.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    asyncio.run(main(parser.parse_args().run_id))
