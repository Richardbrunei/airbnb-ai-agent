"""
AI analyst — automated anomaly read of each scrape via the z.ai API.

Runs on GitHub Actions after the daily pipeline (workflow step "AI
anomaly analysis"): builds a compact digest of the fresh data, sends it
with the anomaly rubric to z.ai's OpenAI-compatible chat API, and
writes the model's return to reports/ai_analysis_<date>_<HHMM>.txt.

Conventions:
- The file is ALWAYS written on a successful API call: the model replies
  NOTHING_UNUSUAL + a one-line digest when calm, or the full analysis
  when something cleared the rubric — so the file doubles as a daily
  heartbeat (no new file ⇒ run stalled or key missing).
- Never fatal: missing key / API failure ⇒ logged skip, exit 0. The
  scrape, scoring, reports and commit are never affected.
- Digest is strictly read-only (trend_report.load_data() + parse_recs);
  Actions stays the sole DB writer.

Config (workflow env):
- ZAI_API_KEY  — required (GitHub Actions secret)
- ZAI_MODEL    — optional, default "glm-5.3"
"""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger(__name__)

# Coding-plan endpoint (covered by subscription). The open-platform URL
# (api/paas/v4) requires a separate pay-per-token resource package — using it
# yields 429 error 1113 "insufficient balance".
ZAI_BASE_URL = os.environ.get("ZAI_BASE_URL", "https://api.z.ai/api/coding/paas/v4")
MODEL = os.environ.get("ZAI_MODEL", "glm-5.3")

SYSTEM_PROMPT = """You are the anomaly analyst for an Airbnb competitor-market monitor \
built around a hypothetical 4BR "anchor" near UT Dallas (listed $250 — \
imaginary; disclose this whenever you quote prices or recommendations).

You receive a digest of the latest scrape. Flag ANY of:
- median day-over-day |change| >= 8%, or a clear reversal of the recent median trend
- comp-set size change >= 30% -> suspect a methodology/lens change (cross-check the
  changelog lines in the digest); a documented change is NOT a market anomaly
  (mention it in one line at most)
- discounting share shift >= 15 points in a day
- suggested price moves >= 5% day-over-day
- probe verdicts: any delisted (removed from market), or >= 3 likely-booked
- >= 5 competitors vanished or returned in one day
- data quality: probe errors, empty scrapes, suspicious price floors

Known context: 2026-09-19 search lens widened 10->20 km (comp-set sizes step up
sharply - a level shift, not a market move). 2026-09-20..26 saw a softening week
(median -28% from peak; discount share 85->33). Judge against recent volatility,
not long-run calm.

Respond in exactly one of two formats:
1. First line NOTHING_UNUSUAL, then ONE line: date, competitor count, median,
   discount share, and a 5-10 word state summary.
2. First line ANOMALY, then a tight analysis under 200 words: what moved with
   the numbers, likely cause (market vs methodology vs data-quality), and what
   it means for the anchor's $250 listing price."""


def build_digest():
    """Compact, model-readable digest of the latest scrape (read-only)."""
    from reports import trend_report as tr
    days, day_stats, hist, meta, probes = tr.load_data()
    recs = tr.parse_recs(days)
    last = days[-1]
    prev = days[-2] if len(days) > 1 else None

    lines = [f"Latest scrape date: {last}",
             "Day stats (date | competitors | median | range | % discounted):"]
    for s in day_stats[-8:]:
        lines.append(f"  {s['date']} | {s['count']} | ${s['median']} | "
                     f"${s['min']}-${s['max']} | {s['disc_pct']:.0f}%")

    lines.append("Suggested-price history (latest run per day):")
    for d in days[-6:]:
        r = recs.get(d)
        if r:
            lines.append(f"  {d}: ${r['suggested']}"
                         + (f" @ {r['conf']}% conf" if r.get("conf") else ""))

    if prev:
        ids = {dd: {lid for lid in hist if dd in hist[lid]} for dd in (prev, last)}
        lines.append(f"Churn {prev} -> {last}: {len(ids[last] - ids[prev])} new, "
                     f"{len(ids[prev] - ids[last])} gone")

    movers = []
    for lid, h in hist.items():
        pts = sorted((d, r["price"]) for d, r in h.items() if r["price"])
        if len(pts) >= 2:
            title = dict(meta[lid])["title"] if lid in meta else lid
            movers.append((abs(pts[-1][1] - pts[-2][1]), title[:40],
                           pts[-1][1] - pts[-2][1]))
    movers.sort(reverse=True)
    lines.append("Biggest price moves (each listing's last two observations):")
    for _, title, dl in movers[:5]:
        lines.append(f"  {title}: {'+' if dl > 0 else ''}{dl}")

    if probes:
        counts = {}
        for v in probes.values():
            counts[v["status"]] = counts.get(v["status"], 0) + 1
        lines.append(f"Ghost probes (live=likely booked/blocked, delisted=removed): {counts}")

    try:
        entries = tr.load_changelog()[:5]
        if entries:
            lines.append("Recent changelog:")
            lines.extend(f"  {e}" for e in entries)
    except Exception:
        pass

    return "\n".join(lines), last


def call_zai(digest):
    """One chat completion via z.ai. Returns (text, None) or (None, error)."""
    key = os.environ.get("ZAI_API_KEY")
    if not key:
        return None, "skipped: no ZAI_API_KEY"
    from openai import OpenAI
    client = OpenAI(api_key=key, base_url=ZAI_BASE_URL, timeout=90)
    r = client.chat.completions.create(
        model=MODEL,
        temperature=0.2,
        max_tokens=900,
        messages=[{"role": "system", "content": SYSTEM_PROMPT},
                  {"role": "user", "content": digest}])
    return (r.choices[0].message.content or "").strip(), None


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    digest, data_date = build_digest()
    logger.info(f"digest built for {data_date} ({len(digest)} chars)")
    try:
        out, err = call_zai(digest)
    except Exception as e:  # never fatal to the pipeline
        out, err = None, f"{type(e).__name__}: {str(e)[:200]}"
    now = datetime.now()
    path = (PROJECT_ROOT / "reports" /
            f"ai_analysis_{now.strftime('%Y-%m-%d')}_{now.strftime('%H%M')}.txt")
    header = (f"AI anomaly analysis — run {now.strftime('%Y-%m-%d %H:%M')} "
              f"(data: {data_date}, model: {MODEL})\n" + "=" * 60 + "\n")
    if err:
        # write the outcome even on skip/error — the file is the heartbeat:
        # no new file per run day ⇒ the step or the workflow didn't run
        logger.warning(f"AI analysis {err}")
        path.write_text(header + f"SKIPPED/ERROR: {err}\n\n"
                        "No model output this run. Likely causes: ZAI_API_KEY secret\n"
                        "missing or misnamed, key rejected, or model name wrong\n"
                        "(override via the ZAI_MODEL workflow env).\n")
        logger.info(f"outcome written to {path.name}")
        return 0
    path.write_text(header + out + "\n")
    logger.info(f"AI analysis written to {path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
