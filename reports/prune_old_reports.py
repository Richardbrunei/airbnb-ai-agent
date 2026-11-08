"""
Prune old daily-report / AI-analysis text files.

Since 2026-11-08 reports live in reports/text_reports/<date>/ day
folders; a folder older than RETENTION_DAYS is removed whole (both the
market report and the AI analysis for that day). Legacy flat files in
reports/ (pre-migration) are still pruned by FILENAME date - mtimes
are never trusted (Actions checkouts reset them).

Never touches the trend report/map HTML, the DB, or anything undated.
Always exits 0 (tidiness must never break the pipeline).
"""
import re
import shutil
from datetime import date, timedelta
from pathlib import Path

RETENTION_DAYS = 31
REPORTS = Path(__file__).resolve().parent
TEXT_REPORTS = REPORTS / "text_reports"

DATE_RE = re.compile(r"^(?:market_report|ai_analysis)_(\d{4}-\d{2}-\d{2})")
DAY_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def file_date(name):
    m = DATE_RE.match(name)
    return date.fromisoformat(m.group(1)) if m else None


def main():
    cutoff = date.today() - timedelta(days=RETENTION_DAYS)
    removed = []
    # day-folder era (2026-11-08+): folder name is the date
    if TEXT_REPORTS.is_dir():
        for d in sorted(TEXT_REPORTS.iterdir()):
            if d.is_dir() and DAY_DIR_RE.match(d.name):
                if date.fromisoformat(d.name) < cutoff:
                    shutil.rmtree(d)
                    removed.append(d.name + '/')
    # legacy flat era: date from the filename
    for pattern in ("market_report_*.txt", "ai_analysis_*.txt"):
        for f in sorted(REPORTS.glob(pattern)):
            d = file_date(f.name)
            if d and d < cutoff:
                f.unlink()
                removed.append(f.name)
    print(f"pruned {len(removed)} item(s) older than {cutoff.isoformat()}"
          + (": " + ", ".join(str(x) for x in removed[:8])
             + (" ..." if len(removed) > 8 else "") if removed else ""))


if __name__ == "__main__":
    main()
