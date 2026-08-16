#!/usr/bin/env python3
"""
score_top20.py — Fetch real coordinates for the UT Dallas Top 20 listings,
then score listing #1 against the other 19 as competitors.

Usage:
    python score_top20.py
    python score_top20.py --input ut_dallas_top20.txt --output reports/ut_dallas_competitor_scores.json
"""

import argparse
import asyncio
import json
import math
import re
import sys
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

import pyairbnb
from market_agent.competitor_scorer import CompetitorScorer, PropertyProfile
from market_agent.scraper import Listing


def parse_top20(path: Path) -> list[dict]:
    """Parse the ut_dallas_top20.txt file into structured listings."""
    text = path.read_text()
    listings = []
    raw_blocks = re.split(r'\n\n(?=\d+\.\s)', text)

    for block in raw_blocks[1:]:
        lines = [l.strip() for l in block.strip().split('\n')]

        m0 = re.match(r'(\d+)\.\s+(.+?)\s+[—-]\s+\$(\d+)/night', lines[0])
        if not m0:
            continue
        idx = int(m0.group(1))
        ptype = m0.group(2).strip()
        price = float(m0.group(3))

        bedrooms, bathrooms, guests, rating, reviews = 0, 0.0, 0, None, 0
        if len(lines) > 1:
            m1 = re.match(
                r'(\d+)BR/([\d.]+)ba\s*\|\s*(\d+)\s+guests\s*\|\s*(.+?)★\s*\((\d+)\s+reviews\)',
                lines[1],
            )
            if m1:
                bedrooms = int(m1.group(1))
                bathrooms = float(m1.group(2))
                guests = int(m1.group(3))
                rstr = m1.group(4).strip()
                rating = float(rstr) if rstr and rstr != 'None' else None
                reviews = int(m1.group(5))

        is_superhost = False
        is_guest_fav = False
        if len(lines) > 2:
            is_superhost = "Superhost: Yes" in lines[2]
            is_guest_fav = "Guest Favorite: Yes" in lines[2]

        neighborhood = ""
        if len(lines) > 3:
            nb = lines[3]
            neighborhood = nb.replace("Neighborhood:", "").strip() if "Neighborhood:" in nb else ""

        room_id = ""
        url = ""
        if len(lines) > 4:
            url_m = re.search(r'rooms/(\d+)', lines[4])
            if url_m:
                room_id = url_m.group(1)
                url = f"https://www.airbnb.com/rooms/{room_id}"

        listings.append({
            "idx": idx,
            "room_id": room_id,
            "title": ptype,
            "price": price,
            "bedrooms": bedrooms,
            "bathrooms": bathrooms,
            "guests": guests,
            "rating": rating,
            "reviews": reviews,
            "is_superhost": is_superhost,
            "is_guest_favorite": is_guest_fav,
            "neighborhood": neighborhood,
            "url": url,
            "property_type": ptype,
        })

    return listings


def _parse_bedrooms_from_details(details: dict) -> int:
    """Extract bedroom count from pyairbnb details response."""
    ctr = details.get("structuredContent") or {}
    for line in (ctr.get("primaryLine") or []):
        body = line.get("body", "")
        if "bedroom" in body.lower():
            m = re.match(r'(\d+)\s+bedroom', body, re.IGNORECASE)
            if m:
                return int(m.group(1))
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
    """Extract nightly price from pyairbnb details response."""
    price_block = details.get("price", {})
    unit = price_block.get("unit", {})
    amount = unit.get("amount") or unit.get("discount")
    if amount and float(amount) > 0:
        return float(amount)
    rate = details.get("rate", {})
    if isinstance(rate, dict):
        amount = rate.get("amount")
        if amount and float(amount) > 0:
            return float(amount)
    return 0.0


def _parse_latlng_from_details(details: dict) -> tuple[float | None, float | None]:
    """
    Extract coordinates from pyairbnb details response.

    Checks multiple possible locations where coordinates may appear.
    """
    # 1. Top-level coordinates object
    coords = details.get("coordinates", {})
    if isinstance(coords, dict):
        lat = coords.get("latitude") or coords.get("latitud")
        lng = coords.get("longitude") or coords.get("longitud") or coords.get("lng")
        if lat is not None and lng is not None:
            return float(lat), float(lng)

    # 2. Sometimes coordinates are in listingPDanb or similar nested keys
    for nested_key in ("listingPDanb", "p3Summary", "location"):
        nested = details.get(nested_key)
        if isinstance(nested, dict):
            lat = nested.get("lat") or nested.get("latitude")
            lng = nested.get("lng") or nested.get("longitude")
            if lat is not None and lng is not None:
                return float(lat), float(lng)

    # 3. Search recursively for lat/lng in the dict
    def _find_coords(obj, depth=0):
        if depth > 5 or not isinstance(obj, dict):
            return None, None
        lat = obj.get("latitude") or obj.get("lat")
        lng = obj.get("longitude") or obj.get("lng") or obj.get("longitud")
        if lat is not None and lng is not None:
            try:
                return float(lat), float(lng)
            except (TypeError, ValueError):
                pass
        for v in obj.values():
            if isinstance(v, dict):
                la, ln = _find_coords(v, depth + 1)
                if la is not None:
                    return la, ln
        return None, None

    lat, lng = _find_coords(details)
    if lat is not None and lng is not None:
        return lat, lng

    return None, None


