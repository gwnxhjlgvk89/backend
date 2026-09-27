"""Create a private TEST certificate and render optional TLS nginx configuration."""

import argparse
import ipaddress
import os
from pathlib import Path
import subprocess

p = argparse.ArgumentParser()
p.add_argument("--host", required=True)
p.add_argument("--algorithm", choices=["rsa2048", "ecdsa256"], default="rsa2048")
p.add_argument("--render-only", action="store_true", help="Reuse the existing private TEST certificate")
a = p.parse_args()
if not ipaddress.ip_address(a.host).is_private:
    raise SystemExit("Only a private isolated test IP is allowed")
root = Path(__file__).resolve().parents[1]
folder = root / ".local" / ("tls" if a.algorithm == "rsa2048" else "tls-ecdsa")
folder.mkdir(parents=True, exist_ok=True)
folder.chmod(0o700)
key, cert = folder / "test.key", folder / "test.crt"
if a.render_only:
    if not key.is_file() or not cert.is_file():
        raise SystemExit("Existing TEST key/certificate required for rendering")
    subprocess.run(
        ["openssl", "x509", "-in", str(cert), "-noout", "-checkip", a.host],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
else:
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
                *(
                    ["rsa:2048"]
                    if a.algorithm == "rsa2048"
                    else ["ec", "-pkeyopt", "ec_paramgen_curve:P-256"]
                ),
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
print("Rendered isolated TLS configuration; private key remains in ignored .local directory")
