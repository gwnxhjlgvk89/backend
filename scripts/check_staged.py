"""Conservative guard against secrets/data being added to either repository."""

import re
import subprocess
import sys

paths = subprocess.check_output(
    ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"], text=True
).splitlines()
issues = []
for name in paths:
    if name.endswith((".sql", ".xlsx", ".xlsm", ".log")) or name.split("/")[-1] in (
        ".env",
        ".env.test",
        ".env.production",
    ):
        issues.append(name + ": private/generated file")
        continue
    raw = subprocess.check_output(["git", "show", ":" + name])
    try:
        body = raw.decode("utf-8")
    except UnicodeDecodeError:
        continue
    patterns = [
        r"AKIA[0-9A-Z]{16}",
        r"-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY-----",
        r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}",
    ]
    if any(re.search(pattern, body) for pattern in patterns):
        issues.append(name + ": possible credential")
if issues:
    print("\n".join(issues))
    sys.exit(1)
print(f"Staged scan: {len(paths)} files checked; no configured secret/data patterns found")
