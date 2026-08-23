#!/usr/bin/env python3
"""
Inject the pricing recommendation into a competitor map HTML.

The recommendation is computed from the PRODUCTION comp set — the latest
daily-pipeline scores in data/market.db (which apply the competitor filters
in config/areas.json: price band, bedrooms, property types) — so the map
card always matches the daily report. The map's display pins may include
listings outside that band (e.g. luxury event estates); those are shown
for context but are NOT competitors and do not move the price.

Patches the HTML:
  1. Adds a "Recommended price" card (top-right)
  2. Enriches the Our Property popup with current vs suggested + reasoning

Re-runnable: idempotent markers <!--REC-START--> ... <!--REC-END--> wrap
everything this script adds, so stale blocks are replaced on re-run; the
Suggested/Confidence values in an already-patched popup are updated too.

Usage:
    python3 add_rec_to_map.py utdallas_4br_map.html
"""

import json
import re
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from market_agent.competitor_scorer import PropertyProfile, ScoredListing
from market_agent.price_analysis import PriceAnalyzer
from market_agent.scraper import Listing

DB_PATH = PROJECT_ROOT / "data" / "market.db"
AREAS_PATH = PROJECT_ROOT / "config" / "areas.json"


def load_profile() -> PropertyProfile:
    """Property profile from config/areas.json — same source as the daily run."""
    cfg = json.loads(AREAS_PATH.read_text())
    p = cfg["search_areas"][0]["property_profile"]
    return PropertyProfile(
        lat=p.get("lat", 0), lng=p.get("lng", 0),
        bedrooms=p.get("bedrooms", 0), price=p.get("price", 0),
        property_type=p.get("property_type", ""),
        rating=p.get("rating"),
        is_guest_favorite=p.get("is_guest_favorite", False),
        is_superhost=p.get("is_superhost", False),
    )


def load_comps() -> tuple[list[ScoredListing], str]:
    """Latest scored comp set from the daily pipeline DB (deduped by listing)."""
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        latest = con.execute(
            "SELECT MAX(scrape_date) FROM competitor_scores"
        ).fetchone()[0]
        if not latest:
            sys.exit("No scored comps in market.db — run the daily pipeline first.")
        rows = con.execute(
            """
            SELECT cs.listing_id, cs.total_score, l.title, l.price,
                   l.original_price, l.discount_amount, l.available, l.rating,
                   l.reviews, l.property_type, l.bedrooms, l.bathrooms, l.guests,
                   l.neighborhood, l.url, l.lat, l.lng
            FROM competitor_scores cs
            JOIN (
                SELECT listing_id, MAX(id) AS id
                FROM listings WHERE scrape_date = :d
                GROUP BY listing_id
            ) pick ON pick.listing_id = cs.listing_id
            JOIN listings l ON l.id = pick.id
            WHERE cs.scrape_date = :d
            ORDER BY cs.total_score DESC
            """,
            {"d": latest},
        ).fetchall()
    finally:
        con.close()

    scored: list[ScoredListing] = []
    seen: set[str] = set()
    for r in rows:
        if r["listing_id"] in seen:
            continue  # a property is one competitor, however often it was stored
        seen.add(r["listing_id"])
        scored.append(ScoredListing(
            listing=Listing(
                listing_id=r["listing_id"], title=r["title"] or "",
                price=r["price"] or 0.0, original_price=r["original_price"] or 0.0,
                discount_amount=r["discount_amount"] or 0.0,
                rating=r["rating"], reviews=r["reviews"] or 0,
                property_type=r["property_type"] or "",
                bedrooms=r["bedrooms"] or 0, bathrooms=r["bathrooms"] or 0.0,
                guests=r["guests"] or 0, neighborhood=r["neighborhood"] or "",
                url=r["url"] or "", lat=r["lat"], lng=r["lng"],
                available=bool(r["available"]),
            ),
            total_score=r["total_score"],
        ))
    return scored, str(latest)