async def fetch_coordinates(room_id: str, url: str) -> tuple[float | None, float | None, dict]:
    """
    Fetch real coordinates for a listing via pyairbnb.get_details.

    Returns (lat, lng, raw_details).
    """
    raw = await asyncio.to_thread(
        pyairbnb.get_details,
        room_url=url,
        currency="USD",
        adults=2,
        language="en",
    )
    lat, lng = _parse_latlng_from_details(raw)
    return lat, lng, raw


async def enrich_all_listings(listings: list[dict], max_concurrent: int = 3) -> list[dict]:
    """
    Fetch real coordinates for all listings concurrently.

    Uses a small concurrency limit to avoid rate-limiting.
    """
    semaphore = asyncio.Semaphore(max_concurrent)
    total = len(listings)

    async def enrich_one(idx: int, listing: dict) -> dict:
        async with semaphore:
            room_id = listing["room_id"]
            url = listing["url"]
            print(f"  [{idx+1}/{total}] Fetching coordinates for #{listing['idx']} (room {room_id})...")
            try:
                lat, lng, raw = await fetch_coordinates(room_id, url)
                if lat is not None and lng is not None:
                    listing["lat"] = lat
                    listing["lng"] = lng
                    print(f"    ✓ {lat:.6f}, {lng:.6f}")
                else:
                    print(f"    ✗ No coordinates found in response")

                # Also enrich bedrooms/price/type from details if missing
                if listing["bedrooms"] == 0:
                    listing["bedrooms"] = _parse_bedrooms_from_details(raw)
                det_price = _parse_price_from_details(raw)
                if det_price > 0 and listing["price"] == 0:
                    listing["price"] = det_price
                room_type = raw.get("room_type", "")
                if room_type and listing["property_type"] in ("Room", "Place to stay", ""):
                    listing["property_type_detail"] = room_type

            except Exception as e:
                print(f"    ✗ Error: {e}")

            return listing

    tasks = [enrich_one(i, l) for i, l in enumerate(listings)]
    return await asyncio.gather(*tasks)


