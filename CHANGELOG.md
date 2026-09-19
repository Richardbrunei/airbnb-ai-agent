# Changelog

Methodology, configuration, and pipeline changes that affect how the stored
data should be read. Newest first. Rendered into the trend report footer.

- 2026-09-19 — Search radius widened 10 km → 20 km; dead top-level property_types list removed (it never reached Airbnb — scraper only forwards a single type). Stored comp-set sizes step up sharply from this date (~30–50 vs 6–14): a lens change, not a market shift. Read trend tables across this boundary with care.
- 2026-09-19 — Map pin labels now recognize returning competitors ("Back after a gap"). Display-only; no stored data changed.
- 2026-09-13 — Pipeline moved to GitHub Actions: two scrapes daily (8:17 AM + 12:17 PM CDT, results bot-committed to this repo). Data density roughly doubles from here; the WSL box became a read-only consumer. data/market.db and daily report .txt files became git-tracked from this date.
- 2026-09-11 — Trend report introduced: competitors-only display (listings ⨝ competitor_scores) with a ≥ 0.70 competitiveness cutoff — weak matches (0.59–0.67) excluded from report display. Discount-share counting corrected the same day (discount_pct > 0, not original_price presence; the daily reports were always correct).
- 2026-08-22 — Database persistence begins. Report files exist back to 2026-06-27, but queryable history starts here.
- 2026-06-27 — First daily market report generated.
