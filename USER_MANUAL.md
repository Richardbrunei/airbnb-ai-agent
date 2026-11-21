# Airbnb Market Monitor — User Manual

Everything you need to read the monitor's output and run the daily check.
Setup instructions live in README.md; for installing on a new device see
docs/agent-setup-prompt.md.

> **Default configuration note:** this repo tracks two **hypothetical** 4BR
> homes — UT Dallas House and South Dallas House, both "listed" at $250, on
> opposite sides of Dallas. They are placeholders. Every number in the
> artifacts is illustrative until you configure a real anchor (§9), and any
> quoted figures should carry the imaginary-anchors disclosure.

## 1. What the system does

Twice a day on a fixed schedule (the `cron` lines in
`.github/workflows/daily-scrape.yml`; currently 7:17 and 11:17 AM US
Central in winter — the workflow stores UTC, so local times shift with
daylight saving), GitHub Actions:

1. **Scrapes** Airbnb listings around each anchor property.
2. **Scores** each listing's similarity to the anchor; strong matches form
   the anchor's **comp set** (similarity at least 0.70).
3. **Recommends a price** from the anchor's 20 closest comps.
4. **Writes** a text market report, an AI anomaly analysis, an interactive
   map, and a trend report (§2).
5. **Commits everything to git.** The local copy is a read-only mirror a
   cron job keeps current (pull every 20 minutes).

You never run the pipeline by hand; local machines only consume its
output. The discipline matters: data written locally would desync the
git mirror.

## 2. What you receive, and where

| Artifact | Location | What it is |
|---|---|---|
| Daily market report | `reports/text_reports/<date>/market_report_*.txt` | Stats + price recommendation, one per run |
| AI analysis | `reports/text_reports/<date>/ai_analysis_*.txt` | Anomaly check by the AI analyst |
| Interactive map | `reports/market_trend_map.html` | Every comp as a pin; both anchors |
| Trend report | `reports/market_trend_report.html` | Long-run tables, charts, direction |
| Database | `data/market.db` | Raw history — read-only; let the tools query it |

Each day gets its own folder holding that day's report + analysis. Day
folders older than **31 days** are pruned automatically; full history
remains in git.

## 3. Reading the daily market report

Open the newest `market_report_*.txt`. The example below is real output
from 2026-11-21 (imaginary anchors).

**Market Overview** — the day's scan pool: count, median/mean, range,
rating:

```text
Market Overview (33 listings)
  Median Price: $435    Mean Price: $430
  Price Range:  $205 - $579    Avg Rating: 4.8 stars
```

**Discount Insights** — how many listings discount and how deep.
"Median (Original) $442 to $354 (effective)" means discounted listings
collect about $88 under asking. Broad discounting = soft demand.

**Pricing Recommendation** — the heart. One block per anchor:

```text
UT Dallas House
  Current $250 -> Suggested $470 (+88%)
  Confidence: 55%
    - Comp set: 20 closest listings, median effective $470 (IQR $360-$542)
    - Only 25% of comps discounting -> stable demand
South Dallas House
  Current $250 -> Suggested $490 (+96%)
  Confidence: 51%
```

- **Current to Suggested** — what the anchor is "listed" at vs what its
  comps support. With the default $250 imaginary anchors, huge +% is
  expected demo output.
- **Confidence** — tightness of the comp evidence. Below about 60% the
  comp set is noisy; do not chase the number.
- **Bullets** — the reasoning: comp-set size and spread, quality
  adjustment, discount climate.

**Price by Bedroom Count / Price by Neighborhood** — sanity tables to
check the recommendation against obvious segments (4BR $525 vs a $470
rec means the rec is pulled down by 3BRs).

## 4. Reading the AI analysis

`ai_analysis_*.txt` is a short verdict from an AI analyst with read-only
database tools.

- **NOTHING_UNUSUAL** plus a one-liner per anchor (date, comp count,
  median, discount share, five-word state) = calm day. Good.
- **ANOMALY** = something moved: comp-set churn, a repricing wave,
  delistings. The text says what changed and what it means for the
  anchor's price. The analyst separates **repricing** (same homes, new
  prices) from **composition** (different homes) — the most common trap
  when reading medians.
- The header records the model and the tool-call count — how many DB
  queries it ran to verify.
- **SKIPPED** means no working API key that run (§10).

## 5. Using the map

Open `reports/market_trend_map.html` in a browser.

- **Colored pills = live competitors**, by nightly price: green up to
  $300, blue $301-400, orange $401-500, red over $500.
