---
name: airbnb-market-monitor
description: Deploy, configure, and operate the Airbnb competitor market monitor (airbnb-ai-agent repo) — set up GitHub Actions scraping for any property, configure real or hypothetical anchors, sync data to a local machine, and read or regenerate the trend report and map. Use when asked to set up or check Airbnb market monitoring, change the tracked property, inspect competitor scores or price recommendations, or port the monitor to another machine or OpenClaw install.
---

# Airbnb Market Monitor

The monitor lives in an ordinary git repo; GitHub Actions is the sole
writer of data, every local clone is a read-only consumer. The repo's
README.md is the full reference — this skill is the operating procedure.

## 1. Locate or set up the repo

Default location in this workspace: `coding/airbnb-ai-agent`.
For a new user/machine: clone or fork
`github.com/Richardbrunei/airbnb-ai-agent` (see README "Porting to
another OpenClaw install"). Verify it exists and is current:
`git pull -q --ff-only origin main` succeeds.

## 2. Configure the tracked property

Edit `config/areas.json` → `search_areas[0]`:

- `property_profile`: lat/lng, bedrooms, price, property_type.
  Real property → omit `"hypothetical"` (report shows neutral anchor
  wording). Demo/analysis-only → set `"hypothetical": true` (amber
  disclaimers render everywhere — never present demo numbers without
  them).
- Optional `rating` / `is_guest_favorite` / `is_superhost` unlock the
  quality multiplier in price recommendations (otherwise ×1.00).
- Tune `radius_km`, `competitor_filters`, `max_competitor_distance_km`.

**Test before committing** (search + filter only, stores nothing):

```python
import asyncio
from market_agent.scraper import AirbnbScraper
print(len(asyncio.run(AirbnbScraper().search_competitors())), "competitors")
```

⚠️ **Never run `main.py`, `run_daily.sh`, or `run_if_missed.py` on the
production clone** — local DB writes break the sole-writer architecture.

## 3. Automation

`.github/workflows/daily-scrape.yml` scrapes 2×/day (8:17 AM + 12:17 PM
CDT), regenerates the trend report, and bot-commits results to `main`.
No secrets or API keys — the built-in GITHUB_TOKEN does everything.
On forks: Actions tab → enable "Daily Airbnb scrape".

Check health without credentials (public repos):

```bash
curl -s "https://api.github.com/repos/<owner>/<repo>/actions/runs?per_page=3"
```

All runs should be `completed/success`. A failed run = check its logs
in the Actions tab before touching anything local.

## 4. Keep local in sync

`git pull --ff-only origin main` (optional cron every 20 min; harmless
when the machine sleeps — it catches up awake). If ff-only fails,
something diverged: investigate, never merge blindly and never force-push
over bot commits.

## 5. Read the results

- `reports/market_trend_report.html` — self-contained: per-day trend
  market-direction verdict (best-fit trend + day-over-day), per-day
  trend table + sparklines, comp-set churn, price movers, recommendation
  history, scoring + pricing methodology, changelog, embedded map.
- `reports/market_trend_map.html` — price·score chips, anchor pin,
  former/returning competitor pins with full price histories.
- Quick numbers from SQLite (read-only, copy the DB out first if
  tooling blocks the state dir):
  `listings` (raw comps per day) ⨝ `competitor_scores` (scores);
  discounts = `discount_pct > 0` (NOT original_price presence).

Remember when interpreting: individual-listing absence is usually
availability churn (booked/hidden from search), not market exit —
median and discount-share are the trustworthy signals.

## 6. Change discipline

- Any change to scoring, filters, config, or cadence → add a dated
  entry to `CHANGELOG.md` (the report renders it; trend boundaries need
  the context).
- Changing the anchor property → reset `data/market.db` per README
  "Tracking Your Own Property" (stored scores are anchor-relative).
- Local analysis or report regeneration → scratch clone with venv, not
  the production clone.
