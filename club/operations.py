"""Explicit maintenance commands. No action runs on import."""

import argparse
import asyncio
import getpass
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from sqlalchemy import delete, inspect, select, update
from sqlalchemy.engine import make_url

from club.config import settings
from club.db import make_engine, sessions
from club.legacy import apply_legacy, plan_legacy, read_legacy
from club.models import Activity, Audit, Club, Enrollment, Favorite, Idempotency, Job, Outbox, User
from club.security import verify_password
from club.services import consistency


def private_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        path.chmod(0o600)
        json.dump(value, f, ensure_ascii=False, indent=2, default=str)
        f.write("\n")


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def binary(name):
    homebrew = Path("/opt/homebrew/opt/mysql@8.4/bin") / name
    path = str(homebrew) if homebrew.exists() else shutil.which(name)
    if not path:
        raise RuntimeError(f"Missing {name}")
    return path


def mysql_process(action, path):
    url = make_url(settings().database_url)
    if not re.fullmatch(r"[A-Za-z0-9_]+", url.database or ""):
        raise ValueError("Unsupported database identifier")

    def quote(v):
        return (
            '"'
            + str(v or "").replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")
            + '"'
        )

    # Credentials are in a temporary 0600 option file, never process arguments.
    with tempfile.TemporaryDirectory(prefix="club-mysql-") as temp:
        cfg = Path(temp) / "client.cnf"
        cfg.write_text(
            "[client]\nhost="
            + quote(url.host)
            + "\nport="
            + str(url.port or 3306)
            + "\nuser="
            + quote(url.username)
            + "\npassword="
            + quote(url.password)
            + "\n"
        )
        cfg.chmod(0o600)
        command = [
            binary("mysqldump" if action == "backup" else "mysql"),
            "--defaults-extra-file=" + str(cfg),
        ]
        if action == "backup":
            command += [
                "--single-transaction",
                "--no-tablespaces",
                "--set-gtid-purged=OFF",
                "--hex-blob",
                url.database,
            ]
            with Path(path).open("xb") as out:
                Path(path).chmod(0o600)
                result = subprocess.run(command, stdout=out, stderr=subprocess.PIPE)
        else:
            with Path(path).open("rb") as inp:
                result = subprocess.run(
                    command + [url.database], stdin=inp, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
                )
        if result.returncode:
            raise RuntimeError(f"{action} failed; stderr suppressed to avoid exposing credentials")


async def state_summary(db):
    rows = (
        await db.execute(select(User.id, User.token_version).where(User.role == "student").order_by(User.id))
    ).all()
    entries = (
        await db.execute(
            select(Enrollment.student_id, Enrollment.club_id, Enrollment.source).order_by(
                Enrollment.student_id
            )
        )
    ).all()
    quotas = (
        await db.execute(select(Club.id, Club.capacity, Club.remaining, Club.version).order_by(Club.id))
    ).all()
    favs = (
        await db.execute(
            select(Favorite.student_id, Favorite.club_id).order_by(Favorite.student_id, Favorite.club_id)
        )
    ).all()
    state = json.dumps([list(map(list, v)) for v in (rows, entries, quotas, favs)])
    return {
        "students": len(rows),
        "enrollments": len(entries),
        "favorites": len(favs),
        "clubs_preserved": len(quotas),
        "fingerprint": hashlib.sha256(state.encode()).hexdigest(),
    }


async def reset_current(db, expected, actor):
    a = await db.get(Activity, 1, with_for_update=True)
    if not a or a.state not in ("paused", "draft"):
        raise ValueError("Pause the activity before reset")
    live = await db.get(User, actor.id, with_for_update=True)
    if not live or not live.active or live.role != "super_admin" or live.token_version != actor.token_version:
        raise ValueError("Super admin session changed")
    summary = await state_summary(db)
    if summary["fingerprint"] != expected:
        raise ValueError("Data changed; review a new reset preview")
    for model in (Favorite, Idempotency, Enrollment, Outbox, Job):
        await db.execute(delete(model))
    await db.execute(delete(User).where(User.role == "student"))
    await db.execute(update(Club).values(remaining=Club.capacity, version=Club.version + 1))
    a.state, a.starts_at, a.ends_at, a.cancel_until, a.allow_cancel = "draft", None, None, None, False
    a.version += 1
    db.add(Audit(actor_id=actor.id, action="data.reset", target="current", summary=summary))
    return summary


