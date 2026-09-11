#!/usr/bin/env python3
"""
Multi-day market trend report + price-history map — COMPETITORS ONLY.

Data source: data/market.db. The scraper applies the competitor filters in
config/areas.json (3–5 BR houses/townhomes, $150–600, ≤20 km from the
property) BEFORE storing, so the `listings` table holds only competitors.
This script additionally cross-checks every row against `competitor_scores`
for the same date and drops anything unscored, so non-competitor listings
can never appear even if storage changes. No context pins, no "Our
Property" pin — competitors only.

Produces (in reports/):
  1. market_trend_map.html    — Leaflet map of the latest day's competitor
     set (price-coded chips) plus dashed grey pins for FORMER competitors
     that dropped out. Popups show each competitor's full price history.
  2. market_trend_report.html — per-day trend table with sparklines,
     comp-set churn (new/dropped competitors), price movers, recommendation
     history (parsed from daily report .txt files), and the map embedded
     via iframe.

Re-runnable: regenerates both files from whatever data exists. Safe to run
after every daily pipeline; the report always reflects the full stored
history.

Usage:
    venv/bin/python3 reports/trend_report.py
"""

import json
import re
import sqlite3
import statistics
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "market.db"
REPORTS_DIR = PROJECT_ROOT / "reports"
MAP_OUT = REPORTS_DIR / "market_trend_map.html"
REPORT_OUT = REPORTS_DIR / "market_trend_report.html"

TIER_COLORS = {  # price chip colors, legend in map
    "low": "#2e7d32",      # <= 300
    "mid": "#1565c0",      # 301-400
    "high": "#ef6c00",     # 401-500
    "top": "#c62828",      # > 500
    "ghost": "#757575",
}

# Minimum competitiveness (total_score in competitor_scores) to appear in
# the report. Observed distribution: true comps cluster 0.74-0.92; low
# scorers (0.59-0.67) are weak matches and are ignored. Tune here.
MIN_TOTAL_SCORE = 0.70


def fmt_d(v):
    return f"${v:,.0f}" if v is not None else "—"


def tier(price):
    if price <= 300:
        return "low"
    if price <= 400:
        return "mid"
    if price <= 500:
        return "high"
    return "top"


def spark(values, w=150, h=34, color="#1565c0"):
    """Inline SVG sparkline. None values break the line."""
    pts = [(i, v) for i, v in enumerate(values) if v is not None]
    if len(pts) < 2:
        return '<span style="color:#999">—</span>'
    vmax, vmin = max(p[1] for p in pts), min(p[1] for p in pts)
    rng = (vmax - vmin) or 1

    def X(i):
        return 4 + i * (w - 8) / (len(values) - 1)

    def Y(v):
        return h - 6 - (v - vmin) * (h - 12) / rng

    d = "M" + " ".join(f"L{X(i):.1f},{Y(v):.1f}"[1:] for i, v in pts)
    last = pts[-1]
    return (
        f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
        f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2"/>'
        f'<circle cx="{X(last[0]):.1f}" cy="{Y(last[1]):.1f}" r="3" fill="{color}"/>'
        f"</svg>"
    )


