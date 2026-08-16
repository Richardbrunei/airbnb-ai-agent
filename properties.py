#!/usr/bin/env python3
"""
properties.py — Manage properties (search areas) in config/areas.json.

Usage:
  python properties.py list
  python properties.py view
  python properties.py view --index 0
  python properties.py add
  python properties.py add --name "Destin Condo" --location "Destin, FL" --lat 30.393 --lng -86.495 --bedrooms 2 --price 220 --property-type "Condo"
  python properties.py edit --index 0 --price 250 --bedrooms 3
  python properties.py edit --name "Destin Condo" --radius 10
  python properties.py remove --index 1
  python properties.py remove --name "Template Area"

Interactive mode (prompts for each field):
  python properties.py add
"""

import argparse
import json
import sys
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent / "config" / "areas.json"


# ── Config helpers ────────────────────────────────────────────────────────────

def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {"search_areas": [], "schedule": {}, "notification": {}}
    with open(CONFIG_PATH) as f:
        return json.load(f)


def save_config(config: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    print(f"  ✓ Saved to {CONFIG_PATH}")


def get_areas(config: dict) -> list[dict]:
    return config.get("search_areas", [])


def find_area(areas: list[dict], index: int | None = None, name: str = "") -> dict | None:
    if index is not None:
        if 0 <= index < len(areas):
            return areas[index]
        print(f"  ✗ Index {index} out of range (0–{len(areas) - 1})")
        return None
    if name:
        for a in areas:
            if a.get("name", "").lower() == name.lower():
                return a
        print(f"  ✗ No area named '{name}'")
        return None
    return None


# ── Display ───────────────────────────────────────────────────────────────────

def print_area(area: dict, index: int, verbose: bool = False):
    name = area.get("name", "Unnamed")
    location = area.get("location", "—")
    profile = area.get("property_profile", {})
    cf = area.get("competitor_filters", {})

    price_str = f"${profile.get('price', 0):.0f}/night" if profile.get("price") else "—"
    beds = profile.get("bedrooms", "—")
    ptype = profile.get("property_type", "—")

    if not verbose:
        print(f"  [{index}] {name}  ({location})  {beds}BR · {ptype} · {price_str}")
        return

    print(f"\n  ┌─ [{index}] {name} ─────────────────────────────────")
    print(f"  │ Location:       {location}")
    if area.get("bbox"):
        print(f"  │ Bounding box:   {area['bbox']}")
    print(f"  │ Radius:         {area.get('radius_km', '—')} km")
    print(f"  │ Max competitor: {area.get('max_competitor_distance_km', '—')} km")
    scan = area.get('scan_around_property', False)
    zip_code = area.get('zip_code', '—')
    print(f"  │ Scan-around:    {'✅ enabled' if scan else '❌ disabled'}")
    print(f"  │ Zip code:       {zip_code}")

    print(f"  │")
    print(f"  │ Property Profile:")
    print(f"  │   Lat/Lng:     {profile.get('lat', '—')}, {profile.get('lng', '—')}")
    print(f"  │   Bedrooms:    {profile.get('bedrooms', '—')}")
    print(f"  │   Price:       {price_str}")
    print(f"  │   Type:        {ptype}")

    if cf:
        print(f"  │")
        print(f"  │ Competitor Filters:")
        if cf.get("min_bedrooms") is not None or cf.get("max_bedrooms") is not None:
            print(f"  │   Bedrooms:    {cf.get('min_bedrooms', '—')} – {cf.get('max_bedrooms', '—')}")
        if cf.get("target_price_min") or cf.get("target_price_max"):
            print(f"  │   Price range: ${cf.get('target_price_min', 0)} – ${cf.get('target_price_max', '∞')}")
        if cf.get("property_types"):
            print(f"  │   Types:       {', '.join(cf['property_types'])}")
        if cf.get("neighborhoods"):
            print(f"  │   Neighborhoods: {', '.join(cf['neighborhoods'])}")
        if cf.get("min_rating"):
            print(f"  │   Min rating:  {cf['min_rating']}")
        if cf.get("min_reviews"):
            print(f"  │   Min reviews: {cf['min_reviews']}")

    print(f"  └{'─' * 50}")


# ── Interactive input ─────────────────────────────────────────────────────────

def prompt(label: str, default="", cast=str) -> any:
    suffix = f" [{default}]" if default != "" else ""
    while True:
        raw = input(f"  {label}{suffix}: ").strip()
        if not raw and default != "":
            return default
        if not raw and cast is not str:
            return 0 if cast is int else 0.0
        try:
            return cast(raw)
        except ValueError:
            if cast is str:
                return raw
            print(f"    Please enter a valid {cast.__name__}")


def prompt_list(label: str, default=None) -> list:
    suffix = f" [{', '.join(default)}]" if default else ""
    raw = input(f"  {label}{suffix} (comma-separated): ").strip()
    if not raw and default:
        return default
    if not raw:
        return []
    return [x.strip() for x in raw.split(",")]


def interactive_area(existing: dict = None) -> dict:
    """Prompt for all area fields interactively."""
    e = existing or {}
    ep = e.get("property_profile", {})
    ec = e.get("competitor_filters", {})

    print("\n  --- Property Details ---")
    name = prompt("Name", e.get("name", ""))
    location = prompt("Location (City, State)", e.get("location", ""))

    print("\n  --- Property Profile ---")
    lat = prompt("Latitude", ep.get("lat", ""), float)
    lng = prompt("Longitude", ep.get("lng", ""), float)
    bedrooms = prompt("Bedrooms", ep.get("bedrooms", 0), int)
    price = prompt("Typical nightly price ($)", ep.get("price", 0), float)
    property_type = prompt("Property type", ep.get("property_type", "Home"))

    print("\n  --- Search Area ---")
    radius = prompt("Search radius (km)", e.get("radius_km", 5), float)
    max_dist = prompt("Max competitor distance (km)", e.get("max_competitor_distance_km", 15), float)
    scan_default = "y" if e.get("scan_around_property", False) else "n"
    scan_raw = input(f"  Scan around property center? (y/n) [{scan_default}]: ").strip().lower()
    scan_around = (scan_raw or scan_default) in ("y", "yes", "true", "1")
    zip_code = prompt("Zip code (optional, overrides bbox via geocoding)", e.get("zip_code", ""), str)

    print("\n  --- Competitor Filters (Enter to skip) ---")
    min_br = prompt("Min bedrooms", ec.get("min_bedrooms", ""), str)
    max_br = prompt("Max bedrooms", ec.get("max_bedrooms", ""), str)
    min_price = prompt("Min price ($)", ec.get("target_price_min", ""), str)
    max_price = prompt("Max price ($)", ec.get("target_price_max", ""), str)
    ptypes = prompt_list("Property types", ec.get("property_types", []))
    min_rating = prompt("Min rating", ec.get("min_rating", ""), str)
    min_reviews = prompt("Min reviews", ec.get("min_reviews", ""), str)

    return build_area_dict(
        name, location, lat, lng, bedrooms, price, property_type,
        radius, max_dist, scan_around, zip_code,
        min_br, max_br, min_price, max_price,
        ptypes, min_rating, min_reviews,
    )


def build_area_dict(
    name, location, lat, lng, bedrooms, price, property_type,
    radius, max_dist, scan_around=False, zip_code="",
    min_br="", max_br="", min_price="", max_price="",
    ptypes=None, min_rating="", min_reviews="",
) -> dict:
    """Build an area dict from individual field values."""
    area = {
        "name": name,
        "location": location,
        "radius_km": radius,
        "scan_around_property": scan_around,
        "property_profile": {
            "lat": lat,
            "lng": lng,
            "bedrooms": bedrooms,
            "price": price,
            "property_type": property_type,
        },
        "max_competitor_distance_km": max_dist,
    }
    if zip_code:
        area["zip_code"] = zip_code

    # Competitor filters — only include non-empty values
    cf = {}
    if min_br:
        cf["min_bedrooms"] = int(min_br)
    if max_br:
        cf["max_bedrooms"] = int(max_br)
    if min_price:
        cf["target_price_min"] = float(min_price)
    if max_price:
        cf["target_price_max"] = float(max_price)
    if ptypes:
        cf["property_types"] = ptypes
    if min_rating:
        cf["min_rating"] = float(min_rating)
    if min_reviews:
        cf["min_reviews"] = int(min_reviews)
    if cf:
        area["competitor_filters"] = cf

    return area


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_list(args):
    config = load_config()
    areas = get_areas(config)
    if not areas:
        print("\n  No properties configured. Use 'add' to create one.")
        return
    print(f"\n  {len(areas)} property(s) configured:\n")
    for i, area in enumerate(areas):
        print_area(area, i)
    print()


def cmd_view(args):
    config = load_config()
    areas = get_areas(config)
    if not areas:
        print("\n  No properties configured.")
        return

    if args.index is not None or args.name:
        area = find_area(areas, index=args.index, name=args.name or "")
        if area:
            idx = args.index if args.index is not None else next(
                i for i, a in enumerate(areas) if a.get("name", "").lower() == args.name.lower()
            )
            print_area(area, idx, verbose=True)
        return

    # Show all verbose
    for i, area in enumerate(areas):
        print_area(area, i, verbose=True)


def cmd_add(args):
    config = load_config()
    areas = get_areas(config)

    if args.interactive or not args.name:
        area = interactive_area()
    else:
        # Validate required fields
        missing = []
        if not args.name: missing.append("--name")
        if not args.location: missing.append("--location")
        if args.lat is None: missing.append("--lat")
        if args.lng is None: missing.append("--lng")
        if missing:
            print(f"  ✗ Missing required: {', '.join(missing)}")
            print("  Or run with no flags for interactive mode.")
            return

        area = build_area_dict(
            args.name, args.location, args.lat, args.lng,
            args.bedrooms or 0, args.price or 0, args.property_type or "Home",
            args.radius, args.max_distance,
            args.scan_around, args.zip_code or "",
            args.min_bedrooms or "", args.max_bedrooms or "",
            args.min_price or "", args.max_price or "",
            args.filter_types or None, args.min_rating or "", args.min_reviews or "",
        )

    areas.append(area)
    config["search_areas"] = areas
    save_config(config)

    print(f"\n  ✓ Added property '{area['name']}'")
    print_area(area, len(areas) - 1, verbose=True)


def cmd_edit(args):
    config = load_config()
    areas = get_areas(config)
    if not areas:
        print("\n  No properties to edit.")
        return

    area = find_area(areas, index=args.index, name=args.name or "")
    if not area:
        return

    idx = args.index if args.index is not None else next(
        i for i, a in enumerate(areas) if a is area
    )

    if args.interactive or not any([
        args.location, args.lat is not None, args.lng is not None,
        args.bedrooms is not None, args.price is not None,
        args.property_type, args.radius is not None,
        args.max_distance is not None, args.scan_around is not None,
        args.zip_code is not None,
        args.min_bedrooms is not None, args.max_bedrooms is not None,
        args.min_price is not None, args.max_price is not None,
        args.filter_types, args.min_rating, args.min_reviews is not None,
    ]):
        # Interactive: pre-fill with existing values
        print(f"\n  Editing '{area.get('name')}' — press Enter to keep current values:\n")
        updated = interactive_area(existing=area)
        areas[idx] = updated
    else:
        # Patch specific fields
        if args.location:
            area["location"] = args.location
        if args.radius is not None:
            area["radius_km"] = args.radius
        if args.max_distance is not None:
            area["max_competitor_distance_km"] = args.max_distance
        if args.scan_around is not None:
            area["scan_around_property"] = args.scan_around
        if args.zip_code is not None:
            if args.zip_code:
                area["zip_code"] = args.zip_code
            elif "zip_code" in area:
                del area["zip_code"]  # --zip-code "" clears it

        profile = area.setdefault("property_profile", {})
        if args.lat is not None:
            profile["lat"] = args.lat
        if args.lng is not None:
            profile["lng"] = args.lng
        if args.bedrooms is not None:
            profile["bedrooms"] = args.bedrooms
        if args.price is not None:
            profile["price"] = args.price
        if args.property_type:
            profile["property_type"] = args.property_type

        cf = area.setdefault("competitor_filters", {})
        if args.min_bedrooms is not None:
            cf["min_bedrooms"] = args.min_bedrooms
        if args.max_bedrooms is not None:
            cf["max_bedrooms"] = args.max_bedrooms
        if args.min_price is not None:
            cf["target_price_min"] = args.min_price
        if args.max_price is not None:
            cf["target_price_max"] = args.max_price
        if args.filter_types:
            cf["property_types"] = args.filter_types
        if args.min_rating:
            cf["min_rating"] = args.min_rating
        if args.min_reviews is not None:
            cf["min_reviews"] = args.min_reviews

    config["search_areas"] = areas
    save_config(config)

    print(f"\n  ✓ Updated property '{area.get('name')}'")
    print_area(area, idx, verbose=True)


def cmd_remove(args):
    config = load_config()
    areas = get_areas(config)
    if not areas:
        print("\n  No properties to remove.")
        return

    area = find_area(areas, index=args.index, name=args.name or "")
    if not area:
        return

    idx = args.index if args.index is not None else next(
        i for i, a in enumerate(areas) if a is area
    )

    name = area.get("name", f"index {idx}")

    if not args.force:
        confirm = input(f"  Remove '{name}'? (y/N): ").strip().lower()
        if confirm != "y":
            print("  Cancelled.")
            return

    areas.pop(idx)
    config["search_areas"] = areas
    save_config(config)
    print(f"\n  ✓ Removed '{name}'")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Manage properties (search areas) for Airbnb AI Agent.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # list
    p_list = sub.add_parser("list", help="List all properties (short format)")

    # view
    p_view = sub.add_parser("view", help="View property details (verbose)")
    p_view.add_argument("-i", "--index", type=int, default=None,
                        help="Property index (0-based)")
    p_view.add_argument("-n", "--name", type=str, default="",
                        help="Property name")

    # add
    p_add = sub.add_parser("add", help="Add a new property")
    p_add.add_argument("--interactive", action="store_true",
                       help="Prompt for each field (default if no flags given)")
    p_add.add_argument("--name", type=str, default="")
    p_add.add_argument("--location", type=str, default="")
    p_add.add_argument("--lat", type=float, default=None)
    p_add.add_argument("--lng", type=float, default=None)
    p_add.add_argument("--bedrooms", type=int, default=None)
    p_add.add_argument("--price", type=float, default=None)
    p_add.add_argument("--property-type", type=str, default="")
    p_add.add_argument("--radius", type=float, default=5)
    p_add.add_argument("--max-distance", type=float, default=15)
    p_add.add_argument("--scan-around", action="store_true", default=False,
                       help="Generate search bbox from property lat/lng + radius")
    p_add.add_argument("--no-scan-around", dest="scan_around", action="store_false",
                       help="Disable scan-around-property (use city bbox instead)")
    p_add.add_argument("--zip-code", type=str, default="",
                       help="Zip code for search area (geocoded to lat/lng at search time)")
    # Filters
    p_add.add_argument("--min-bedrooms", type=int, default=None)
    p_add.add_argument("--max-bedrooms", type=int, default=None)
    p_add.add_argument("--min-price", type=float, default=None)
    p_add.add_argument("--max-price", type=float, default=None)
    p_add.add_argument("--filter-types", type=str, nargs="*", default=None,
                       help="Property type filters (space-separated)")
    p_add.add_argument("--min-rating", type=float, default=None)
    p_add.add_argument("--min-reviews", type=int, default=None)

    # edit
    p_edit = sub.add_parser("edit", help="Edit an existing property")
    p_edit.add_argument("-i", "--index", type=int, default=None)
    p_edit.add_argument("-n", "--name", type=str, default="")
    p_edit.add_argument("--interactive", action="store_true",
                       help="Full interactive edit (default if no fields given)")
    # All the same fields as add
    p_edit.add_argument("--location", type=str, default="")
    p_edit.add_argument("--lat", type=float, default=None)
    p_edit.add_argument("--lng", type=float, default=None)
    p_edit.add_argument("--bedrooms", type=int, default=None)
    p_edit.add_argument("--price", type=float, default=None)
    p_edit.add_argument("--property-type", type=str, default="")
    p_edit.add_argument("--radius", type=float, default=None)
    p_edit.add_argument("--max-distance", type=float, default=None)
    p_edit.add_argument("--scan-around", action="store_true", default=None,
                       help="Enable scan-around-property")
    p_edit.add_argument("--no-scan-around", dest="scan_around", action="store_false",
                       default=None, help="Disable scan-around-property")
    p_edit.add_argument("--zip-code", type=str, default=None,
                       help="Set zip code for geocoded bbox (pass empty string to clear)")
    p_edit.add_argument("--min-bedrooms", type=int, default=None)
    p_edit.add_argument("--max-bedrooms", type=int, default=None)
    p_edit.add_argument("--min-price", type=float, default=None)
    p_edit.add_argument("--max-price", type=float, default=None)
    p_edit.add_argument("--filter-types", type=str, nargs="*", default=None)
    p_edit.add_argument("--min-rating", type=float, default=None)
    p_edit.add_argument("--min-reviews", type=int, default=None)

    # remove
    p_remove = sub.add_parser("remove", help="Remove a property")
    p_remove.add_argument("-i", "--index", type=int, default=None)
    p_remove.add_argument("-n", "--name", type=str, default="")
    p_remove.add_argument("--force", "-f", action="store_true",
                          help="Skip confirmation")

    args = parser.parse_args()

    if args.command == "list":
        cmd_list(args)
    elif args.command == "view":
        cmd_view(args)
    elif args.command == "add":
        cmd_add(args)
    elif args.command == "edit":
        cmd_edit(args)
    elif args.command == "remove":
        cmd_remove(args)


if __name__ == "__main__":
    main()
