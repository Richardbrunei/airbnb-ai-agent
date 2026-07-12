"""
Airbnb Scraper - Competitor listing data collection.

Uses the pyairbnb library to search and extract competitor listings.
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pyairbnb

logger = logging.getLogger(__name__)


@dataclass
class Listing:
    """Represents a single Airbnb listing."""
    listing_id: str = ""
    title: str = ""
    price: float = 0.0           # Effective nightly price (post-discount)
    original_price: float = 0.0  # Pre-discount nightly price (== price when no discount)
    discount_amount: float = 0.0 # Total discount for the stay ($)
    discount_pct: float = 0.0    # Discount as % of original (0.0 if none)
    nights: int = 1             # Number of nights in the search query
    currency: str = "USD"
    rating: Optional[float] = None
    reviews: int = 0
    property_type: str = ""
    bedrooms: int = 0
    bathrooms: float = 0.0
    guests: int = 0
    neighborhood: str = ""
    url: str = ""
    available: bool = True
    lat: Optional[float] = None
    lng: Optional[float] = None
    badges: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


# Default bounding boxes for known locations: (sw_lat, sw_lng, ne_lat, ne_lng)
# Used when areas.json doesn't provide coordinates.
DEFAULT_BBOXES = {
    "austin": (30.18, -97.90, 30.52, -97.65),
    "dallas": (32.70, -96.90, 32.95, -96.70),
    "houston": (29.60, -95.55, 29.90, -95.30),
    "san antonio": (29.30, -98.65, 29.65, -98.40),
}


class AirbnbScraper:
    """Scrapes Airbnb competitor listings for market monitoring."""

    def __init__(self, config_path: str = "config/areas.json"):
        self.config_path = config_path
        self.areas = self._load_areas()

    def _load_areas(self) -> list[dict]:
        """Load search area definitions from config."""
        path = Path(self.config_path)
        if not path.exists():
            logger.warning(f"Areas config not found at {path}")
            return []
        try:
            data = json.loads(path.read_text())
            areas = data.get("search_areas", [])
            logger.info(f"Loaded {len(areas)} search area(s) from config")
            return areas
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Failed to parse areas config: {e}")
            return []

    async def search_competitors(
        self,
        location: str = "",
        checkin: str = "",
        checkout: str = "",
        adults: int = 2,
    ) -> list[Listing]:
        """
        Search for competitor listings in a given area.

        Iterates over all configured search areas (or the provided location),
        queries pyairbnb, and maps results to Listing objects.

        Args:
            location: Override location (if empty, uses config/areas.json)
            checkin: Check-in date (YYYY-MM-DD). Defaults to next Friday.
            checkout: Check-out date (YYYY-MM-DD). Defaults to next Saturday.
            adults: Number of adult guests

        Returns:
            List of competitor Listing objects
        """
        from datetime import date, timedelta

        # Default to next weekend if no dates provided
        if not checkin:
            today = date.today()
            days_until_friday = (4 - today.weekday()) % 7 or 7
            checkin = (today + timedelta(days=days_until_friday)).isoformat()
            checkout = (today + timedelta(days=days_until_friday + 1)).isoformat()

        logger.info(f"Searching: checkin={checkin}, checkout={checkout}, adults={adults}")

        all_listings: list[Listing] = []

        if location:
            # Single ad-hoc search
            areas_to_search = [{"name": location, "location": location}]
        else:
            areas_to_search = self.areas

        for area in areas_to_search:
            area_name = area.get("name", area.get("location", "Unknown"))
            try:
                raw_results = await asyncio.to_thread(
                    self._pyairbnb_search, area, checkin, checkout, adults
                )
                listings = [self._parse_result(r) for r in raw_results]
                listings = [l for l in listings if l is not None]

                before = len(listings)
                listings = self._filter_competitors(listings, area)
                logger.info(
                    f"  [{area_name}] {before} → {len(listings)} listings "
                    f"after competitor filters"
                )
                all_listings.extend(listings)

            except Exception as e:
                logger.error(f"  [{area_name}] Search failed: {e}")
                continue

        logger.info(f"Total competitor listings across all areas: {len(all_listings)}")
        return all_listings

    def score_competitors(
        self, listings: list[Listing], area: dict
    ) -> "list[ScoredListing]":
        """
        Score and rank listings by similarity to the property profile.

        Requires a 'property_profile' block in the area config:
            {
              "lat": 30.27,
              "lng": -97.74,
              "bedrooms": 2,
              "price": 180,
              "property_type": "Home"
            }

        Returns ScoredListing objects sorted by total_score descending.
        """
        from market_agent.competitor_scorer import CompetitorScorer, PropertyProfile, ScoredListing

        profile_data = area.get("property_profile")
        if not profile_data:
            logger.warning("No property_profile in config — skipping scoring")
            return []

        profile = PropertyProfile(
            lat=profile_data.get("lat", 0.0),
            lng=profile_data.get("lng", 0.0),
            bedrooms=profile_data.get("bedrooms", 0),
            price=profile_data.get("price", 0.0),
            property_type=profile_data.get("property_type", ""),
        )

        max_dist = area.get("max_competitor_distance_km", 20.0)
        scorer = CompetitorScorer(profile, max_distance_km=max_dist)

        scored = scorer.score_all(listings)

        logger.info(
            f"  Scored {len(scored)} listings | "
            f"top: {scored[0].total_score:.2f} | "
            f"median: {scored[len(scored)//2].total_score:.2f}"
            if scored else "  No listings to score"
        )

        return scored

    def _pyairbnb_search(
        self, area: dict, checkin: str, checkout: str, adults: int
    ) -> list[dict]:
        """
        Call pyairbnb.search_all with bounding-box coordinates for the area.

        Runs synchronously (called via asyncio.to_thread).
        """
        location = area.get("location", "")
        bbox = self._get_bbox(area, location)

        property_types = area.get("property_types", [])
        place_type = ""
        if len(property_types) == 1:
            place_type = property_types[0]

        price_min = area.get("target_price_min", 0)
        price_max = area.get("target_price_max", 0)

        logger.info(
            f"  Searching bbox {bbox} for '{location}' "
            f"(place_type={place_type!r}, price={price_min}-{price_max})"
        )

        sw_lat, sw_lng, ne_lat, ne_lng = bbox

        results = pyairbnb.search_all(
            check_in=checkin,
            check_out=checkout,
            ne_lat=ne_lat,
            ne_long=ne_lng,
            sw_lat=sw_lat,
            sw_long=sw_lng,
            zoom_value=2,
            price_min=price_min,
            price_max=price_max,
            place_type=place_type,
            currency="USD",
            language="en",
            proxy_url="",
        )
        return results

    def _filter_competitors(self, listings: list[Listing], area: dict) -> list[Listing]:
        """
        Filter raw search results down to likely competitors.

        Uses competitor_filters from the area config. Supported keys:
          - min_bedrooms / max_bedrooms (int)
          - property_types (list[str])  — e.g. ["Entire home/apt", "Home"]
          - neighborhoods (list[str])   — case-insensitive substring match
          - min_rating (float)          — skip poorly-rated listings
          - min_reviews (int)           — skip listings with no track record
          - target_price_min / target_price_max (float) — price band

        Filters that are not present in the config are skipped.
        """
        cf = area.get("competitor_filters", {})
        if not cf:
            # No competitor filters — fall back to basic price filter only
            price_min = area.get("target_price_min", 0)
            price_max = area.get("target_price_max", 0)
            if price_max > 0:
                listings = [l for l in listings if price_min <= l.price <= price_max]
            return listings

        # Price range (can come from competitor_filters or area root)
        price_min = cf.get("target_price_min", area.get("target_price_min", 0))
        price_max = cf.get("target_price_max", area.get("target_price_max", 0))

        result = listings

        if price_max > 0:
            result = [l for l in result if price_min <= l.price <= price_max]

        # Bedrooms
        min_br = cf.get("min_bedrooms")
        max_br = cf.get("max_bedrooms")
        if min_br is not None:
            result = [l for l in result if l.bedrooms >= min_br]
        if max_br is not None:
            result = [l for l in result if l.bedrooms <= max_br]

        # Property types (case-insensitive substring match against listing.property_type)
        ptypes = cf.get("property_types")
        if ptypes:
            ptypes_lower = [p.lower() for p in ptypes]
            # Also normalize common Airbnb type names
            def matches_type(l: Listing) -> bool:
                pt = l.property_type.lower()
                # "Entire home/apt" in pyairbnb title → "Home", "Apartment", "Cabin", etc.
                # Accept if any filter token appears in the property type
                return any(t in pt for t in ptypes_lower)
            result = [l for l in result if matches_type(l)]

        # Neighborhoods (case-insensitive substring match)
        hoods = cf.get("neighborhoods")
        if hoods:
            hoods_lower = [h.lower() for h in hoods]
            result = [
                l for l in result
                if l.neighborhood and any(h in l.neighborhood.lower() for h in hoods_lower)
            ]

        # Minimum rating
        min_rating = cf.get("min_rating")
        if min_rating is not None:
            result = [l for l in result if l.rating is not None and l.rating >= min_rating]

        # Minimum review count
        min_reviews = cf.get("min_reviews")
        if min_reviews is not None:
            result = [l for l in result if l.reviews >= min_reviews]

        return result

    def _get_bbox(self, area: dict, location: str) -> tuple[float, float, float, float]:
        """
        Get bounding box as (sw_lat, sw_lng, ne_lat, ne_lng) for an area.

        Priority: explicit bbox in config > known location lookup > default.
        """
        # Check if bbox provided directly in config (expects [sw_lat, sw_lng, ne_lat, ne_lng])
        if "bbox" in area:
            return tuple(area["bbox"])  # type: ignore

        # Check known locations
        loc_lower = location.lower()
        for key, bbox in DEFAULT_BBOXES.items():
            if key in loc_lower:
                return bbox

        # Default: Austin (project base)
        logger.warning(
            f"No bbox found for '{location}', using Austin defaults. "
            "Add a 'bbox' field to areas.json to configure."
        )
        return DEFAULT_BBOXES["austin"]

    def _extract_nightly_price(self, price_data: dict) -> tuple[float, int]:
        """
        Extract the per-night price and nights count from pyairbnb price data.

        pyairbnb returns price in these places:
          1. price.unit.amount with qualifier 'for 1 night' — clean per-night
          2. price.unit.amount with qualifier 'for N nights' — TOTAL for N nights
          3. price.break_down[0] — 'N nights x $X.XX' where $X.XX is per-night

        Some listings (e.g. hotel rooms) omit unit.amount entirely but
        still include the break_down line.

        Returns (nightly_price, nights). Price is 0.0 if undeterminable.
        """
        # 1. Try price.unit.amount (most listings)
        unit = price_data.get("unit", {})
        unit_amount = unit.get("amount")
        qualifier = unit.get("qualifier", "")

        nights_from_qualifier = 1
        if qualifier:
            m = re.search(r'(\d+)\s+night', qualifier)
            if m:
                nights_from_qualifier = int(m.group(1))

        if unit_amount is not None and unit_amount > 0:
            if nights_from_qualifier <= 1:
                # Per-night price directly
                return float(unit_amount), 1
            # Multi-night: unit.amount is the total — need break_down or derive
            # Fall through to break_down first

        # 2. Parse break_down 'N nights x $X.XX' — $X.XX is the per-night rate
        break_down = price_data.get("break_down", [])
        if break_down:
            for item in break_down:
                desc = item.get("description", "")
                m = re.match(r'(\d+)\s+night[s]?\s*x\s*\$?([\d,]+\.\d+)', desc)
                if m:
                    nights = int(m.group(1))
                    per_night = float(m.group(2).replace(",", ""))
                    if nights > 0 and per_night > 0:
                        return round(per_night, 2), nights

        # 3. Fallback: derive per-night from unit total / nights
        if unit_amount is not None and unit_amount > 0 and nights_from_qualifier > 1:
            return round(float(unit_amount) / nights_from_qualifier, 2), nights_from_qualifier

        # No per-night price found
        return 0.0, 1

    def _parse_discount(
        self, raw: dict, effective_price: float, nights: int
    ) -> tuple[float, float, float]:
        """
        Parse discount data from a raw pyairbnb listing.

        pyairbnb returns long_stay_discount as:
            {"amount": -272.0, "currency_symbol": "$.80"}
        where amount is the total discount over the entire stay (negative).

        Returns (original_price, discount_amount, discount_pct):
            original_price  — pre-discount nightly rate
            discount_amount — total $ discount for the stay (positive)
            discount_pct    — discount as % of original (e.g. 10.0 = 10% off)
        """
        discount_data = raw.get("long_stay_discount", {})
        if not discount_data or not isinstance(discount_data, dict):
            return effective_price, 0.0, 0.0

        raw_amount = discount_data.get("amount", 0)
        if raw_amount is None or raw_amount == 0:
            return effective_price, 0.0, 0.0

        # pyairbnb uses negative amounts for discounts
        discount_amount = abs(float(raw_amount))
        if discount_amount <= 0 or nights <= 0:
            return effective_price, 0.0, 0.0

        per_night_discount = discount_amount / nights
        original_price = effective_price + per_night_discount

        if original_price > 0:
            discount_pct = round((per_night_discount / original_price) * 100, 1)
        else:
            discount_pct = 0.0

        return round(original_price, 2), round(discount_amount, 2), discount_pct

    def _parse_result(self, raw: dict) -> Optional[Listing]:
        """Map a raw pyairbnb result dict to a Listing object."""
        try:
            room_id = str(raw.get("room_id", ""))

            # Price: extract per-night rate and nights
            price, nights = self._extract_nightly_price(raw.get("price", {}))

            # Discount: compute original price and discount info
            original_price, discount_amount, discount_pct = self._parse_discount(
                raw, price, nights
            )

            # Rating
            rating_data = raw.get("rating", {})
            rating = float(rating_data.get("value", 0)) if rating_data.get("value") else None
            review_count = int(rating_data.get("reviewCount", 0)) if rating_data.get("reviewCount") else 0

            # Parse bedrooms/bathrooms/guests from structuredContent
            bedrooms, bathrooms = self._parse_structured_content(raw)

            # Property type from title (e.g. "Home in Austin", "Cabin in Austin")
            title = raw.get("title", "")
            property_type = title.split(" in ")[0] if " in " in title else title

            # Location
            coords = raw.get("coordinates", {})
            lat = coords.get("latitude") or coords.get("latitud")
            lng = coords.get("longitude") or coords.get("longitud") or coords.get("lng")

            # Neighborhood: try to extract from title (e.g. "Home in Austin · South Congress")
            neighborhood = ""
            if " · " in title:
                neighborhood = title.split(" · ")[-1].strip()
            elif " in " in title:
                parts = title.split(" in ")
                if len(parts) > 1:
                    neighborhood = parts[-1].strip()

            return Listing(
                listing_id=room_id,
                title=raw.get("name", ""),
                price=price,
                original_price=original_price,
                discount_amount=discount_amount,
                discount_pct=discount_pct,
                nights=nights,
                currency="USD",
                rating=rating,
                reviews=review_count,
                property_type=property_type,
                bedrooms=bedrooms,
                bathrooms=bathrooms,
                neighborhood=neighborhood,
                url=f"https://www.airbnb.com/rooms/{room_id}",
                available=True,
                lat=lat,
                lng=lng,
                badges=raw.get("badges", []),
                raw=raw,
            )
        except Exception as e:
            logger.warning(f"Failed to parse listing: {e}")
            return None

    def _parse_structured_content(self, raw: dict) -> tuple[int, float]:
        """
        Extract bedroom and bathroom counts from structuredContent.primaryLine.

        Returns (bedrooms, bathrooms).
        """
        bedrooms = 0
        bathrooms = 0.0

        primary_lines = (
            (raw.get("structuredContent") or {}).get("primaryLine") or []
        )
        for line in primary_lines:
            body = line.get("body", "")
            line_type = line.get("type", "")

            if line_type == "BEDINFO" and "bedroom" in body:
                m = re.match(r"(\d+)\s+bedroom", body)
                if m:
                    bedrooms = int(m.group(1))
                elif "studio" in body.lower():
                    bedrooms = 0

            elif line_type == "BATHROOMINFO" and "bath" in body:
                m = re.match(r"([\d.]+)\s+bath", body)
                if m:
                    bathrooms = float(m.group(1))

        return bedrooms, bathrooms

    async def get_listing_details(self, listing_id: str) -> Optional[Listing]:
        """
        Get detailed information for a specific listing.

        Uses pyairbnb.get_details() to fetch full listing data including
        amenities, description, host info, etc.
        """
        logger.info(f"Fetching details for listing {listing_id}")
        try:
            raw = await asyncio.to_thread(
                pyairbnb.get_details,
                room_id=int(listing_id),
                currency="USD",
                adults=2,
                language="en",
                proxy_url="",
            )
            if not raw:
                return None

            # Merge with existing listing or create new
            listing = self._parse_details(raw, listing_id)
            return listing

        except Exception as e:
            logger.error(f"Failed to fetch details for {listing_id}: {e}")
            return None

    def _parse_details(self, raw: dict, listing_id: str) -> Optional[Listing]:
        """Parse the detailed listing response from pyairbnb.get_details()."""
        try:
            # Rating block: { guest_satisfaction: 4.97, review_count: "344", ... }
            rating = None
            reviews = 0
            rating_info = raw.get("rating", {})
            if isinstance(rating_info, dict):
                if rating_info.get("guest_satisfaction"):
                    rating = float(rating_info["guest_satisfaction"])
                elif rating_info.get("value"):
                    rating = float(rating_info["value"])
                rc = rating_info.get("review_count", "0")
                reviews = int(rc) if rc else 0

            # Coordinates
            coords = raw.get("coordinates", {})
            lat = coords.get("latitude")
            lng = coords.get("longitude")

            # Title: can be a string or a list of rich-text fragments
            title = raw.get("name", raw.get("title", ""))
            if isinstance(title, list):
                title = " ".join(
                    seg.get("text", "") if isinstance(seg, dict) else str(seg)
                    for seg in title
                ).strip()

            return Listing(
                listing_id=listing_id,
                title=title,
                price=0.0,  # Details endpoint doesn't always include nightly price
                currency="USD",
                rating=rating,
                reviews=reviews,
                property_type=raw.get("room_type", ""),
                guests=int(raw.get("person_capacity", 0)),
                url=f"https://www.airbnb.com/rooms/{listing_id}",
                lat=lat,
                lng=lng,
                raw=raw,
            )
        except Exception as e:
            logger.warning(f"Failed to parse details for {listing_id}: {e}")
            return None