def load_data():
    """Load strong competitors only: rows present in BOTH listings and
    competitor_scores for the same date AND with total_score >=
    MIN_TOTAL_SCORE (weak matches are ignored per Richard's call)."""
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    days = [r[0] for r in db.execute(
        "SELECT DISTINCT scrape_date FROM listings ORDER BY scrape_date")]
    day_stats = []
    for d in days:
        rows = db.execute(
            "SELECT l.* FROM listings l JOIN competitor_scores c "
            "ON c.scrape_date = l.scrape_date AND c.listing_id = l.listing_id "
            "WHERE l.scrape_date=? AND c.total_score >= ?", (d, MIN_TOTAL_SCORE)).fetchall()
        prices = [r["price"] for r in rows if r["price"] is not None]
        # discounted = active price cut (discount_pct > 0). original_price is
        # populated on EVERY row (equals price when undiscounted) — never use
        # its presence as the discount signal.
        discounted = [r for r in rows if r["discount_pct"]]
        day_stats.append({
            "date": d,
            "count": len(rows),
            "median": statistics.median(prices) if prices else None,
            "mean": statistics.mean(prices) if prices else None,
            "min": min(prices) if prices else None,
            "max": max(prices) if prices else None,
            "disc_count": len(discounted),
            "disc_pct": 100 * len(discounted) / len(rows) if rows else 0,
            "avg_disc": (statistics.mean([r["discount_pct"] for r in discounted
                                          if r["discount_pct"]]) if discounted else 0),
        })

    hist = defaultdict(dict)   # listing_id -> {date: row}
    meta = {}
    for d in days:
        rows = db.execute(
            "SELECT l.*, c.total_score AS comp_score FROM listings l JOIN competitor_scores c "
            "ON c.scrape_date = l.scrape_date AND c.listing_id = l.listing_id "
            "WHERE l.scrape_date=? AND c.total_score >= ?", (d, MIN_TOTAL_SCORE)).fetchall()
        for r in rows:
            hist[r["listing_id"]][d] = r
            m = meta.setdefault(r["listing_id"], {
                "title": r["title"], "url": r["url"], "bedrooms": r["bedrooms"],
                "neighborhood": r["neighborhood"], "lat": r["lat"], "lng": r["lng"],
                "rating": r["rating"],
            })
            if r["lat"] is not None:  # keep freshest coords
                m.update(lat=r["lat"], lng=r["lng"])
    db.close()
    return days, day_stats, hist, meta


def parse_recs(days):
    """Pull recommendation history from daily report .txt files."""
    recs = {}
    for d in days:
        f = REPORTS_DIR / f"market_report_{d}.txt"
        if not f.exists():
            continue
        txt = f.read_text(errors="replace")
        m = re.search(r"Current \$\d+ → Suggested \$(\d+)", txt)
        c = re.search(r"Confidence:\s*(\d+)%", txt)
        if m:
            recs[d] = {"suggested": int(m.group(1)),
                       "conf": int(c.group(1)) if c else None}
    return recs


