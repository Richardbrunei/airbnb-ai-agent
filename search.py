#!/usr/bin/env python3
"""
search.py — Standalone CLI for Airbnb competitor search & analysis.

Usage examples:

  # Search by location (uses config/areas.json bbox or built-in defaults)
  python search.py --location "Austin, TX" --checkin 2026-08-01 --checkout 2026-08-07

  # Search around a specific Airbnb listing URL
  # Fetches the listing's coordinates, then finds competitors nearby.
  # Scoring is automatic (uses the listing as the property profile).
  python search.py --url "https://www.airbnb.com/rooms/1234567890"

  # Control the search radius around a URL (default: 5km)
  python search.py --url "https://www.airbnb.com/rooms/1234567890" --radius 3

  # Tight radius around coordinates
  python search.py --lat 30.267 --lng -97.743 --radius 2 --checkin 2026-08-01 --checkout 2026-08-07

  # Output to JSON and print a summary table
  python search.py --location "Austin, TX" --output competitors.json

  # Use property profile from config for scoring
  python search.py --location "Austin, TX" --score

  # Adjust filters
  python search.py --location "Austin, TX" --min-price 100 --max-price 300 --bedrooms 2

  # Next weekend (default dates if omitted)
  python search.py --location "Austin, TX"
"""

import argparse
import asyncio
import json
import logging
import re
import sys
from datetime import date, timedelta
from pathlib import Path

# Ensure project root is on sys.path when run from anywhere
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

import pyairbnb
from market_agent.scraper import AirbnbScraper, Listing
from market_agent.competitor_scorer import CompetitorScorer, PropertyProfile
from data import storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("search")


def default_dates():
    """Default to next Friday → Saturday."""
    today = date.today()
    days_to_friday = (4 - today.weekday()) % 7 or 7
    fri = today + timedelta(days=days_to_friday)
    sat = fri + timedelta(days=1)
    return fri.isoformat(), sat.isoformat()


def extract_room_id(url: str) -> str:
    """Extract the room ID from an Airbnb listing URL."""
    m = re.search(r'/rooms/(\d+)', url)
    return m.group(1) if m else ""


def _parse_bedrooms_from_details(details: dict) -> int:
    """Try to extract bedroom count from listing details."""
    # Check structuredContent
    ctr = details.get("structuredContent") or {}
    for line in (ctr.get("primaryLine") or []):
        body = line.get("body", "")
        if "bedroom" in body.lower():
            m = re.match(r'(\d+)\s+bedroom', body, re.IGNORECASE)
            if m:
                return int(m.group(1))
    # Check listing details for bedroom label
    for key in ("bedrooms", "bedroom_label", "beds"):
        val = details.get(key)
        if isinstance(val, int) and val > 0:
            return val
        if isinstance(val, str):
            m = re.match(r'(\d+)', val)
            if m:
                return int(m.group(1))
    return 0


def _parse_price_from_details(details: dict) -> float:
    """Try to extract a nightly price from listing details."""
    price_block = details.get("price", {})
    unit = price_block.get("unit", {})
    amount = unit.get("amount") or unit.get("discount")
    if amount and float(amount) > 0:
        return float(amount)
    # Sometimes under rate
    rate = details.get("rate", {})
    if isinstance(rate, dict):
        amount = rate.get("amount")
        if amount and float(amount) > 0:
            return float(amount)
    return 0.0


