"""Temporary TEST-only request timing; never records bodies, credentials or query strings."""

import argparse
import json
from pathlib import Path
import subprocess

NAME = "club-capacity-test_nginx_1"
LOG = "/tmp/club-test-requests.jsonl"
PREFIX = """map $http_x_load_request_id $club_probe {
    default "";
    "~^[a-f0-9]{32}$" $http_x_load_request_id;
}
log_format club_diag escape=json '{"epoch":$msec,"probe":"$club_probe",'
    '"api_id":"$upstream_http_x_request_id","uri":"$uri","method":"$request_method",'
    '"status":$status,"rt":$request_time,"uct":"$upstream_connect_time",'
    '"uht":"$upstream_header_time","urt":"$upstream_response_time",'
    '"us":"$upstream_status","bytes":$bytes_sent,"conn":$connection,'
    '"conn_requests":$connection_requests,"complete":"$request_completion"}';
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["enable", "disable", "read"])
    args = parser.parse_args()
    info = json.loads(subprocess.check_output(["podman", "inspect", NAME]))[0]
    labels = info["Config"]["Labels"]
    if labels.get("com.docker.compose.project") != "club-capacity-test":
        raise SystemExit("Only isolated TEST container allowed")
    root = Path(__file__).resolve().parents[1]
    config = root / ".local/nginx.test.tls.conf"
    backup = root / ".local/tracing-nginx.before.conf"
    if args.action == "read":
        subprocess.run(["podman", "exec", NAME, "cat", LOG], check=True)
        return
    if args.action == "enable":
        source = config.read_text()
        if "club_diag" in source or source.count("access_log off;") != 1:
            raise SystemExit("Unexpected configuration; refusing to modify")
        with backup.open("x") as handle:
            handle.write(source)
        config.write_text(
            PREFIX + source.replace("access_log off;", f"access_log {LOG} club_diag buffer=64k flush=1s;")
        )
    else:
        if not backup.exists() or "club_diag" not in config.read_text():
            raise SystemExit("No owned diagnostic configuration to restore")
        source = config.read_text()
        config.write_text(backup.read_text())
    try:
        subprocess.run(["podman", "exec", NAME, "nginx", "-t"], check=True)
        subprocess.run(["podman", "exec", NAME, "nginx", "-s", "reload"], check=True)
    except BaseException:
        config.write_text(source)
        raise
    if args.action == "disable":
        backup.unlink()
    print(json.dumps({"action": args.action, "test_only": True, "bodies_or_queries_logged": False}))


if __name__ == "__main__":
    main()
