"""Run an explicit command with a root-only environment file; never echo its values."""

import os
from pathlib import Path
import sys

path = Path(sys.argv[1])
if path.stat().st_mode & 0o077:
    raise SystemExit("Environment file must be private")
env = os.environ.copy()
env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
for line in path.read_text().splitlines():
    if line.strip() and not line.lstrip().startswith("#"):
        key, value = line.split("=", 1)
        env[key] = value
os.execvpe(sys.argv[2], sys.argv[2:], env)
