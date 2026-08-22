#!/usr/bin/env python3
"""
Inject the pricing recommendation into a competitor map HTML.

Computes the recommendation from the map's own top-N JSON (so the map and
the daily report always use identical logic: PriceAnalyzer.recommend with
the top-20 closest comps), then patches the HTML:

  1. Adds a "Recommended price" card (top-right)
  2. Enriches the Our Property popup with current vs suggested + reasoning
  3. Adds a legend-style REC const injected into the JS

Re-runnable: idempotent markers <!--REC-START--> ... <!--REC-END--> wrap
everything this script adds, so stale blocks are replaced on re-run.

Usage:
    python3 add_rec_to_map.py utdallas_4br_map.html utdallas_4br_top20.json
"""

import json
import sys
from pathlib import Path

# Allow running from repo root or reports/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from market_agent.competitor_scorer import PropertyProfile, ScoredListing
from market_agent.price_analysis import PriceAnalyzer
from market_agent.scraper import Listing


def build_comp_listings(data: dict) -> list[ScoredListing]:
    """Rank order in the JSON == closest-first order for the comp set."""
    scored = []
    for c in data["top20"]:
        scored.append(ScoredListing(
            listing=Listing(
                listing_id=str(c.get("listing_id", c["rank"])),
                title=c.get("title", ""),
                price=float(c.get("price", 0) or 0),
                rating=c.get("rating"),
                reviews=int(c.get("reviews", 0) or 0),
                bedrooms=int(c.get("bedrooms", 0) or 0),
                property_type=c.get("property_type", ""),
                lat=c.get("lat"),
                lng=c.get("lng"),
            ),
            total_score=c.get("score", 0) / 100.0,
        ))
    return scored


def main(map_path: str, json_path: str) -> None:
    html = Path(map_path).read_text()
    data = json.loads(Path(json_path).read_text())

    prop = data["our_property"]
    profile = PropertyProfile(
        lat=prop.get("lat", 0), lng=prop.get("lng", 0),
        bedrooms=prop.get("bedrooms", 0), price=prop.get("price", 0),
        property_type=prop.get("property_type", ""),
        rating=prop.get("rating"),
        is_guest_favorite=prop.get("is_guest_favorite", False),
        is_superhost=prop.get("is_superhost", False),
    )

    rec = PriceAnalyzer().recommend(profile, build_comp_listings(data))
    if rec is None:
        sys.exit("Not enough priced comps — no recommendation to inject.")

    delta = ((rec.suggested_price - profile.price) / profile.price * 100
             if profile.price else 0)
    bullets = [s.rstrip(".") for s in rec.reasoning.split(". ") if s.strip(". ")]

    # The analyzer assumes absent discount data means "no discounts" —
    # for map JSONs that simply lack the field, drop that misleading
    # bullet and say so instead.
    has_demand_data = any(
        c.get("discount_amount") is not None or c.get("available") is not None
        for c in data["top20"]
    )
    if not has_demand_data:
        bullets = [
            ("No discount/availability data in this scrape — demand signal "
             "unavailable (treated as neutral)")
            if "discounting" in b else b
            for b in bullets
        ]

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
    new_popup = f"""if (isOurs) {{ return `<div class="popup-title">🏠 OUR PROPERTY (Imaginary)</div><div class="popup-row"><span class="popup-label">Type</span><span class="popup-value">4BR Home</span></div><div class="popup-row"><span class="popup-label">Price</span><span class="popup-value">$250/night</span></div><div class="popup-row"><span class="popup-label">Location</span><span class="popup-value">Richardson, TX 75080</span></div><div class="popup-row"><span class="popup-label">Suggested</span><span class="popup-value" style="color:#f39c12">${rec.suggested_price:.0f}/night</span></div><div class="popup-row"><span class="popup-label">Confidence</span><span class="popup-value">{rec.confidence:.0%}</span></div>`; }}"""

    # ---- Idempotent injection ------------------------------------------
    def replace_block(text: str, start: str, end: str, block: str, anchor: str) -> str:
        import re
        pattern = re.compile(re.escape(start) + r".*?" + re.escape(end) + r"\n?", re.DOTALL)
        if pattern.search(text):
            return pattern.sub(lambda _: block, text, count=1)
        return text.replace(anchor, block + "\n" + anchor, 1)

    html = replace_block(html, "<!--REC-CSS-START-->", "<!--REC-CSS-END-->", rec_css, "</style>")
    html = replace_block(html, "<!--REC-START-->", "<!--REC-END-->", rec_js, "</body>")
    if old_popup in html:
        html = html.replace(old_popup, new_popup, 1)
    elif "Suggested</span>" in html:
        pass  # popup already patched
    else:
        sys.exit("Our-property popup not found — map template changed?")

    Path(map_path).write_text(html)
    print(f"Injected: current ${profile.price:.0f} → suggested ${rec.suggested_price:.0f} "
          f"({delta:+.0f}%, confidence {rec.confidence:.0%})")
    for b in bullets:
        print(f"  • {b}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(f"usage: {sys.argv[0]} <map.html> <top20.json>")
    main(sys.argv[1], sys.argv[2])