def build_map(days, hist, meta, day_stats):
    last = days[-1]
    feats = []
    for lid, h in hist.items():
        m = meta[lid]
        if m["lat"] is None:
            continue
        in_last = last in h
        seen_days = sorted(h.keys())
        first_d, last_seen = seen_days[0], seen_days[-1]
        series = " · ".join(
            f"{d[5:]} <b>{fmt_d(h[d]['price'])}</b>" for d in seen_days)
        cur = h[last_seen]["price"]
        score = h[last_seen]["comp_score"]
        if in_last:
            color = TIER_COLORS[tier(cur)]
            if first_d == days[0] and len(seen_days) >= len(days) - 1:
                status, sc = "Stable competitor", "#2e7d32"
            elif first_d != days[0]:
                status, sc = "New competitor since " + first_d[5:], "#1565c0"
            else:
                status, sc = "Active competitor", "#1565c0"
            icon_html = (f'<div style="transform:translate(-50%,-100%);white-space:nowrap;'
                         f'font:700 11px -apple-system,sans-serif;color:#fff;background:{color};'
                         f'padding:2px 7px;border-radius:12px;border:2px solid #fff;'
                         f'box-shadow:0 1px 4px rgba(0,0,0,.4)">{fmt_d(cur)}'
                         f'<span style="opacity:.85;font-weight:600"> · {score:.2f}</span></div>')
        else:
            color = TIER_COLORS["ghost"]
            status, sc = "Former competitor — last seen " + last_seen[5:], "#757575"
            icon_html = (f'<div style="transform:translate(-50%,-100%);width:12px;height:12px;'
                         f'border-radius:50%;background:transparent;border:2px dashed {color};'
                         f'box-shadow:0 1px 3px rgba(0,0,0,.3)"></div>')
        popup = f"""
        <div style="font-family:-apple-system,sans-serif;min-width:230px">
          <div style="font-weight:700;margin-bottom:2px">{m['title'] or 'Listing'}</div>
          <div style="color:#666;font-size:12px;margin-bottom:6px">
            {str(m['bedrooms'] or '?')} BR · {m['neighborhood'] or '—'}
            {(' · ★ ' + str(m['rating'])) if m['rating'] else ''}</div>
          <div style="font-size:12px;margin:4px 0">
            <span style="background:{sc}22;color:{sc};font-weight:700;
                  padding:1px 8px;border-radius:10px;font-size:11px">{status}</span>
            <span style="background:#eef2f7;color:#333;font-weight:700;
                  padding:1px 8px;border-radius:10px;font-size:11px">score {score:.2f}</span></div>
          <div style="border-top:1px solid #eee;margin-top:6px;padding-top:6px;
               font-size:12px;line-height:1.7">{series}</div>
          {f'<a href="{m["url"]}" target="_blank" style="font-size:12px">View listing ↗</a>' if m['url'] else ''}
        </div>"""
        feats.append({"lat": m["lat"], "lng": m["lng"], "icon": icon_html,
                      "popup": popup, "active": in_last})

    center = [statistics.mean(f["lat"] for f in feats),
              statistics.mean(f["lng"] for f in feats)]

    # Anchor property from config — the imaginary home everything is scored against
    try:
        cfg = json.loads((PROJECT_ROOT / "config" / "areas.json").read_text())
        prof = cfg["search_areas"][0]["property_profile"]
    except Exception:
        prof = {"lat": 32.9949, "lng": -96.7474, "bedrooms": 4, "price": 250}
    anchor = {
        "lat": prof["lat"], "lng": prof["lng"],
        "icon": (f'<div style="transform:translate(-50%,-100%);white-space:nowrap;'
                 f'font:700 11px -apple-system,sans-serif;color:#fff;background:#1a237e;'
                 f'padding:3px 9px;border-radius:12px;border:2px solid #fff;'
                 f'box-shadow:0 2px 6px rgba(0,0,0,.5)">🏠 {fmt_d(prof["price"])} anchor</div>'),
        "popup": (f'<div style="font-family:-apple-system,sans-serif;min-width:210px">'
                  f'<div style="font-weight:700;margin-bottom:2px">🏠 Imaginary anchor home</div>'
                  f'<div style="color:#666;font-size:12px;margin-bottom:6px">'
                  f'{prof["bedrooms"]} BR · UT Dallas campus · listed {fmt_d(prof["price"])}</div>'
                  f'<div style="font-size:12px;line-height:1.6;border-top:1px solid #eee;padding-top:6px">'
                  f'<b>This property does not exist.</b> It is the placeholder profile all competitor '
                  f'scores and price recommendations are measured against.</div>'
                  f'<div style="font-size:11px;color:#999;margin-top:4px">{prof["lat"]}, {prof["lng"]}</div></div>'),
    }

    stats_card = f"""
      <div style="font-weight:700;margin-bottom:4px">{last} · live comp set</div>
      <div style="font-size:12px;line-height:1.8">
        <div><b style="font-size:18px">{day_stats[-1]['count']}</b> active · median <b>{fmt_d(day_stats[-1]['median'])}</b></div>
        <div>{sum(1 for f in feats if not f['active'])} former competitors (dropped)</div>
        <div style="margin-top:4px;color:#7a5c00">⚠ anchored to an imaginary
        <span style="white-space:nowrap">4BR @ UT Dallas</span></div>
      </div>"""

    html = MAP_TEMPLATE.replace("__CENTER__", json.dumps(center))
    html = html.replace("__DATA__", json.dumps(feats))
    html = html.replace("__ANCHOR__", json.dumps(anchor))
    html = html.replace("__STATS__", stats_card)
    html = html.replace("__GENERATED__", str(date.today()))
    MAP_OUT.write_text(html)