async def run(args):
    engine = make_engine()
    factory = sessions(engine)
    try:
        if args.action == "backup":
            path = Path(args.file)
            path.parent.mkdir(parents=True, exist_ok=True)
            async with factory() as db:
                a = await db.get(Activity, 1)
                if a and a.state == "published":
                    raise ValueError("Pause before maintenance backup")
                before = await state_summary(db)
            await asyncio.to_thread(mysql_process, "backup", path)
            async with factory() as db:
                after = await state_summary(db)
            if before != after:
                raise ValueError("Database changed during backup; do not use this backup for reset")
            private_json(
                str(path) + ".manifest.json",
                {
                    "sha256": digest(path),
                    "state": after,
                    "database": make_url(settings().database_url).database,
                },
            )
            print("Backup complete; perform isolated restore verification before any cleanup")
        elif args.action == "restore-test":
            url = make_url(settings().database_url)
            if settings().club_env != "test" or not url.database.endswith("_restore"):
                raise ValueError("Restore is limited to an empty test database ending in _restore")
            async with engine.connect() as conn:
                tables = await conn.run_sync(lambda c: inspect(c).get_table_names())
            if tables:
                raise ValueError("Restore target is not empty; nothing was overwritten")
            manifest = json.loads(Path(str(args.file) + ".manifest.json").read_text())
            if digest(args.file) != manifest["sha256"]:
                raise ValueError("Backup checksum mismatch")
            await asyncio.to_thread(mysql_process, "restore", args.file)
            async with factory() as db:
                if await consistency(db) or await state_summary(db) != manifest["state"]:
                    raise ValueError("Restore validation failed")
            private_json(
                str(args.file) + ".restore-verified.json",
                {"sha256": manifest["sha256"], "target": url.database, "verified": True},
            )
            print("Isolated restore verified")
        elif args.action == "legacy-plan":
            async with factory() as db:
                plan = plan_legacy(await read_legacy(db))
            private_json(args.file, {k: v for k, v in plan.items() if k != "enrollments"})
            print(json.dumps({"conflicts": len(plan["issues"]), "fingerprint": plan["fingerprint"]}))
        elif args.action == "legacy-apply":
            if not args.maintenance_confirm:
                raise ValueError("Require maintenance confirmation; stop legacy writes first")
            reviewed = json.loads(Path(args.file).read_text())
            async with factory() as db, db.begin():
                await apply_legacy(
                    db, await read_legacy(db, lock=True), reviewed["fingerprint"], args.legacy_timezone
                )
                if await consistency(db):
                    raise ValueError("Post-migration quota validation failed")
            print("Migration committed; activity remains draft; legacy tables preserved")
        elif args.action == "reset-preview":
            async with factory() as db:
                summary = await state_summary(db)
            private_json(args.file, summary)
            print(json.dumps(summary))
        elif args.action == "reset-apply":
            if not args.maintenance_confirm or not args.backup or not args.actor:
                raise ValueError("Maintenance, verified backup, and super admin identity are required")
            receipt = json.loads(Path(str(args.backup) + ".restore-verified.json").read_text())
            manifest = json.loads(Path(str(args.backup) + ".manifest.json").read_text())
            preview = json.loads(Path(args.file).read_text())
            if (
                not receipt.get("verified")
                or digest(args.backup) != receipt["sha256"]
                or manifest["sha256"] != receipt["sha256"]
            ):
                raise ValueError("Verified backup checksum mismatch")
            if preview != manifest["state"]:
                raise ValueError("Backup does not match reviewed reset data")
            async with factory() as db:
                actor = await db.scalar(select(User).where(User.username == args.actor))
                if (
                    not actor
                    or actor.role != "super_admin"
                    or not actor.active
                    or not await verify_password(
                        getpass.getpass("Super admin password: "), actor.password_hash
                    )
                ):
                    raise ValueError("Super admin authentication failed")
            if (
                input("Type RESET " + preview["fingerprint"][:12] + " to confirm reviewed cleanup: ")
                != "RESET " + preview["fingerprint"][:12]
            ):
                raise ValueError("Reset cancelled")
            async with factory() as db, db.begin():
                await reset_current(db, preview["fingerprint"], actor)
            print(
                "Current v2 cohort reset. Legacy tables and private backup files retained for separate reviewed cleanup."
            )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument(
        "action",
        choices=["backup", "restore-test", "legacy-plan", "legacy-apply", "reset-preview", "reset-apply"],
    )
    p.add_argument("--file", required=True)
    p.add_argument("--backup")
    p.add_argument("--actor")
    p.add_argument("--maintenance-confirm", action="store_true")
    p.add_argument("--legacy-timezone", default="Asia/Shanghai")
    asyncio.run(run(p.parse_args()))
