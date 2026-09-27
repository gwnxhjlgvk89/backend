"""Owns only processes/data under backend/.local. Never uses brew services."""

import argparse
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".local"
MYSQL = Path("/opt/homebrew/opt/mysql@8.4/bin")


def binary(name):
    found = (MYSQL / name) if (MYSQL / name).exists() else shutil.which(name)
    if not found:
        raise SystemExit(f"Missing executable: {name}")
    return str(found)


def start(name, args):
    pidfile = STATE / f"{name}.owner.pid"
    if pidfile.exists():
        try:
            os.kill(int(pidfile.read_text()), 0)
            print(f"{name}: already running")
            return
        except ProcessLookupError:
            pidfile.unlink()
    with (STATE / f"{name}.log").open("ab") as log:
        p = subprocess.Popen(args, cwd=ROOT, stdout=log, stderr=log, start_new_session=True)
    pidfile.write_text(str(p.pid))
    time.sleep(0.5)
    if p.poll() is not None:
        raise SystemExit(f"{name} failed; inspect .local/{name}.log")
    print(f"{name}: started pid={p.pid}")


def main():
    action = argparse.ArgumentParser()
    action.add_argument("action", choices=["start", "stop", "status"])
    args = action.parse_args()
    STATE.mkdir(mode=0o700, exist_ok=True)
    if args.action == "start":
        if not (ROOT / ".env").exists():
            shutil.copy(ROOT / ".env.example", ROOT / ".env")
            (ROOT / ".env").chmod(0o600)
        data = STATE / "mysql"
        if not (data / "mysql").exists():
            data.mkdir(exist_ok=True)
            subprocess.run(
                [binary("mysqld"), "--no-defaults", "--initialize-insecure", f"--datadir={data}"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        socket = str(STATE / "mysql.sock")
        start(
            "mysql",
            [
                binary("mysqld"),
                "--no-defaults",
                f"--datadir={data}",
                "--port=13306",
                "--bind-address=127.0.0.1",
                f"--socket={socket}",
                "--mysqlx=0",
                "--max-connections=150",
                "--innodb-buffer-pool-size=256M",
                f"--pid-file={STATE / 'mysql.pid'}",
            ],
        )
        for _ in range(60):
            result = subprocess.run(
                [binary("mysqladmin"), "--no-defaults", f"--socket={socket}", "-uroot", "ping"],
                capture_output=True,
            )
            if result.returncode == 0:
                break
            time.sleep(1)
        else:
            raise SystemExit("MySQL startup timeout")
        sql = "CREATE DATABASE IF NOT EXISTS club_dev CHARACTER SET utf8mb4; CREATE DATABASE IF NOT EXISTS club_test CHARACTER SET utf8mb4; CREATE USER IF NOT EXISTS 'club'@'127.0.0.1' IDENTIFIED BY 'club-local-only'; GRANT ALL ON club_dev.* TO 'club'@'127.0.0.1'; GRANT ALL ON club_test.* TO 'club'@'127.0.0.1';"
        subprocess.run(
            [binary("mysql"), "--no-defaults", f"--socket={socket}", "-uroot"],
            input=sql,
            text=True,
            check=True,
        )
        start(
            "redis",
            [
                binary("redis-server"),
                "--bind",
                "127.0.0.1",
                "--port",
                "16379",
                "--dir",
                str(STATE),
                "--dbfilename",
                "redis.rdb",
                "--appendonly",
                "no",
                "--maxmemory",
                "128mb",
                "--maxmemory-policy",
                "noeviction",
            ],
        )
    elif args.action == "stop":
        for name in ("worker", "api", "redis", "mysql"):
            p = STATE / f"{name}.owner.pid"
            if p.exists():
                pid = int(p.read_text())
                cmd = subprocess.run(
                    ["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True
                ).stdout
                # Refuse to signal a reused PID unrelated to this workspace.
                if str(STATE) in cmd or (str(ROOT / ".venv") in cmd and name in {"api", "worker"}):
                    os.kill(pid, signal.SIGTERM)
                p.unlink()
    else:
        for p in STATE.glob("*.owner.pid"):
            pid = int(p.read_text())
            try:
                os.kill(pid, 0)
                print(p.stem, "running", pid)
            except ProcessLookupError:
                print(p.stem, "stopped")


if __name__ == "__main__":
    main()
