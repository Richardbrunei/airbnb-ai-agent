# Setup prompt — local, on-demand use (no scheduled reports)

For someone who wants the monitor on their own machine without the
automation: they trigger scrapes and reports manually whenever they want.
No GitHub Actions, no cron, no repo secrets, nothing commits anywhere.
Hand everything below the line to an AI agent on that machine (or follow
it yourself).

---

You are setting up **airbnb-ai-agent** on this machine for **on-demand,
local-only use**: the user runs scrapes and reports by hand. There is no
schedule, no automation, and no git pushing in this mode.

## 0. Prerequisites

- Linux, macOS, or Windows-under-WSL with python3 (3.10+), and git or a
  browser to fetch the code.
- The code — either way works:
  - **Download ZIP:** on GitHub open `Richardbrunei/airbnb-ai-agent` →
    green **Code** button → **Download ZIP** → unzip.
  - **Or clone:** `git clone https://github.com/Richbrunei/airbnb-ai-agent.git`
- Optional: a z.ai API key with **coding-plan** access (the monitor calls
  `https://api.z.ai/api/coding/paas/v4`, model `glm-5.3`). Only the AI
  anomaly analysis needs it — without a key, everything else works and
  the analysis file simply says SKIPPED.

## 1. Install

```bash
cd airbnb-ai-agent
python3 -m venv venv                # bare venv: bootstrap pip first
./venv/bin/python3 -m ensurepip
./venv/bin/python3 -m pip install -r requirements.txt
```

## 2. Configure your property (or keep the demo anchors)

Out of the box the config tracks THREE IMAGINARY Dallas homes — a demo
setup; disclose that whenever quoting numbers. To watch your own property
instead: edit `config/areas.json` (`search_areas`; entry 1 is the primary
anchor) — set `location`, `property_profile` (lat/lng/bedrooms/price),
filters, `radius_km`. **Replacing the demo anchors requires deleting the
inherited demo database first**, or your scores mix with months of demo
history:

```bash
rm data/market.db
```

Details in "Tracking Your Own Property" (README.md). Keeping the demo
anchors to evaluate the tool is fine — skip this step.

## 3. Run it (whenever you want a report)

```bash
# scrape + score + write today's report:
./venv/bin/python3 main.py

# same, with the AI anomaly analysis:
ZAI_API_KEY=your-key ./venv/bin/python3 main.py

# regenerate the interactive map + trend report:
./venv/bin/python3 reports/trend_report.py
```

- Text reports land in `reports/text_reports/<date>/` (`market_report_*.txt`
  + `ai_analysis_*.txt`); the map is `reports/market_trend_map.html` and
  the trend report `reports/market_trend_report.html`.
- Every run appends to the local `data/market.db` — charts and trends
  build up as you run it more often. USER_MANUAL.md explains the output.

## 4. Notes for this mode

- Nothing runs on a schedule and nothing leaves the machine: the local
  `data/market.db` is the only memory — back it up if the history matters.
- Be a polite scraper: one run of `main.py` is one scrape pass; a couple
  of runs a day is plenty. Airbnb rate-limits aggressive scrapers.
- If you later want the full automated pipeline (twice-daily runs on
  GitHub Actions, auto-committed reports), switch to the fork setup:
  README Setup or docs/agent-setup-prompt.md.

First task: install, configure (or keep the demo anchors), run `main.py`
once, and summarize the resulting report — disclosing that the anchors
are imaginary if they are still the defaults.