MAP_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Competitor Trend Map — Richardson TX comp set</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; }
  #map { width:100vw; height:100vh; }
  .card { position:absolute; top:12px; right:12px; z-index:1000; background:#fff;
          border-radius:12px; box-shadow:0 2px 12px rgba(0,0,0,.18); padding:12px 14px;
          max-width:250px; }
  .legend { position:absolute; bottom:22px; left:12px; z-index:1000; background:#fff;
          border-radius:12px; box-shadow:0 2px 12px rgba(0,0,0,.18); padding:10px 14px;
          font-size:12px; line-height:1.9; }
  .sw { display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:6px; }
  .leaflet-popup-content { font-family:-appleclaw,sans-serif; font-family:-apple-system,sans-serif; }
</style>
</head>
<body>
<div id="map"></div>
<div class="card">__STATS__
  <div style="font-size:10px;color:#999;margin-top:6px">competitors only · generated __GENERATED__</div>
</div>
<div class="legend">
  <span class="sw" style="background:#2e7d32"></span>≤ $300<br>
  <span class="sw" style="background:#1565c0"></span>$301–400<br>
  <span class="sw" style="background:#ef6c00"></span>$401–500<br>
  <span class="sw" style="background:#c62828"></span>&gt; $500<br>
  <span class="sw" style="background:transparent;border:2px dashed #757575"></span>former competitor<br>
  <span style="margin-right:6px">🏠</span><b>$250 anchor</b> (imaginary)
  <div style="border-top:1px solid #eee;margin-top:6px;padding-top:6px;color:#777">
    score = .35·location + .30·bedrooms +<br>.30·type + .05·price (similarity to anchor)</div>
</div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const center = __CENTER__;
const feats = __DATA__;
const anchor = __ANCHOR__;
const map = L.map('map').setView(center, 12);
L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}', {
  maxZoom: 19,
  attribution: 'Tiles &copy; Esri &mdash; Source: Esri, DeLorme, NAVTEQ, USGS, Intermap, iPC, NRCAN, Esri Japan, METI, Esri China (Hong Kong), Esri (Thailand), TomTom'
}).addTo(map);
const active = feats.filter(f => f.active), ghosts = feats.filter(f => !f.active);
for (const f of active)
  L.marker([f.lat, f.lng], {icon: L.divIcon({html: f.icon, className: '', iconSize: null})})
   .addTo(map).bindPopup(f.popup);
for (const f of ghosts)
  L.marker([f.lat, f.lng], {icon: L.divIcon({html: f.icon, className: '', iconSize: null})})
   .addTo(map).bindPopup(f.popup);
L.marker([anchor.lat, anchor.lng], {icon: L.divIcon({html: anchor.icon, className: '', iconSize: null}), zIndexOffset: 1000})
 .addTo(map).bindPopup(anchor.popup);
