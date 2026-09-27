"""
Ghost probes — is a vanished competitor booked or removed?

Airbnb search never returns listings whose calendar is closed for the
target window, so an unavailable competitor simply vanishes from results.
That absence is ambiguous: booked (demand), host-blocked (personal), or
delisted (supply exit). Fetching the listing page directly splits it:

- page up            → "live"     → booked or host-blocked (demand signal)
- 404 / removed page → "delisted" → market exit
- anything else      → "error"    → e.g. 403 blocked; retried next run

Etiquette: only vanished listings, at most `max_probes` per run, one
probe per listing per day (UNIQUE(probe_date, listing_id)), ~2 s between
requests, browser impersonation. Runs on the Actions runner as part of
the daily pipeline; verdicts land in data.listing_probes and are rendered
by reports/trend_report.py (amber = likely booked, red = removed).
"""

import logging
import time
from datetime import datetime

logger = logging.getLogger(__name__)

# Phrases Airbnb renders on removed/deactivated listing pages
DELISTED_MARKERS = (
    "no longer available",
    "this listing was removed",
    "this listing is no longer",
    "page not found",
    "we can’t find that page",
)


def classify(status_code: int, body: str) -> str:
    """Map an HTTP response to live | delisted | error."""
    if status_code in (404, 410):   # Not Found / Gone — both permanent exits
        return "delisted"
    low = (body or "").lower()
    if any(m in low for m in DELISTED_MARKERS):
        return "delisted"
    if status_code == 200:
        return "live"
    return "error"


def probe_ghosts(max_probes: int = 10, lookback_days: int = 3, db_path=None) -> dict:
    """Probe vanished competitors and store verdicts. Never raises."""
    from data import storage
    from curl_cffi import requests

    results = {"ghosts": 0, "probed": 0, "live": 0, "delisted": 0,
               "errors": 0, "skipped": 0}
    try:
        ghosts = storage.find_ghosts(lookback_days=lookback_days, db_path=db_path)
    except Exception as e:  # missing table, schema hiccup
        logger.warning(f"find_ghosts failed: {e}")
        return results
    results["ghosts"] = len(ghosts)

    today = datetime.now().strftime("%Y-%m-%d")
    todo = []
    for g in ghosts:
        if g["probe_date"] == today:            # already probed today
            results["skipped"] += 1
        elif g["probe_status"] == "delisted":   # confirmed exit; don't re-probe
            results["skipped"] += 1
        elif not g["url"]:
            continue
        else:
            todo.append(g)
        if len(todo) >= max_probes:
            break

    for g in todo:
        try:
            r = requests.get(g["url"], impersonate="chrome", timeout=20,
                             allow_redirects=True)
            status = classify(r.status_code, r.text[:6000])
            detail = f"http {r.status_code}"
        except Exception as e:
            status, detail = "error", f"{type(e).__name__}: {str(e)[:90]}"
        try:
            storage.store_probe(g["listing_id"], g["url"], g["title"],
                                status, detail, db_path=db_path)
        except Exception as e:
            logger.warning(f"store_probe failed for {g['listing_id']}: {e}")
            continue
        results["probed"] += 1
        if status == "live":
            results["live"] += 1
        elif status == "delisted":
            results["delisted"] += 1
        else:
            results["errors"] += 1
        time.sleep(2)

    logger.info(f"Ghost probe: {results}")
    return results
