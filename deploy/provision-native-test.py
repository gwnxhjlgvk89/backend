"""Provision the explicitly authorized, empty 2026-09-30 native test host.

Run as root after installing locked Python dependencies in the fixed release.
Only synthetic club_test is created. No DNS, public TLS or production migration.
Credentials are created on-host in mode-600 files and never printed.
"""

import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
from urllib.parse import urlsplit

RELEASE = Path("/srv/club/releases/81adef2bfa4441fc54d014f445e1f81383242a13")


def run(argv, **kwargs):
    return subprocess.run(argv, check=True, **kwargs)


def mysql(sql):
    return subprocess.check_output(["mysql", "--batch", "--skip-column-names"], input=sql, text=True)


def private_file(path, content):
    with os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w") as f:
        f.write(content)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-url", default="https://43.142.19.144")
    args = parser.parse_args()
    url = urlsplit(args.public_url)
    if url.scheme != "https" or not url.hostname or url.username or url.password or url.path:
        raise SystemExit("Explicit HTTPS origin required")
    if os.geteuid() != 0 or socket.gethostname() != "VM-0-11-ubuntu":
        raise SystemExit("Only the explicitly authorized new host is permitted")
    if Path("/srv/club/current").exists() or Path("/etc/club/load-test.env").exists():
        raise SystemExit("Existing deployment found; refusing replacement")
    if mysql("SHOW DATABASES LIKE 'club%';").strip():
        raise SystemExit("Existing club database found; refusing initialization")
    if mysql("SELECT user FROM mysql.user WHERE user LIKE 'club%';").strip():
        raise SystemExit("Existing club database user found")
    if not (RELEASE / ".venv/bin/python").exists():
        raise SystemExit("Fixed release and Python dependencies must exist first")
    commands = subprocess.check_output(["redis-cli", "--raw", "COMMAND", "INFO", "GETDEL"], text=True)
    if "getdel" not in commands.splitlines():
        raise SystemExit("Redis GETDEL support is required (Redis >=6.2); upgrade before provisioning")

    run(["install", "-d", "-m", "700", "/etc/club"])
    if subprocess.run(["id", "club"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        run(["useradd", "--system", "--user-group", "--home-dir", "/srv/club", "--shell", "/usr/sbin/nologin", "club"])
    for folder in ("/srv/club/shared", "/srv/club/shared/test-files"):
        run(["install", "-d", "-m", "750", "-o", "club", "-g", "club", folder])
    Path("/srv/club/current").symlink_to(RELEASE, target_is_directory=True)

    mysql("CREATE DATABASE club_test CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;")
    common = {
        "CLUB_ENV": "test", "REDIS_URL": "redis://127.0.0.1:6379/2", "REDIS_PREFIX": "club:test",
        "JWT_SECRET": secrets.token_urlsafe(48), "PUBLIC_URL": args.public_url,
        "STORAGE_DIR": "/srv/club/shared/test-files", "STORAGE_BACKEND": "local",
        "POOL_SIZE": "15", "POOL_OVERFLOW": "3", "READ_POOL_SIZE": "4",
    }
    for role in ("app", "migrate"):
        user = "club_test_" + role
        password = secrets.token_hex(32)
        grants = "SELECT,INSERT,UPDATE,DELETE" if role == "app" else "ALL PRIVILEGES"
        mysql(f"CREATE USER '{user}'@'localhost' IDENTIFIED BY '{password}';"
              f"GRANT {grants} ON club_test.* TO '{user}'@'localhost';")
        values = dict(common, DATABASE_URL=f"mysql+asyncmy://{user}:{password}@127.0.0.1:3306/club_test?charset=utf8mb4")
        name = "load-test.env" if role == "app" else "load-test-migrate.env"
        private_file("/etc/club/" + name, "".join(k + "=" + v + "\n" for k, v in values.items()))

    Path("/etc/mysql/mysql.conf.d/club-test.cnf").write_text(
        "[mysqld]\nbind-address=127.0.0.1\nmysqlx-bind-address=127.0.0.1\n"
        "innodb_buffer_pool_size=805306368\nmax_connections=151\n"
    )
    redis = Path("/etc/redis/redis.conf")
    with redis.open("a") as f:
        f.write("\n# Club isolated native capacity test\nbind 127.0.0.1 ::1\nmaxmemory 201326592\nmaxmemory-policy noeviction\n")
    run(["systemctl", "restart", "mysql", "redis-server"])
    launcher = [str(RELEASE / ".venv/bin/python"), str(RELEASE / "deploy/run-private-env.py")]
    run(launcher + ["/etc/club/load-test-migrate.env", str(RELEASE / ".venv/bin/alembic"), "upgrade", "head"], cwd=RELEASE)
    for action in ("seed", "details"):
        run(launcher + ["/etc/club/load-test.env", str(RELEASE / ".venv/bin/python"), "-m", "club.load_fixture", action], cwd=RELEASE)

    for service in ("club-api", "club-worker"):
        body = (RELEASE / "deploy" / (service + ".service")).read_text()
        body = body.replace("/etc/club/production.env", "/etc/club/load-test.env")
        body = body.replace("StandardOutput=journal", "LogNamespace=club\nStandardOutput=journal")
        Path("/etc/systemd/system/" + service + ".service").write_text(body)
    Path("/etc/systemd/journald@club.conf.d").mkdir(exist_ok=True)
    Path("/etc/systemd/journald@club.conf.d/limits.conf").write_text(
        "[Journal]\nSystemMaxUse=128M\nRuntimeMaxUse=32M\nMaxRetentionSec=14day\n"
    )
    run(["systemctl", "daemon-reload"])
    run(["systemctl", "enable", "--now", "club-api", "club-worker"])
    print(json.dumps({"database": "club_test", "synthetic_accounts": 3000, "clubs": 42,
                      "application_release": RELEASE.name, "public_ingress_configured": False,
                      "credentials_logged": False}))


if __name__ == "__main__":
    main()
