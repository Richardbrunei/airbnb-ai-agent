# Changelog

Methodology, configuration, and pipeline changes that affect how the stored
data should be read. Newest first. Rendered into the trend report footer.

- 2026-09-27 — AI analyst: every scrape gets an automated z.ai anomaly read committed as `reports/ai_analysis_<date>_<HHMM>.txt` (NOTHING_UNUSUAL + one-liner when calm; ANOMALY + <200-word analysis when the rubric trips — median ±8% DoD, comp-set ±30% cross-checked vs changelog, discount ±15 pts, rec ±5%, probe verdicts, ≥5 vanished/returned). Needs the ZAI_API_KEY repo secret; without it the step skips harmlessly.
- 2026-09-27 — Probe classification: HTTP 410 (Gone) now counts as delisted (was "error"). First runner-IP probe batch: 16 live (likely booked/blocked), 1 delisted-by-410, zero 403s.
- 2026-09-27 — Daily reports: each scrape now keeps its own file (`market_report_<date>_<HHMM>.txt`) — the afternoon run no longer overwrites the morning report. Trend report reads the latest run of each day for recommendations; older date-only files still parse.
- 2026-09-26 — Ghost probes: vanished competitors get a polite daily URL probe (max 10/run, one per listing per day, ever-displayed ≥0.70 competitors only). Map/report now split "likely booked — page still live" (amber) from "removed/delisted" (red); grey = unprobed. Absence alone stays ambiguous — Airbnb search hides calendar-closed listings. First verdicts appear from the next Actions run.
- 2026-09-20 — Report: market-direction verdict added (best-fit line over daily medians + day-over-day delta + discounting/comp-set chips), per-day Δ median column, direction card, and a trend line on the map stats. Direction is a least-squares fit over the whole window — read sharp one-day steps against this changelog, not as market moves.
- 2026-09-19 — Search radius widened 10 km → 20 km; dead top-level property_types list removed (it never reached Airbnb — scraper only forwards a single type). Stored comp-set sizes step up sharply from this date (~30–50 vs 6–14): a lens change, not a market shift. Read trend tables across this boundary with care.
- 2026-09-19 — Map pin labels now recognize returning competitors ("Back after a gap"). Display-only; no stored data changed.
- 2026-09-13 — Pipeline moved to GitHub Actions: two scrapes daily (8:17 AM + 12:17 PM CDT, results bot-committed to this repo). Data density roughly doubles from here; the WSL box became a read-only consumer. data/market.db and daily report .txt files became git-tracked from this date.
- 2026-09-11 — Trend report introduced: competitors-only display (listings ⨝ competitor_scores) with a ≥ 0.70 competitiveness cutoff — weak matches (0.59–0.67) excluded from report display. Discount-share counting corrected the same day (discount_pct > 0, not original_price presence; the daily reports were always correct).
- 2026-08-22 — Database persistence begins. Report files exist back to 2026-06-27, but queryable history starts here.
- 2026-06-27 — First daily market report generated.
