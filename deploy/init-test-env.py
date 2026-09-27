"""Run on the explicitly authorized test host. Does not print credentials."""

from pathlib import Path
import secrets

p = Path(__file__).parent / ".env.test"
if p.exists():
    print("Existing test environment retained")
else:
    with p.open("x") as f:
        p.chmod(0o600)
        for key in ("TEST_DB_PASSWORD", "TEST_ROOT_PASSWORD", "TEST_JWT_SECRET"):
            f.write(key + "=" + secrets.token_hex(24) + "\n")
        f.write("TEST_HOST=192.168.100.130\nTEST_BIND=192.168.100.130\n")
    print("Independent test environment created")