if (active.length) map.fitBounds(active.concat([anchor]).map(f => [f.lat, f.lng]), {padding:[60,60]});
</script>
</body>
</html>
"""


def build_report(days, day_stats, hist, meta, recs):
    last = days[-1]
    n_days = len(days)

    prev = days[-2] if n_days >= 2 else None
    ids = {d: {lid for lid in hist if d in hist[lid]} for d in days}
    new_now = sorted(ids[last] - ids[prev], key=lambda l: -(hist[l][last]["price"] or 0)) if prev else []
    gone_now = sorted(ids[prev] - ids[last], key=lambda l: -(hist[l][prev]["price"] or 0)) if prev else []

    def listing_row(lid, d_ref):
        m = meta[lid]
        p = hist[lid][d_ref]["price"]
        return (f'<tr><td><a href="{m["url"]}" target="_blank">{m["title"] or lid}</a></td>'
                f'<td>{str(m["bedrooms"] or "?")} BR</td>'
                f'<td style="text-align:right"><b>{fmt_d(p)}</b></td></tr>')

    movers = []
    for lid, h in hist.items():
        prices = [(d, r["price"]) for d, r in sorted(h.items()) if r["price"]]
        if len(prices) >= 2 and len({p for _, p in prices}) > 1:
            movers.append((lid, prices))
    movers.sort(key=lambda x: -(max(p for _, p in x[1]) - min(p for _, p in x[1])))

    trend_rows = ""
    for s in day_stats:
        r = recs.get(s["date"], {})
        trend_rows += (
            f'<tr><td><b>{s["date"]}</b></td>'
            f'<td style="text-align:right">{s["count"]}</td>'
            f'<td style="text-align:right"><b>{fmt_d(s["median"])}</b></td>'
            f'<td style="text-align:right">{fmt_d(s["min"])}–{fmt_d(s["max"])}</td>'
            f'<td style="text-align:right">{s["disc_count"]}/{s["count"]} ({s["disc_pct"]:.0f}%)</td>'
            f'<td style="text-align:right">{fmt_d(r.get("suggested"))}'
            + (f' <span style="color:#999;font-size:11px">@{r["conf"]}%</span>' if r.get("conf") else "")
            + '</td></tr>')

    med_spark = spark([s["median"] for s in day_stats], color="#1565c0")
    cnt_spark = spark([s["count"] for s in day_stats], color="#6a1b9a")
    dsc_spark = spark([round(s["disc_pct"]) for s in day_stats], color="#ef6c00")

    movers_html = ""
    for lid, prices in movers[:8]:
        series = " → ".join(f'{d[5:]} <b>{fmt_d(p)}</b>' for d, p in prices)
        delta = prices[-1][1] - prices[0][1]
        col = "#2e7d32" if delta > 0 else "#c62828"
        movers_html += (
            f'<div style="display:flex;justify-content:space-between;gap:12px;'
            f'padding:7px 0;border-bottom:1px solid #f0f0f0;font-size:13px">'
            f'<div><b>{meta[lid]["title"] or lid}</b>'
            f'<div style="color:#666;font-size:12px">{series}</div></div>'
            f'<div style="color:{col};font-weight:700;white-space:nowrap">'
            f'{"+" if delta>0 else "−"}{fmt_d(abs(delta))} vs first</div></div>')

    new_html = "".join(listing_row(l, last) for l in new_now) or "<tr><td colspan=3 style='color:#999'>none</td></tr>"
    gone_html = "".join(listing_row(l, prev) for l in gone_now) or "<tr><td colspan=3 style='color:#999'>none</td></tr>"

    rec_rows = "".join(
        f'<tr><td>{d}</td><td style="text-align:right"><b>${r["suggested"]}</b></td>'
        f'<td style="text-align:right">{r["conf"] if r["conf"] else "—"}%</td></tr>'
        for d, r in recs.items())

    first = days[0]
    html = REPORT_TEMPLATE
    html = (html.replace("__GENERATED__", str(date.today()))
                .replace("__RANGE__", f"{first} → {last}")
                .replace("__NDAYS__", str(n_days))
                .replace("__MED__", fmt_d(day_stats[-1]["median"]))
                .replace("__CNT__", str(day_stats[-1]["count"]))
                .replace("__DISC__", f"{day_stats[-1]['disc_pct']:.0f}%")
                .replace("__MED_SPARK__", med_spark)
                .replace("__CNT_SPARK__", cnt_spark)
                .replace("__DSC_SPARK__", dsc_spark)
                .replace("__TREND_ROWS__", trend_rows)
                .replace("__MOVERS__", movers_html or "<p style='color:#999'>No price changes detected.</p>")
                .replace("__NEW_ROWS__", new_html)
                .replace("__GONE_ROWS__", gone_html)
                .replace("__REC_ROWS__", rec_rows)
                .replace("__PREV__", prev or "")
                .replace("__LAST__", last)
                .replace("__MINSCORE__", f"{MIN_TOTAL_SCORE:.2f}"))
    REPORT_OUT.write_text(html)


REPORT_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Airbnb Competitor Trend Report — Richardson TX</title>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
         background:#f6f7f9; color:#222; padding:32px 16px; }
  .wrap { max-width:860px; margin:0 auto; }
  h1 { font-size:24px; margin-bottom:4px; }
  .sub { color:#777; font-size:13px; margin-bottom:24px; }
  h2 { font-size:15px; text-transform:uppercase; letter-spacing:.06em;
       color:#555; margin:28px 0 10px; }
  .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:12px; }
  .card { background:#fff; border-radius:12px; padding:16px;
          box-shadow:0 1px 4px rgba(0,0,0,.07); }
  .card .label { font-size:11px; color:#888; text-transform:uppercase;
                 letter-spacing:.05em; margin-bottom:6px; }
  .card .big { font-size:26px; font-weight:800; }
  .card .small { font-size:12px; color:#666; margin-top:2px; }
  table { width:100%; border-collapse:collapse; background:#fff; border-radius:12px;
          overflow:hidden; box-shadow:0 1px 4px rgba(0,0,0,.07); font-size:13px; }
  th { text-align:left; font-size:11px; text-transform:uppercase; letter-spacing:.05em;
       color:#888; background:#fafafa; padding:10px 12px; }
  td { padding:9px 12px; border-top:1px solid #f0f0f0; }
  tr:last-child td { border-bottom:none; }
  a { color:#1565c0; text-decoration:none; }
  a:hover { text-decoration:underline; }
  .panel { background:#fff; border-radius:12px; padding:16px 18px;
           box-shadow:0 1px 4px rgba(0,0,0,.07); }
  iframe { width:100%; height:600px; border:1px solid #e4e4e4; border-radius:12px;
           background:#fff; }
  .note { font-size:12px; color:#999; margin-top:8px; }
</style>
</head>
<body>
<div class="wrap">
  <h1>📊 Competitor Trend Report</h1>
  <div class="sub">Richardson TX comp set · __RANGE__ (__NDAYS__ days of data) · generated __GENERATED__</div>
  <div style="background:#fff8e1;border:1px solid #ffe082;border-radius:10px;
       padding:10px 14px;font-size:13px;color:#7a5c00;margin-bottom:20px">
    <b>⚠️ Hypothetical anchor:</b> all scoring, comp-set selection and price recommendations
    are based on an <b>imaginary 4BR home at UT Dallas</b> (32.9949, -96.7474, listed at $250) —
    a placeholder profile, not a real property. Treat every number as illustrative.</div>

  <h2>How competitors are scored</h2>
  <div class="panel" style="font-size:13px">
    Every competitor gets a <b>similarity score (0–1)</b> against the imaginary anchor —
    a weighted mix of four components (weights sum to 1.0):
    <table style="box-shadow:none;border-radius:8px;margin-top:8px">
      <tr><th>Component</th><th style="text-align:right">Weight</th><th>Rule</th></tr>
      <tr><td>📍 Location</td><td style="text-align:right"><b>35%</b></td>
          <td>Haversine distance from the anchor: 0 km = 1.0, falling linearly to 0.0 at 20 km</td></tr>
      <tr><td>🛏 Bedrooms</td><td style="text-align:right"><b>30%</b></td>
          <td>Exact 4BR match = 1.0; −0.25 per bedroom of difference</td></tr>
      <tr><td>🏠 Property type</td><td style="text-align:right"><b>30%</b></td>
          <td>Exact match = 1.0; same broad category (house / townhouse / cabin / …) = 0.7; different category = 0</td></tr>
      <tr><td>💰 Price</td><td style="text-align:right"><b>5%</b></td>
          <td>Log-ratio to the anchor's $250: within ±20% → &gt;0.8; 2× away → ≈0.25</td></tr>
    </table>
    <div class="note" style="margin-top:8px">This report shows only competitors scoring ≥ __MINSCORE__ — weak matches are excluded.
      Scoring lives in <code>market_agent/competitor_scorer.py</code>.</div>
  </div>

  <div class="cards">
    <div class="card"><div class="label">Days of data</div>
      <div class="big">__NDAYS__</div><div class="small">__RANGE__</div></div>
    <div class="card"><div class="label">Median price (__LAST__)</div>
      <div class="big">__MED__</div><div class="small">latest snapshot</div></div>
    <div class="card"><div class="label">Active competitors</div>
      <div class="big">__CNT__</div><div class="small">in current comp set</div></div>
    <div class="card"><div class="label">Discounting</div>
      <div class="big">__DISC__</div><div class="small">of current competitors</div></div>
  </div>

  <div class="cards" style="margin-top:12px">
    <div class="card"><div class="label">Median trend</div>__MED_SPARK__</div>
    <div class="card"><div class="label">Comp-set size</div>__CNT_SPARK__</div>
    <div class="card"><div class="label">% discounting</div>__DSC_SPARK__</div>
  </div>

  <h2>Per-day summary</h2>
  <table>
    <tr><th>Date</th><th style="text-align:right">Competitors</th>
        <th style="text-align:right">Median</th><th style="text-align:right">Range</th>
        <th style="text-align:right">Discounted</th>
        <th style="text-align:right">Rec. price</th></tr>
    __TREND_ROWS__
  </table>
  <div class="note">Rec. price = suggested price for the hypothetical $250 anchor listing from that day's daily report (comp-set anchored).</div>

  <h2>Comp-set churn (__PREV__ → __LAST__)</h2>
  <table>
    <tr><th>🆕 New competitors since __PREV__</th><th></th><th style="text-align:right">Price</th></tr>
    __NEW_ROWS__
  </table>
  <div style="height:12px"></div>
  <table>
    <tr><th>👋 Competitors dropped since __PREV__</th><th></th><th style="text-align:right">Last price</th></tr>
    __GONE_ROWS__
  </table>

  <h2>Price movers (competitors, across all days)</h2>
  <div class="panel">__MOVERS__</div>

  <h2>Recommendation history</h2>
  <table>
    <tr><th>Date</th><th style="text-align:right">Suggested</th><th style="text-align:right">Confidence</th></tr>
    __REC_ROWS__
  </table>

  <h2>🗺️ Competitor map (__LAST__)</h2>
  <iframe src="market_trend_map.html" title="Competitor trend map"></iframe>
  <div class="note">Price-coded chips = current competitors; dashed grey pins = former competitors.
    Click any pin for its full price history. Also openable directly:
    <a href="market_trend_map.html">market_trend_map.html</a></div>

  <div class="note" style="margin-top:24px">Strong competitors only: listings passing the config/areas.json competitor
    filters (3–5 BR houses/townhomes, $150–600, ≤20 km) with a matching competitor_scores row
    of total_score ≥ __MINSCORE__ on that date — low-scoring weak matches are excluded.
    Scoring is similarity to the <b>hypothetical</b> 4BR anchor at UT Dallas, not a real listing.
    Source: data/market.db · generated by reports/trend_report.py — re-run after any daily run.</div>
</div>
</body>
</html>
"""


def main():
    if not DB_PATH.exists():
        sys.exit(f"No database at {DB_PATH}")
    days, day_stats, hist, meta = load_data()
    if not days:
        sys.exit("No snapshots in database")
    recs = parse_recs(days)
    build_map(days, hist, meta, day_stats)
    build_report(days, day_stats, hist, meta, recs)
    print(f"OK: {MAP_OUT.name} + {REPORT_OUT.name}  "
          f"({len(days)} days, {len(hist)} competitors, {len(recs)} recs)")


if __name__ == "__main__":
    main()
