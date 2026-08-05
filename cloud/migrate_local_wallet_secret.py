"""Migrate the DPAPI-protected local agent wallet directly to Secret Manager.

The plaintext agent key is held only in this process memory and is passed to
gcloud over stdin. It is never printed, logged, or written to a temporary file.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit("usage: migrate_local_wallet_secret.py UID GCLOUD_PATH PROJECT")
    uid, gcloud_path, project = sys.argv[1:]
    trading_server = Path(__file__).resolve().parents[1] / "trading_server"
    sys.path.insert(0, str(trading_server))
    from credential_store import load  # type: ignore

    credentials = load()
    if not credentials:
        raise SystemExit("Geen lokale DPAPI-agentwallet gevonden")
    master_address, api_private_key = credentials
    secret_id = f"tradementor-wallet-{uid}"

    describe = subprocess.run(
        [gcloud_path, "secrets", "describe", secret_id, "--project", project, "--quiet"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if describe.returncode != 0:
        subprocess.run(
            [gcloud_path, "secrets", "create", secret_id, "--project", project, "--replication-policy", "automatic", "--quiet"],
            stdout=subprocess.DEVNULL,
            check=True,
        )

    payload = json.dumps({"master": master_address, "key": api_private_key})
    subprocess.run(
        [gcloud_path, "secrets", "versions", "add", secret_id, "--project", project, "--data-file=-", "--quiet"],
        input=payload,
        text=True,
        stdout=subprocess.DEVNULL,
        check=True,
    )
    payload = ""
    api_private_key = ""
    print(secret_id)


if __name__ == "__main__":
    main()
