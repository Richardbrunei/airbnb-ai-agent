"""
Prune old daily-report / AI-analysis text files.

Deletes reports/market_report_*.txt and reports/ai_analysis_*.txt whose
embedded date (parsed from the FILENAME) is older than RETENTION_DAYS.
Filenames, not mtimes — Actions checkouts reset mtimes at checkout time.

Never touches the trend report/map HTML, the DB, or anything undated.
Always exits 0 (tidiness must never break the pipeline).
"""
import re
from datetime import date, timedelta
from pathlib import Path

RETENTION_DAYS = 31
REPORTS = Path(__file__).resolve().parent

DATE_RE = re.compile(r"^(?:market_report|ai_analysis)_(\d{4}-\d{2}-\d{2})")


def file_date(name: str):
    m = DATE_RE.match(name)
    return date.fromisoformat(m.group(1)) if m else None


def main():
    cutoff = date.today() - timedelta(days=RETENTION_DAYS)
    removed = []
    for pattern in ("market_report_*.txt", "ai_analysis_*.txt"):
        for f in sorted(REPORTS.glob(pattern)):
            d = file_date(f.name)
            if d and d < cutoff:
                f.unlink()
                removed.append(f.name)
    print(f"pruned {len(removed)} file(s) older than {cutoff.isoformat()}"
          + (f": {', '.join(removed[:8])}" + (" …" if len(removed) > 8 else "")
             if removed else ""))


if __name__ == "__main__":
    main()
