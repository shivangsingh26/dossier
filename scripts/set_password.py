"""
scripts/set_password.py — Set or update a user's dashboard login password.

Stores SHA-256 hashed passwords in profile/auth.json.
Run this once per user before sharing the dashboard link.

Usage:
    python scripts/set_password.py --user krishna --password mypassword123
    python scripts/set_password.py --user anushthan --password mypassword456
    python scripts/set_password.py --user shivang --password mypassword789
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

AUTH_FILE = Path("profile/auth.json")


def hash_password(password: str) -> str:
    """Return SHA-256 hex digest of the password."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def set_password(user: str, password: str) -> None:
    """Upsert the hashed password for a user in profile/auth.json."""
    auth: dict = {}
    if AUTH_FILE.exists():
        auth = json.loads(AUTH_FILE.read_text(encoding="utf-8"))

    auth[user] = hash_password(password)
    AUTH_FILE.write_text(json.dumps(auth, indent=2), encoding="utf-8")
    print(f"Password set for user '{user}' → {AUTH_FILE}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Set dashboard password for a Dossier user.")
    parser.add_argument("--user",     required=True, help="User name (e.g. shivang, krishna, anushthan)")
    parser.add_argument("--password", required=True, help="Password to set")
    args = parser.parse_args()

    if len(args.password) < 6:
        print("Error: password must be at least 6 characters.")
        sys.exit(1)

    set_password(args.user, args.password)