def main(map_path: str) -> None:
    html = Path(map_path).read_text()

    profile = load_profile()
    scored, scrape_date = load_comps()
    rec = PriceAnalyzer().recommend(profile, scored)
    if rec is None:
        sys.exit("Not enough priced comps — no recommendation to inject.")

    delta = ((rec.suggested_price - profile.price) / profile.price * 100
             if profile.price else 0)
    bullets = [s.rstrip(".") for s in rec.reasoning.split(". ") if s.strip(". ")]

    # Make the card honest about what the pins show vs what sets the price:
    # pins can include listings outside the areas.json competitor band.
    cfg = json.loads(AREAS_PATH.read_text())
    area = cfg["search_areas"][0]
    cf = area.get("competitor_filters", {})
    lo = cf.get("target_price_min", area.get("target_price_min"))
    hi = cf.get("target_price_max", area.get("target_price_max"))
    band = f"${lo:.0f}-${hi:.0f}" if hi else "unbanded"
    br = (f"{cf.get('min_bedrooms')}-{cf.get('max_bedrooms')}BR"
          if cf.get("min_bedrooms") and cf.get("max_bedrooms") else "")
    basis = f"Comp basis: daily scan {scrape_date} ({band}"
    basis += f", {br}" if br else ""
    basis += ") — display pins outside the band aren't counted"
    bullets.insert(0, basis)

    # ---- JS block -------------------------------------------------------
    rec_js = f"""<!--REC-START-->
<script>
const REC = {{
  current: {profile.price:.0f},
  suggested: {rec.suggested_price:.0f},
  confidence: {rec.confidence:.2f},
  bullets: {json.dumps(bullets)},
}};
(function () {{
  const card = document.createElement('div');
  card.className = 'rec-card';
  const sign = {delta:+.0f} >= 0 ? '+' : '';
  card.innerHTML =
    '<h3>💡 Recommended Price</h3>' +
    `<div class="rec-price">${{REC.suggested}}<span>/night</span></div>` +
    `<div class="rec-delta">${{REC.current ? `currently $${{REC.current}} · ${{sign}}{abs(delta):.0f}%` : 'no current price set'}}</div>` +
    `<div class="rec-conf">confidence ${{(REC.confidence * 100).toFixed(0)}}%</div>` +
    REC.bullets.map(b => `<div class="rec-bullet">• ${{b}}</div>`).join('');
  document.body.appendChild(card);
}})();
</script>
<!--REC-END-->"""

    # ---- CSS block ------------------------------------------------------
    rec_css = """<!--REC-CSS-START-->
<style>
  .rec-card { position: absolute; top: 20px; right: 20px; z-index: 1000; background: rgba(15,23,41,0.95); padding: 14px 18px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.4); max-width: 300px; font-size: 12px; border: 1px solid #2a3a5c; }
  .rec-card h3 { font-size: 12px; color: #f39c12; margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.5px; }
  .rec-price { font-size: 26px; font-weight: 800; color: #fff; line-height: 1.1; }
  .rec-price span { font-size: 11px; font-weight: 400; color: #888; }
  .rec-delta { color: #2ecc71; font-weight: 600; margin: 2px 0; }
  .rec-conf { color: #7788aa; font-size: 11px; margin-bottom: 6px; }
  .rec-bullet { color: #aabbcc; font-size: 11px; line-height: 1.45; }
</style>
<!--REC-CSS-END-->"""

    # ---- Our-property popup enrichment ---------------------------------
    old_popup = "if (isOurs) { return `<div class=\"popup-title\">🏠 OUR PROPERTY (Imaginary)</div><div class=\"popup-row\"><span class=\"popup-label\">Type</span><span class=\"popup-value\">4BR Home</span></div><div class=\"popup-row\"><span class=\"popup-label\">Price</span><span class=\"popup-value\">$250/night</span></div><div class=\"popup-row\"><span class=\"popup-label\">Location</span><span class=\"popup-value\">Richardson, TX 75080</span></div>`; }"
    new_popup = f"""if (isOurs) {{ return `<div class="popup-title">🏠 OUR PROPERTY (Imaginary)</div><div class="popup-row"><span class="popup-label">Type</span><span class="popup-value">4BR Home</span></div><div class="popup-row"><span class="popup-label\">Price</span><span class=\"popup-value\">$250/night</span></div><div class=\"popup-row\"><span class=\"popup-label\">Location</span><span class=\"popup-value\">Richardson, TX 75080</span></div><div class="popup-row\"><span class="popup-label\">Suggested</span><span class="popup-value" style="color:#f39c12">${rec.suggested_price:.0f}/night</span></div><div class="popup-row"><span class="popup-label\">Confidence</span><span class="popup-value">{rec.confidence:.0%}</span></div>`; }}"""

    # ---- Idempotent injection ------------------------------------------
    def replace_block(text: str, start: str, end: str, block: str, anchor: str) -> str:
        pattern = re.compile(re.escape(start) + r".*?" + re.escape(end) + r"\n?", re.DOTALL)
        if pattern.search(text):
            return pattern.sub(lambda _: block, text, count=1)
        return text.replace(anchor, block + "\n" + anchor, 1)

    html = replace_block(html, "<!--REC-CSS-START-->", "<!--REC-CSS-END-->", rec_css, "</style>")
    html = replace_block(html, "<!--REC-START-->", "<!--REC-END-->", rec_js, "</body>")

    if old_popup in html:
        html = html.replace(old_popup, new_popup, 1)
    elif "Suggested</span>" in html:
        # Popup already patched on a previous run — refresh its numbers.
        html = re.sub(
            r'(Suggested</span><span class="popup-value"[^>]*>\$)\d+(/night)',
            rf'\g<1>{rec.suggested_price:.0f}\g<2>', html)
        html = re.sub(
            r'(Confidence</span><span class="popup-value">)\d+%',
            '\\g<1>' + f'{rec.confidence:.0%}', html)
    else:
        sys.exit("Our-property popup not found — map template changed?")

    Path(map_path).write_text(html)
    print(f"Injected: current ${profile.price:.0f} → suggested ${rec.suggested_price:.0f} "
          f"({delta:+.0f}%, confidence {rec.confidence:.0%})")
    print(f"  Source: market.db scrape {scrape_date}, {len(scored)} deduped comps")
    for b in bullets:
        print(f"  • {b}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(f"usage: {sys.argv[0]} <map.html>")
    main(sys.argv[1])