async def fetch_listing_info(url: str) -> dict:
    """
    Fetch a listing's coordinates and key details from its URL.

    Returns dict with: room_id, lat, lng, title, bedrooms, price,
    property_type, rating, reviews, url.
    """
    room_id = extract_room_id(url)
    if not room_id:
        raise ValueError(f"Could not extract room ID from URL: {url}")

    print(f"  Fetching listing details for room {room_id}...")
    raw = await asyncio.to_thread(
        pyairbnb.get_details,
        room_url=url,
        currency="USD",
        adults=2,
        language="en",
    )

    coords = raw.get("coordinates", {})
    lat = coords.get("latitude") or coords.get("latitud")
    lng = coords.get("longitude") or coords.get("longitud") or coords.get("lng")

    if lat is None or lng is None:
        raise ValueError(f"Could not extract coordinates from listing {room_id}")

    # Title can be string or list of rich-text fragments
    title = raw.get("name", raw.get("title", ""))
    if isinstance(title, list):
        title = " ".join(
            seg.get("text", "") if isinstance(seg, dict) else str(seg)
            for seg in title
        ).strip()

    # Rating
    rating = None
    reviews = 0
    rating_info = raw.get("rating", {})
    if isinstance(rating_info, dict):
        rating = float(rating_info.get("guest_satisfaction") or rating_info.get("value") or 0) or None
        rc = rating_info.get("review_count", "0")
        reviews = int(rc) if rc else 0

    return {
        "room_id": room_id,
        "lat": float(lat),
        "lng": float(lng),
        "title": title,
        "bedrooms": _parse_bedrooms_from_details(raw),
        "price": _parse_price_from_details(raw),
        "property_type": raw.get("room_type", ""),
        "rating": rating,
        "reviews": reviews,
        "url": url,
    }


