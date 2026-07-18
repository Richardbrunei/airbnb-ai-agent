#!/usr/bin/env python3
"""
Check if today's market monitoring run already happened.
If not, run it. Used as a cron fallback for missed runs.

Checks market_snapshots for today's date. If missing, runs main.py.
"""

import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).parent
DB_PATH = PROJECT_DIR / "data" / "market.db"
LOG_FILE = PROJECT_DIR / "logs" / "daily.log"


def already_ran_today() -> bool:
    """Check if a snapshot exists for today's date."""
    if not DB_PATH.exists():
        return False

    today = datetime.now().strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute(
            "SELECT 1 FROM market_snapshots WHERE date = ?", (today,)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def run_pipeline() -> int:
    """Run main.py and return exit code."""
    result = subprocess.run(
        [sys.executable, "main.py"],
        cwd=PROJECT_DIR,
        stdout=open(LOG_FILE, "a"),
        stderr=subprocess.STDOUT,
    )
    return result.returncode


if __name__ == "__main__":
    if already_ran_today():
        print(f"[{datetime.now():%Y-%m-%d %H:%M}] Already ran today, skipping.")
        sys.exit(0)

    print(
        f"[{datetime.now():%Y-%m-%d %H:%M}] Missed run detected, executing pipeline...",
        file=open(LOG_FILE, "a"),
    )
    exit_code = run_pipeline()
    sys.exit(exit_code)