- **White border = primary anchor's comps; purple border = second
  anchor's** (default config: north vs south Dallas).
- **Click a pin** for title, match score, and full observed price
  history.
- **Dashed pins = ghosts** (former competitors): amber = likely just
  booked (page still live), red = removed/delisted, grey = not yet
  probed. Absence alone is ambiguous — Airbnb hides calendar-closed
  listings — which is why ghosts get probed.
- **House pins = the anchors themselves** — click for live comp-set
  stats (imaginary under the default config).
- **Stats card (top right)**: one section per anchor — active count,
  median, trend arrow, suggested price.

## 6. Using the trend report

`reports/market_trend_report.html` is the long view: a per-day table of
comp-set size and median (with day-over-day delta), suggested-price
history, ghost/delisting tallies (a **cumulative ledger**, not today's
count), a market-direction card (least-squares fit over the window), and
a second-anchor card for the newer anchor's history. Read it weekly for
drift; when you see a sharp one-day step, check CHANGELOG.md before
calling it a market move (lens changes live there).

## 7. Your daily check (about 2 minutes)

1. Confirm sync (`git pull`, or let the 20-minute cron do it).
2. Today's folder exists in `reports/text_reports/` — two bot commits
   per day is the heartbeat.
3. Open the market report; glance at recommendation + confidence.
4. Open the AI analysis; if ANOMALY, read why.

Everything else is automatic.

## 8. Asking questions about your market

If an AI assistant has access to this repo (the intended setup), ask in
plain language: "Why did the median jump Tuesday?" or "Which anchor's
comp set discounts more?" or "Show price history for listings that left
the set this week." The repo ships read-only tools (`day_diff`,
`comp_set`, each taking an optional anchor parameter) that answer from
the same view the reports use — including the repricing-vs-composition
split. If you query the DB yourself: open it read-only and always filter
by the `anchor` column.

## 9. Changing configuration

- **Your own property**: edit `config/areas.json` (search_areas). Entry 1
  is the primary anchor. **Replacing an anchor requires a DB reset**
  (scores are anchor-relative) — see "Tracking Your Own Property" in
  README.md. Adding an anchor needs no reset; its history starts that day.
- **Schedule**: the `cron` lines in `.github/workflows/daily-scrape.yml`
  (UTC times).
- **Filters / scoring**: neighborhoods, price band, bedroom range, and
  match weights live in `areas.json` and
  `market_agent/competitor_scorer.py`. Any change that affects how stored
  data reads belongs in CHANGELOG.md with a date.
- **Testing a change end-to-end**: bump the `# rev <date>` comment at the
  top of `daily-scrape.yml` and push — that file's push trigger runs the
  whole pipeline immediately.

## 10. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| No folder for today | Scheduled run failed (often Airbnb blocking the runner IP) | Read the Actions log; transient blocks self-heal next run |
| Analysis says SKIPPED / no ZAI_API_KEY | Secret missing or wrong | Repo Settings > Secrets > Actions > set ZAI_API_KEY |
| git pull refuses (local changes) | Something wrote to the mirror (should not happen) | git status, discard tracked-file changes, re-pull |
| Push rejected | Bot committed between fetch and push | git fetch, rebase onto origin/main, push again |
| Map/report stale | Mirror has not synced | git pull; check the cron log |
| Missing /tmp/airbnb-pull.log | Machine rebooted (log is per-boot) | Not an error; check git log freshness instead |
| Old reports gone | 31-day retention | By design; recover from git history |
| pytest failures | 8 pre-existing (2 scorer drift, 6 async) | Not regressions; the live suite is tests/test_two_anchors.py |

**Golden rule:** the Actions bot is the only data writer. Local pulls;
it never pushes data, never scrapes, never edits `data/market.db`.

## 11. Glossary

- **Anchor** — reference property everything is scored against (default: two imaginary ones).
- **Comp set** — listings scoring at least 0.70 similarity to an anchor that day.
- **Ghost** — vanished competitor under polite daily re-probing.
- **Effective price** — nightly price after discounts.
- **Suggested price** — median effective price of the anchor's 20 closest comps.
- **Same-set median** — median over homes present both days; isolates repricing from churn.

## 12. Where to learn more

- README.md — technical setup, configuration reference, automation
- CHANGELOG.md — dated record of methodology/config changes
- docs/agent-setup-prompt.md — paste-ready prompt for a new device
- skill/SKILL.md — operating notes for AI assistants
