"""Create an immutable artifact from a clean committed checkout, without deployment."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    status = subprocess.check_output(["git", "status", "--porcelain"], text=True)
    if status:
        raise SystemExit("Commit reviewed changes before packaging")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    requested = subprocess.check_output(["git", "rev-parse", args.commit + "^{commit}"], text=True).strip()
    if requested != head:
        raise SystemExit("Use a checkout at the exact release commit")
    folder = Path(args.output)
    folder.mkdir(parents=True, exist_ok=True)
    artifact = folder / f"club-backend-{head}.tar.gz"
    if artifact.exists():
        raise SystemExit("Artifact exists; refusing overwrite")
    subprocess.run(
        ["git", "archive", "--format=tar.gz", "--prefix=backend/", "--output=" + str(artifact), head],
        check=True,
    )
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    (folder / f"{artifact.name}.json").write_text(
        json.dumps({"commit": head, "sha256": digest, "file": artifact.name}, indent=2) + "\n"
    )
    print(json.dumps({"commit": head, "sha256": digest, "artifact": str(artifact)}))


if __name__ == "__main__":
    main()
