"""Create a private TEST certificate and render optional TLS nginx configuration."""

import argparse
import ipaddress
import os
from pathlib import Path
import subprocess

p = argparse.ArgumentParser()
p.add_argument("--host", required=True)
a = p.parse_args()
if not ipaddress.ip_address(a.host).is_private:
    raise SystemExit("Only a private isolated test IP is allowed")
root = Path(__file__).resolve().parents[1]
folder = root / ".local" / "tls"
folder.mkdir(parents=True, exist_ok=True)
folder.chmod(0o700)
key, cert = folder / "test.key", folder / "test.crt"
if key.exists() or cert.exists():
    raise SystemExit("Test TLS files already exist; refusing to overwrite")
old = os.umask(0o077)
try:
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "30",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-subj",
            "/CN=club-isolated-test",
            "-addext",
            f"subjectAltName=IP:{a.host}",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
finally:
    os.umask(old)
source = (root / "deploy/nginx.test.conf").read_text()
source = source.replace(
    "listen 8080 backlog=2048;",
    """listen 8080 backlog=2048;
    listen 8443 ssl backlog=2048;
    ssl_certificate /etc/nginx/test-tls/test.crt;
    ssl_certificate_key /etc/nginx/test-tls/test.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_cache shared:club_tls:10m;
    ssl_session_timeout 10m;""",
)
(root / ".local/nginx.test.tls.conf").write_text(source)
print("Created isolated TLS configuration; key stays in ignored .local/tls")
