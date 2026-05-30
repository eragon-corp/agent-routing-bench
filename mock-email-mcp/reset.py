#!/usr/bin/env python3
"""Reset inbox.db to seed state."""
import shutil
import pathlib

SCRIPT_DIR = pathlib.Path(__file__).parent.resolve()
SEED_DB = SCRIPT_DIR / "seed.db"
INBOX_DB = SCRIPT_DIR / "inbox.db"


def main() -> None:
    if not SEED_DB.exists():
        print(f"ERROR: seed.db not found at {SEED_DB}. Run seed.py first.")
        raise SystemExit(1)
    shutil.copy2(SEED_DB, INBOX_DB)
    print(f"Reset complete. Copied {SEED_DB} → {INBOX_DB}")


if __name__ == "__main__":
    main()