def print_summary(listings: list[Listing], scored=None, source_listing=None):
    """Print a readable summary table to stdout."""
    if source_listing:
        print(f"\n{'='*100}")
        print(f"  Source: {source_listing.get('title', source_listing['room_id'])}")
        print(f"  Location: {source_listing['lat']:.4f}, {source_listing['lng']:.4f}")
        if source_listing.get("bedrooms"):
            print(f"  Bedrooms: {source_listing['bedrooms']}")
        if source_listing.get("price"):
            print(f"  Listed price: ${source_listing['price']:.0f}/night")
        if source_listing.get("rating"):
            print(f"  Rating: {source_listing['rating']:.2f} ({source_listing['reviews']} reviews)")
        print(f"  URL: {source_listing['url']}")

    if not listings:
        print("\n  No listings found.")
        return

    source = scored if scored else listings

    print(f"\n{'='*100}")
    print(f"  Found {len(listings)} competitor listings")
    print(f"{'='*100}")

    if scored:
        print(f"\n{'#':<4} {'Score':<7} {'$/night':<9} {'Orig':<9} {'Beds':<5} {'Rating':<7} {'Reviews':<8} {'Type':<16} {'Title'}")
        print(f"{'-'*4} {'-'*7} {'-'*9} {'-'*9} {'-'*5} {'-'*7} {'-'*8} {'-'*16} {'-'*40}")
        for i, s in enumerate(scored, 1):
            l = s.listing
            rating_str = f"{l.rating:.2f}" if l.rating else "—"
            print(
                f"{i:<4} {s.total_score:<7.2f} ${l.price:<8.0f} ${l.original_price:<8.0f} "
                f"{l.bedrooms:<5} {rating_str:<7} {l.reviews:<8} {l.property_type:<16.16} {l.title[:40]}"
            )
            if l.discount_types:
                print(f"     → Discounts: {', '.join(l.discount_types)} ({l.discount_pct:.0f}% off)")
            print(f"     → {l.url}")
    else:
        prices = [l.price for l in listings if l.price > 0]
        if prices:
            prices_sorted = sorted(prices)
            median = prices_sorted[len(prices_sorted) // 2]
            print(f"\n  Price: ${min(prices):.0f} – ${max(prices):.0f} | Median: ${median:.0f} | Avg: ${sum(prices)/len(prices):.0f}")

        print(f"\n{'#':<4} {'$/night':<9} {'Orig':<9} {'Beds':<5} {'Rating':<7} {'Reviews':<8} {'Type':<16} {'Title'}")
        print(f"{'-'*4} {'-'*9} {'-'*9} {'-'*5} {'-'*7} {'-'*8} {'-'*16} {'-'*40}")
        for i, l in enumerate(listings, 1):
            rating_str = f"{l.rating:.2f}" if l.rating else "—"
            print(
                f"{i:<4} ${l.price:<8.0f} ${l.original_price:<8.0f} "
                f"{l.bedrooms:<5} {rating_str:<7} {l.reviews:<8} {l.property_type:<16.16} {l.title[:40]}"
            )
            if l.discount_types:
                print(f"     → Discounts: {', '.join(l.discount_types)} ({l.discount_pct:.0f}% off)")
            print(f"     → {l.url}")

    print()


def export_json(listings: list[Listing], path: str, scored=None, source_listing=None):
    """Export listings to JSON."""
    source = scored if scored else listings
    data = []
    for item in source:
        if hasattr(item, 'listing'):
            l = item.listing
            entry = {
                "score": round(item.total_score, 3),
                "score_breakdown": {k: round(v, 3) for k, v in item.breakdown.items()},
            }
        else:
            l = item
            entry = {}

        entry.update({
            "listing_id": l.listing_id,
            "title": l.title,
            "price": l.price,
            "original_price": l.original_price,
            "currency": l.currency,
            "discount_pct": l.discount_pct,
            "discount_types": l.discount_types,
            "discounts": [
                {"type": d.type, "amount": d.amount, "per_night": d.per_night}
                for d in l.discounts
            ],
            "nights": l.nights,
            "rating": l.rating,
            "reviews": l.reviews,
            "property_type": l.property_type,
            "bedrooms": l.bedrooms,
            "bathrooms": l.bathrooms,
            "neighborhood": l.neighborhood,
            "lat": l.lat,
            "lng": l.lng,
            "url": l.url,
        })
        data.append(entry)

    output = {
        "source_listing": source_listing,
        "search_dates": None,  # filled by run()
        "count": len(data),
        "listings": data,
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"  → Exported {len(data)} listings to {path}")


async def run(args):
    """Main search execution."""
    checkin, checkout = args.checkin, args.checkout
    if not checkin or not checkout:
        checkin, checkout = default_dates()
        print(f"  No dates specified — using next weekend: {checkin} → {checkout}")

    scraper = AirbnbScraper()
    source_listing = None  # populated when --url is used

    # ── Determine search center ──
    # Priority: --url (fetch coords) > --lat/--lng > --bbox > --location
    if args.url:
        # Fetch the listing to get its coordinates + details
        source_listing = await fetch_listing_info(args.url)
        lat, lng = source_listing["lat"], source_listing["lng"]
        print(f"  Listing location: {lat:.4f}, {lng:.4f}")

        # Set bounding box around the listing
        delta = args.radius * 0.012  # ~1km ≈ 0.012 degrees
        area = {
            "name": f"Around listing {source_listing['room_id']}",
            "location": "",
            "bbox": [lat - delta, lng - delta, lat + delta, lng + delta],
        }
    elif args.bbox:
        area = {"name": "CLI Search", "location": args.location or "", "bbox": args.bbox}
    elif args.lat is not None and args.lng is not None:
        delta = args.radius * 0.012
        area = {
            "name": args.location or "CLI Search",
            "location": args.location or "",
            "bbox": [args.lat - delta, args.lng - delta, args.lat + delta, args.lng + delta],
        }
    else:
        area = {"name": args.location or "CLI Search", "location": args.location or ""}

    # Filters from CLI
    cf = {}
    if args.min_price or args.max_price:
        cf["target_price_min"] = args.min_price or 0
        cf["target_price_max"] = args.max_price or 0
    if args.bedrooms is not None:
        cf["min_bedrooms"] = args.bedrooms
        cf["max_bedrooms"] = args.bedrooms
    if args.property_type:
        cf["property_types"] = [args.property_type]
    if cf:
        area["competitor_filters"] = cf

    # Override scraper's areas for this run
    scraper.areas = [area]

    # ── Search ──
    print(f"\n  Searching Airbnb...")
    listings = await scraper.search_competitors(
        location=area.get("location", ""),
        checkin=checkin,
        checkout=checkout,
        adults=args.adults,
    )

    # Exclude the source listing from results if searching by URL
    if args.url and source_listing:
        source_id = source_listing["room_id"]
        listings = [l for l in listings if l.listing_id != source_id]

    if not listings:
        print("\n  No listings found. Try broadening your filters or increasing --radius.")
        return

    # ── Score ──
    # Auto-score when using --url (listing becomes the profile).
    # Also score when --score is explicitly passed.
    scored = None
    profile_data = None

    if source_listing:
        profile_data = source_listing
        print(f"  Auto-scoring against source listing: {source_listing.get('title', source_listing['room_id'])}")
    elif args.score:
        config_path = PROJECT_ROOT / "config" / "areas.json"
        if config_path.exists():
            with open(config_path) as f:
                config = json.load(f)
            areas_cfg = config.get("search_areas", [])
            if areas_cfg and areas_cfg[0].get("property_profile"):
                profile_data = areas_cfg[0]["property_profile"]
        if not profile_data:
            print("  ⚠ --score requested but no property_profile found in config/areas.json")

    if profile_data:
        profile = PropertyProfile(
            lat=profile_data.get("lat", 0),
            lng=profile_data.get("lng", 0),
            bedrooms=profile_data.get("bedrooms", 0),
            price=profile_data.get("price", 0),
            property_type=profile_data.get("property_type", ""),
        )
        # Use CLI radius for scoring distance when searching by URL, else config default
        max_dist = args.radius if source_listing else 20.0
        scorer = CompetitorScorer(profile, max_distance_km=max_dist)
        scored = scorer.score_all(listings)
        print(f"  Scored {len(scored)} competitors.")

    # ── Output ──
    print_summary(listings, scored, source_listing=source_listing)

    if args.save:
        from datetime import datetime as _dt
        scrape_date = _dt.now().strftime("%Y-%m-%d")
        storage.init_db()
        stored = storage.store_listings(listings, scrape_date=scrape_date)
        print(f"  → Stored {stored} listings in database ({storage.DB_PATH})")
        if scored:
            storage.store_scores(scored, scrape_date=scrape_date)
            print(f"  → Stored {len(scored)} competitor scores for {scrape_date}")

    if args.output:
        export_json(listings, args.output, scored, source_listing=source_listing)


def main():
    parser = argparse.ArgumentParser(
        description="Search Airbnb competitor listings.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Search target
    parser.add_argument("-l", "--location", type=str, default="",
                        help="Location to search (e.g. 'Austin, TX')")
    parser.add_argument("-u", "--url", type=str, default="",
                        help="Airbnb listing URL — fetches its coordinates and finds competitors nearby")
    parser.add_argument("--lat", type=float, default=None,
                        help="Latitude for coordinate-based search")
    parser.add_argument("--lng", type=float, default=None,
                        help="Longitude for coordinate-based search")
    parser.add_argument("--radius", type=float, default=5,
                        help="Search radius in km around --url or --lat/--lng (default: 5)")
    parser.add_argument("--bbox", type=float, nargs=4, metavar=("SW_LAT", "SW_LNG", "NE_LAT", "NE_LNG"),
                        default=None,
                        help="Explicit bounding box coordinates")

    # Dates
    parser.add_argument("--checkin", type=str, default="",
                        help="Check-in date YYYY-MM-DD (default: next Friday)")
    parser.add_argument("--checkout", type=str, default="",
                        help="Check-out date YYYY-MM-DD (default: next Saturday)")
    parser.add_argument("--adults", type=int, default=2,
                        help="Number of adults (default: 2)")

    # Filters
    parser.add_argument("--min-price", type=float, default=0,
                        help="Minimum nightly price")
    parser.add_argument("--max-price", type=float, default=0,
                        help="Maximum nightly price (0 = no limit)")
    parser.add_argument("--bedrooms", type=int, default=None,
                        help="Exact bedroom count to filter on")
    parser.add_argument("--property-type", type=str, default="",
                        help="Property type filter (e.g. 'Entire home', 'Condo')")

    # Output
    parser.add_argument("-o", "--output", type=str, default="",
                        help="Output JSON file path")
    parser.add_argument("--score", action="store_true",
                        help="Score competitors against property profile from config/areas.json")
    parser.add_argument("--save", action="store_true",
                        help="Save results to SQLite database (data/market.db)")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Debug logging")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if not args.location and not args.url and args.lat is None and not args.bbox:
        parser.error("Provide --location, --url, --lat/--lng, or --bbox")

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
