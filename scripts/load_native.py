"""Explicit adapter for authorized load tests on the native Tencent deployment.

Only changes the control/observation transport. The public driver still refuses
non-TEST health, and fixtures still refuse any database except club_test.
"""

import os
import shlex


def enabled():
    return os.environ.get("CLUB_NATIVE_CAPACITY") == "1"


TARGETS = {
    "ubuntu@150.158.22.139": {
        "url": "https://wjy-1214.cloud",
        "cpu_scope": "Actual Tencent production 4 vCPU / approximately 4GB, native systemd services",
        "data_scope": "Temporary club_test database; original club_v2_prod untouched",
    },
    "ubuntu@43.142.19.144": {
        "url": "https://wjy-1214.cloud",
        "cpu_scope": "Actual new Tencent host 4 vCPU / 8GB, native systemd services, no CPU quota",
        "data_scope": "Dedicated synthetic club_test on new host; user switched DNS; old production data untouched",
    },
}


def target(args):
    selected = TARGETS.get(args.ssh)
    if selected is None or (hasattr(args, "url") and args.url != selected["url"]):
        raise ValueError("Native adapter requires an explicitly authorized host and matching HTTPS endpoint")
    return selected


def scope(args):
    selected = target(args)
    return {
        "network_scope": "Independent wired Linux generator to actual Tencent public HTTPS; no artificial shaping",
        "cpu_scope": selected["cpu_scope"],
        "data_scope": selected["data_scope"],
        "production_capacity_verified": False,
    }


def translate(args, command):
    target(args)
    argv = shlex.split(command)
    prefix = ["podman", "exec", "club-capacity-test_api_1", "python"]
    launcher = "cd /srv/club/current && sudo .venv/bin/python deploy/run-private-env.py /etc/club/load-test.env .venv/bin/python "
    guard = "from club.config import settings; from sqlalchemy.engine import make_url; s=settings(); assert s.club_env=='test' and make_url(s.database_url).database=='club_test' and s.redis_prefix=='club:test'\n"
    if argv[:4] == prefix:
        tail = argv[4:]
        if len(tail) == 2 and tail[0] == "-c":
            code = tail[1].replace("http://127.0.0.1:8000/metrics", "http://127.0.0.1:8001/metrics")
            return launcher + "-c " + shlex.quote(guard + code)
        if tail[:2] == ["-m", "club.load_fixture"]:
            return launcher + shlex.join(tail)
    if command == "podman inspect --format '{{.Image}}' club-capacity-test_api_1":
        return "readlink /srv/club/current"
    if command == "podman inspect --format '{{json .Config.Cmd}}' club-capacity-test_api_1":
        return "python3 -c " + shlex.quote(
            "import json,subprocess;print(json.dumps(subprocess.check_output(['systemctl','show','club-api','-p','ExecStart','--value'],text=True).strip()))"
        )
    if command == "python3 ~/club-system-test/backend/deploy/metrics-test.py":
        return "sudo python3 /etc/club/load-snapshot.py"
    if (
        argv[:2] == ["python3", "-c"]
        and len(argv) == 3
        and "root=Path.home()/'club-system-test/backend'" in argv[2]
    ):
        names = [
            "/etc/nginx/nginx.conf",
            "/etc/nginx/club-routes.conf",
            "/etc/nginx/conf.d/club-v2.conf",
            "/etc/systemd/system/club-api.service",
            "/etc/systemd/system/club-worker.service",
            "/srv/club/current/uv.lock",
        ]
        code = (
            "from pathlib import Path;import hashlib,json;names="
            + repr(names)
            + ";print(json.dumps({n:hashlib.sha256(Path(n).read_bytes()).hexdigest() for n in names}))"
        )
        return "sudo python3 -c " + shlex.quote(code)
    raise ValueError("Unrecognized native control command; refusing fallback")