def score_competitors(our_prop: dict, competitors: list[dict]) -> list[dict]:
    """
    Score competitors against our property using the CompetitorScorer.

    Returns list of {listing, score, breakdown} sorted by score desc.
    """

    # Build PropertyProfile from our property
    profile = PropertyProfile(
        lat=our_prop.get("lat", 0.0),
        lng=our_prop.get("lng", 0.0),
        bedrooms=our_prop.get("bedrooms", 0),
        price=our_prop.get("price", 0.0),
        property_type=our_prop.get("property_type", ""),
    )

    scorer = CompetitorScorer(profile, max_distance_km=20.0)

    results = []
    for comp in competitors:
        # Build a Listing object for the scorer
        listing = Listing(
            listing_id=comp.get("room_id", ""),
            title=comp.get("title", ""),
            price=comp.get("price", 0.0),
            original_price=comp.get("price", 0.0),
            rating=comp.get("rating"),
            reviews=comp.get("reviews", 0),
            property_type=comp.get("property_type", ""),
            bedrooms=comp.get("bedrooms", 0),
            bathrooms=comp.get("bathrooms", 0.0),
            guests=comp.get("guests", 0),
            neighborhood=comp.get("neighborhood", ""),
            url=comp.get("url", ""),
            lat=comp.get("lat"),
            lng=comp.get("lng"),
            is_super_host=comp.get("is_superhost", False),
        )

        scored = scorer.score(listing)

        # Compute distance for display
        dist_km = None
        if comp.get("lat") and comp.get("lng") and profile.lat and profile.lng:
            dist_km = _haversine_km(profile.lat, profile.lng, comp["lat"], comp["lng"])

        results.append({
            "comp": comp,
            "total_score": scored.total_score * 100,
            "breakdown": {k: round(v * 100, 1) for k, v in scored.breakdown.items()},
            "distance_km": round(dist_km, 2) if dist_km is not None else None,
        })

    results.sort(key=lambda x: x["total_score"], reverse=True)
    return results


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6371.0
    lat1_r, lat2_r = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlng / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def print_report(our_prop: dict, results: list[dict]):
    """Print a readable scoring report."""
    print("\n" + "=" * 100)
    print(f"OUR PROPERTY: #{our_prop['idx']} — {our_prop['title']} · ${our_prop['price']:.0f}/night")
    lat_str = f"{our_prop['lat']:.4f}" if our_prop.get("lat") else "N/A"
    lng_str = f"{our_prop['lng']:.4f}" if our_prop.get("lng") else "N/A"
    print(f"  Coordinates: ({lat_str}, {lng_str})")
    print(f"  {our_prop.get('bedrooms', 0)}BR · {our_prop.get('bathrooms', 0)}ba · {our_prop.get('guests', 0)} guests")
    print(f"  Neighborhood: {our_prop.get('neighborhood', 'N/A')}")
    print(f"  URL: {our_prop['url']}")
    print("=" * 100)

    print(f"\n{'Rank':<5} {'#':<4} {'Score':<7} {'Type':<24} {'Price':<7} {'Dist':<10} {'Loc':<5} {'Bed':<5} {'Pr':<5} {'Typ'}")
    print("-" * 100)

    for rank, r in enumerate(results, 1):
        c = r["comp"]
        dist_str = f"{r['distance_km']:.1f}km" if r["distance_km"] is not None else "N/A"
        bd = r["breakdown"]
        print(
            f"{rank:<5} #{c['idx']:<3} {r['total_score']:>5.1f}   "
            f"{c['property_type']:<24.24} ${c['price']:<6.0f} "
            f"{dist_str:<10} "
            f"{bd.get('location', 0):>4.0f}% {bd.get('bedrooms', 0):>4.0f}% "
            f"{bd.get('price', 0):>4.0f}% {bd.get('property_type', 0):>3.0f}%"
        )

    # Stats
    scores = [r["total_score"] for r in results]
    with_coords = [r for r in results if r["distance_km"] is not None]
    print(f"\n{'─' * 100}")
    print(f"  Top competitor:      #{results[0]['comp']['idx']} — {results[0]['comp']['property_type']} "
          f"(${results[0]['comp']['price']:.0f}/night) → {results[0]['total_score']:.1f}/100")
    print(f"  Avg competitor score: {sum(scores)/len(scores):.1f}/100")
    print(f"  Lowest competitor:    #{results[-1]['comp']['idx']} — {results[-1]['comp']['property_type']} "
          f"(${results[-1]['comp']['price']:.0f}/night) → {results[-1]['total_score']:.1f}/100")
    print(f"  Listings with coordinates: {len(with_coords)}/{len(results)}")

    if with_coords:
        dists = [r["distance_km"] for r in with_coords]
        print(f"  Distance range: {min(dists):.1f}km – {max(dists):.1f}km (avg {sum(dists)/len(dists):.1f}km)")


def main():
    parser = argparse.ArgumentParser(description="Score UT Dallas Top 20 listings as competitors")
    parser.add_argument("--input", default="ut_dallas_top20.txt", help="Input top20 file")
    parser.add_argument("--output", default="reports/ut_dallas_competitor_scores.json", help="Output JSON")
    parser.add_argument("--max-concurrent", type=int, default=3, help="Max concurrent detail fetches")
    args = parser.parse_args()

    input_path = PROJECT_ROOT / args.input
    output_path = PROJECT_ROOT / args.output

    print(f"Parsing {input_path.name}...")
    listings = parse_top20(input_path)
    print(f"  Parsed {len(listings)} listings\n")

    # Fetch real coordinates for all listings
    print("Fetching real coordinates from Airbnb...")
    listings = asyncio.run(enrich_all_listings(listings, max_concurrent=args.max_concurrent))

    found = sum(1 for l in listings if l.get("lat") is not None)
    print(f"\n  Got coordinates for {found}/{len(listings)} listings\n")

    # Our property = listing #1
    our_prop = listings[0]
    competitors = listings[1:]

    # Score
    print("Scoring competitors...")
    results = score_competitors(our_prop, competitors)

    # Print report
    print_report(our_prop, results)

    # Save JSON
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps({
        "our_property": our_prop,
        "competitors": [
            {
                "idx": r["comp"]["idx"],
                "title": r["comp"]["title"],
                "price": r["comp"]["price"],
                "bedrooms": r["comp"]["bedrooms"],
                "property_type": r["comp"]["property_type"],
                "lat": r["comp"].get("lat"),
                "lng": r["comp"].get("lng"),
                "distance_km": r["distance_km"],
                "score": round(r["total_score"], 1),
                "breakdown": r["breakdown"],
            }
            for r in results
        ],
    }, indent=2))
    print(f"\n  ✓ Saved to {output_path}")


if __name__ == "__main__":
    main()
