"""
Airbnb Scraper - Competitor listing data collection.

Uses the pyairbnb library to search and extract competitor listings.
"""

import asyncio
import json
import logging
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pyairbnb

logger = logging.getLogger(__name__)


def strip_html(text: str) -> str:
    """Remove HTML tags and normalize whitespace."""
    if not text:
        return ""
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    text = text.replace('&nbsp;', ' ').replace('&#39;', "'").replace('&quot;', '"')
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


@dataclass
class DiscountItem:
    """A single discount applied to a listing."""
    type: str = ""             # e.g. "Last-minute discount", "Special offer", "Long stay discount"
    amount: float = 0.0        # Total $ amount for the stay (positive)
    per_night: float = 0.0     # Per-night $ amount


@dataclass
class Listing:
    """Represents a single Airbnb listing."""
    listing_id: str = ""
    title: str = ""
    price: float = 0.0           # Effective nightly price (post-discount)
    original_price: float = 0.0  # Pre-discount nightly price (== price when no discount)
    discount_amount: float = 0.0 # Total discount for the stay ($)
    discount_pct: float = 0.0    # Discount as % of original (0.0 if none)
    discount_types: list[str] = field(default_factory=list)  # e.g. ["Last-minute discount", "Special offer"]
    discounts: list[DiscountItem] = field(default_factory=list)  # Detailed breakdown
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
    # Extended fields from get_details()
    description: str = ""
    is_guest_favorite: bool = False
    is_super_host: bool = False
    home_tier: int = 0
    amenities: list[str] = field(default_factory=list)
    house_rules: str = ""
    location_description: str = ""
    detail_raw: dict = field(default_factory=dict)
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

        # Dedup across search pages/tiles — the same listing often appears
        # on multiple pages of the same search. Count each property once.
        seen: set[str] = set()
        deduped: list[Listing] = []
        for listing in all_listings:
            key = listing.listing_id or listing.url or listing.title
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(listing)
        if len(deduped) != len(all_listings):
            logger.info(
                f"Deduped {len(all_listings) - len(deduped)} repeat listings "
                f"({len(all_listings)} → {len(deduped)})"
            )

        logger.info(f"Total competitor listings across all areas: {len(deduped)}")
        return deduped

    async def search_adhoc(
        self,
        location: str = "",
        zip_code: str = "",
        label: str = "",
        checkin: str = "",
        checkout: str = "",
        adults: int = 2,
        radius_km: float = 5.0,
        store_temp: bool = True,
        detail: str = "full",
        max_concurrent: int = 5,
    ) -> list[Listing]:
        """
        Run a one-off search and optionally store results in temp_scrapes.db.

        Args:
            location: Location string (e.g. "Austin, TX")
            zip_code: Zip code to geocode and search around (overrides bbox)
            label: Label for this scrape in temp storage (default: zip or location)
            checkin / checkout: Dates (default: next Fri–Sat)
            adults: Number of guests
            radius_km: Search radius for zip/scan-around bbox
            store_temp: If True, save to data/temp_scrapes.db
            detail: "full" (default) fetches full details per listing (slower,
                complete data). "basic" skips enrichment (fast, search-only data).
            max_concurrent: Max concurrent detail requests when detail="full"

        Returns:
            List of Listing objects (also stored in temp DB)
        """
        from datetime import date, timedelta

        if not checkin:
            today = date.today()
            days_until_friday = (4 - today.weekday()) % 7 or 7
            checkin = (today + timedelta(days=days_until_friday)).isoformat()
            checkout = (today + timedelta(days=days_until_friday + 1)).isoformat()

        # Build ad-hoc area
        area: dict = {"location": location or "", "radius_km": radius_km}
        if zip_code:
            area["zip_code"] = zip_code
            area["name"] = zip_code
        else:
            area["name"] = location

        label = label or zip_code or location or "adhoc"

        logger.info(f"Ad-hoc search: label='{label}', zip={zip_code!r}, location={location!r}")

        try:
            raw_results = await asyncio.to_thread(
                self._pyairbnb_search, area, checkin, checkout, adults
            )
            listings = [self._parse_result(r) for r in raw_results]
            listings = [l for l in listings if l is not None]
            logger.info(f"  [{label}] {len(listings)} listings found")
        except Exception as e:
            logger.error(f"  [{label}] Search failed: {e}")
            listings = []

        # Enrich with full details (concurrent, rate-limited)
        if detail == "full" and listings:
            listings = await self._enrich_listings(listings, max_concurrent=max_concurrent)
        elif detail == "basic":
            logger.info(f"  Basic mode — skipping detail enrichment ({len(listings)} listings)")

        # Store in temp DB
        if store_temp and listings:
            from data.storage import store_temp_listings
            scrape_id = store_temp_listings(
                listings,
                label=label,
                query_params={
                    "location": location,
                    "zip_code": zip_code,
                    "checkin": checkin,
                    "checkout": checkout,
                    "adults": adults,
                    "radius_km": radius_km,
                    "detail": detail,
                },
            )
            logger.info(f"  Stored as temp scrape '{scrape_id}' (label: '{label}')")

        return listings

    async def _enrich_listings(
        self,
        listings: list[Listing],
        max_concurrent: int = 5,
    ) -> list[Listing]:
        """
        Fetch full details for each listing concurrently and merge.

        Uses a semaphore to limit concurrency and a small delay between
        batches to avoid rate limiting.
        """
        semaphore = asyncio.Semaphore(max_concurrent)
        total = len(listings)
        enriched: list[Listing] = []

        async def enrich_one(idx: int, listing: Listing) -> Listing:
            async with semaphore:
                logger.info(f"  Enriching {idx+1}/{total}: {listing.listing_id}")
                detail = await self.get_listing_details(listing.listing_id)
                if detail:
                    return self._merge_listing(listing, detail)
                return listing

        tasks = [enrich_one(i, l) for i, l in enumerate(listings)]
        enriched = await asyncio.gather(*tasks, return_exceptions=False)

        success = sum(1 for e in enriched if e.description or e.detail_raw)
        logger.info(f"  Enriched {success}/{total} listings with full details")
        return enriched

    @staticmethod
    def _merge_listing(search: Listing, detail: Listing) -> Listing:
        """
        Merge search results with detail results.

        Search has: price, discounts, bedrooms (sometimes), badges, neighborhood.
        Detail has: description, amenities, house_rules, is_super_host, etc.
        Take the best of each; don't overwrite non-zero search values with zero detail values.
        """
        merged = Listing(
            listing_id=search.listing_id,
            title=search.title or detail.title,
            price=search.price,
            original_price=search.original_price,
            discount_amount=search.discount_amount,
            discount_pct=search.discount_pct,
            discount_types=search.discount_types,
            discounts=search.discounts,
            nights=search.nights,
            currency=search.currency,
            rating=search.rating if search.rating else detail.rating,
            reviews=max(search.reviews, detail.reviews),
            property_type=search.property_type or detail.property_type,
            bedrooms=search.bedrooms,
            bathrooms=search.bathrooms,
            guests=detail.guests or search.guests,
            neighborhood=search.neighborhood,
            url=search.url,
            available=search.available,
            lat=search.lat or detail.lat,
            lng=search.lng or detail.lng,
            badges=search.badges,
            description=detail.description,
            is_guest_favorite=detail.is_guest_favorite,
            is_super_host=detail.is_super_host,
            home_tier=detail.home_tier,
            amenities=detail.amenities,
            house_rules=detail.house_rules,
            location_description=detail.location_description,
            detail_raw=detail.detail_raw,
            raw=search.raw,
        )
        return merged

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

        Priority:
          1. Explicit bbox in config
          2. zip_code: geocode to lat/lng, then bbox_from_center
          3. scan_around_property: generate from property lat/lng + radius_km
          4. Known location lookup (DEFAULT_BBOXES)
          5. Default (Austin)
        """
        # 1. Explicit bbox in config
        if "bbox" in area:
            return tuple(area["bbox"])  # type: ignore

        radius = area.get("radius_km", 5)

        # 2. Zip code geocoding
        zip_code = area.get("zip_code")
        if zip_code:
            coords = self._geocode_zip(zip_code)
            if coords:
                lat, lng = coords
                bbox = self._bbox_from_center(lat, lng, radius)
                logger.info(
                    f"  Zip code {zip_code}: center=({lat}, {lng}) "
                    f"radius={radius}km → bbox={bbox}"
                )
                return bbox
            else:
                logger.warning(
                    f"  Could not geocode zip_code '{zip_code}' — falling back"
                )

        # 3. Scan around property center
        if area.get("scan_around_property"):
            profile = area.get("property_profile", {})
            lat = profile.get("lat")
            lng = profile.get("lng")
            if lat is not None and lng is not None:
                bbox = self._bbox_from_center(lat, lng, radius)
                logger.info(
                    f"  Scan-around-property: center=({lat}, {lng}) "
                    f"radius={radius}km → bbox={bbox}"
                )
                return bbox
            else:
                logger.warning(
                    "  scan_around_property is true but property_profile "
                    "lat/lng missing — falling back"
                )

        # 4. Known locations
        loc_lower = location.lower()
        for key, bbox in DEFAULT_BBOXES.items():
            if key in loc_lower:
                return bbox

        # 5. Default: Austin (project base)
        logger.warning(
            f"No bbox found for '{location}', using Austin defaults. "
            "Add a 'bbox' field, 'zip_code', or enable 'scan_around_property'."
        )
        return DEFAULT_BBOXES["austin"]

    @staticmethod
    def _geocode_zip(zip_code: str) -> Optional[tuple[float, float]]:
        """
        Geocode a US zip code to (lat, lng) using geopy Nominatim.

        Returns None if geocoding fails.
        """
        from geopy.geocoders import Nominatim

        try:
            geolocator = Nominatim(user_agent="airbnb-ai-agent")
            query = f"{zip_code}, USA"
            location_obj = geolocator.geocode(query, exactly_one=True, timeout=10)
            if location_obj:
                return (location_obj.latitude, location_obj.longitude)
            logger.warning(f"  Geocoder returned no result for zip '{zip_code}'")
            return None
        except Exception as e:
            logger.warning(f"  Zip geocoding failed for '{zip_code}': {e}")
            return None

    @staticmethod
    def _bbox_from_center(
        lat: float, lng: float, radius_km: float
    ) -> tuple[float, float, float, float]:
        """
        Compute a bounding box from a center point and radius in km.

        Uses simple spherical approximation:
          - 1° latitude ≈ 111.0 km
          - 1° longitude ≈ 111.32 × cos(lat) km

        Returns (sw_lat, sw_lng, ne_lat, ne_lng).
        """
        lat_offset = radius_km / 111.0
        lng_offset = radius_km / (111.32 * math.cos(math.radians(lat)))

        sw_lat = round(lat - lat_offset, 6)
        ne_lat = round(lat + lat_offset, 6)
        sw_lng = round(lng - lng_offset, 6)
        ne_lng = round(lng + lng_offset, 6)

        return (sw_lat, sw_lng, ne_lat, ne_lng)

    def _extract_nightly_price(self, price_data: dict) -> tuple[float, float, int]:
        """
        Extract the per-night price, original price, and nights count.

        pyairbnb returns price in these places:
          1. price.unit.amount — the listed (original) nightly price
          2. price.unit.discount — the discounted nightly price (when a discount exists)
          3. price.break_down[0] — 'N nights x $X.XX' where $X.XX is per-night

        Returns (effective_price, original_price, nights).
        effective_price is post-discount; original_price is pre-discount.
        Both are 0.0 if undeterminable.
        """
        unit = price_data.get("unit", {})
        unit_amount = unit.get("amount")
        unit_discount = unit.get("discount")
        qualifier = unit.get("qualifier", "")

        nights = 1
        if qualifier:
            m = re.search(r'(\d+)\s+night', qualifier)
            if m:
                nights = int(m.group(1))

        original_price = 0.0
        effective_price = 0.0

        if unit_amount is not None and unit_amount > 0:
            # If unit.discount exists, that's the effective price
            if unit_discount is not None and unit_discount > 0:
                effective_price = float(unit_discount)
                # unit.amount for multi-night is sometimes the total,
                # so we'll let break_down override if it has a per-night rate
                if nights <= 1:
                    original_price = float(unit_amount)
                else:
                    # Multi-night: unit.amount might be total, defer to break_down
                    original_price = round(float(unit_amount) / nights, 2)
            else:
                if nights <= 1:
                    original_price = float(unit_amount)
                else:
                    # Multi-night: derive per-night from total
                    original_price = round(float(unit_amount) / nights, 2)
                effective_price = original_price

        # Try break_down for per-night rate (more precise for multi-night)
        break_down = price_data.get("break_down", [])
        if break_down:
            for item in break_down:
                desc = item.get("description", "")
                m = re.match(r'(\d+)\s+night[s]?\s*x\s*\$?([\d,]+\.\d+)', desc)
                if m:
                    nights_bd = int(m.group(1))
                    per_night = float(m.group(2).replace(",", ""))
                    if nights_bd > 0 and per_night > 0:
                        # break_down per-night rate is the pre-discount rate
                        original_price = per_night
                        nights = nights_bd
                        if effective_price == 0.0 or effective_price >= original_price:
                            if unit_discount is None:
                                effective_price = per_night
                    break

        # Fallback: if we still don't have a price, try unit total / nights
        if original_price == 0.0 and unit_amount is not None and unit_amount > 0 and nights > 1:
            original_price = round(float(unit_amount) / nights, 2)
            effective_price = original_price

        if effective_price == 0.0 and original_price > 0:
            effective_price = original_price

        return round(effective_price, 2), round(original_price, 2), nights

    def _parse_discounts(
        self, raw: dict, effective_price: float, original_price: float, nights: int
    ) -> tuple[list[DiscountItem], float, float, float]:
        """
        Parse all discount data from a raw pyairbnb listing.

        Discounts come from three sources:
          1. price.break_down[] — line items with negative amounts and descriptions
             like "Last-minute discount", "Special offer", "Long stay discount"
          2. price.unit.discount — the effective price when a discount is applied
          3. long_stay_discount — top-level field for multi-night stays
             {"amount": -272.0, "currency_symbol": "$.80"}

        Returns (discounts, combined_discount_amount, combined_discount_pct, combined_original).
        - discounts: list of DiscountItem with type, amount, per_night
        - combined_discount_amount: total $ discount for the stay
        - combined_discount_pct: total discount as % of original
        - combined_original: pre-discount nightly price
        """
        discounts: list[DiscountItem] = []
        seen_types: set[str] = set()

        # ── Source 1: break_down line items ──
        break_down = raw.get("price", {}).get("break_down", [])
        for item in break_down:
            desc = item.get("description", "")
            amount = item.get("amount", 0)

            if amount is None or amount >= 0:
                continue

            # Normalize the discount type label
            dtype = self._normalize_discount_type(desc)
            if not dtype or dtype in seen_types:
                continue

            discount_amt = abs(float(amount))
            per_night = round(discount_amt / nights, 2) if nights > 0 else discount_amt

            discounts.append(DiscountItem(
                type=dtype,
                amount=round(discount_amt, 2),
                per_night=per_night,
            ))
            seen_types.add(dtype)

        # ── Source 2: unit.discount (price difference between amount and discount) ──
        unit = raw.get("price", {}).get("unit", {})
        unit_amount = unit.get("amount")
        unit_discount = unit.get("discount")

        if (
            unit_amount is not None
            and unit_discount is not None
            and float(unit_amount) > float(unit_discount) > 0
        ):
            # If we already captured this via break_down, the amounts should match
            per_night_diff = float(unit_amount) - float(unit_discount)
            total_diff = round(per_night_diff * nights, 2)

            # Check if a break_down discount already accounts for this
            already_captured = any(
                abs(d.per_night - per_night_diff) < 0.50 for d in discounts
            )

            if not already_captured:
                dtype = "Price discount"
                if dtype not in seen_types:
                    discounts.append(DiscountItem(
                        type=dtype,
                        amount=total_diff,
                        per_night=round(per_night_diff, 2),
                    ))
                    seen_types.add(dtype)

        # ── Source 3: long_stay_discount (top-level) ──
        lsd = raw.get("long_stay_discount", {})
        if lsd and isinstance(lsd, dict):
            raw_amount = lsd.get("amount", 0)
            if raw_amount and float(raw_amount) < 0:
                dtype = "Long stay discount"
                if dtype not in seen_types:
                    discount_amt = abs(float(raw_amount))
                    per_night = round(discount_amt / nights, 2) if nights > 0 else discount_amt
                    discounts.append(DiscountItem(
                        type=dtype,
                        amount=round(discount_amt, 2),
                        per_night=per_night,
                    ))
                    seen_types.add(dtype)

        # ── Compute combined stats ──
        if discounts:
            total_discount = sum(d.amount for d in discounts)
            total_per_night = sum(d.per_night for d in discounts)

            # Determine the effective original price
            if original_price > effective_price:
                combined_original = original_price
            else:
                combined_original = effective_price + total_per_night

            if combined_original > 0:
                combined_pct = round((total_per_night / combined_original) * 100, 1)
            else:
                combined_pct = 0.0

            return (
                discounts,
                round(total_discount, 2),
                combined_pct,
                round(combined_original, 2),
            )

        # No discounts found
        return [], 0.0, 0.0, effective_price

    # Discount type labels that appear in Airbnb break_down descriptions
    DISCOUNT_LABELS = {
        "last-minute": "Last-minute discount",
        "last minute": "Last-minute discount",
        "special offer": "Special offer",
        "special": "Special offer",
        "long stay": "Long stay discount",
        "long-stay": "Long stay discount",
        "early bird": "Early booking discount",
        "early booking": "Early booking discount",
        "weekly": "Weekly discount",
        "monthly": "Monthly discount",
        "new listing": "New listing discount",
        "flash": "Flash sale",
    }

    def _normalize_discount_type(self, desc: str) -> str:
        """Normalize a break_down description into a standard discount type label."""
        desc_lower = desc.lower().strip()
        for key, label in self.DISCOUNT_LABELS.items():
            if key in desc_lower:
                return label
        # If it contains 'discount' or 'off' but isn't recognized, use as-is
        if "discount" in desc_lower or "off" in desc_lower:
            return desc.strip()
        return ""

    def _parse_result(self, raw: dict) -> Optional[Listing]:
        """Map a raw pyairbnb result dict to a Listing object."""
        try:
            room_id = str(raw.get("room_id", ""))

            # Price: extract per-night effective + original price and nights
            effective_price, original_price, nights = self._extract_nightly_price(
                raw.get("price", {})
            )

            # Discounts: capture all types (break_down, unit.discount, long_stay)
            discounts, discount_amount, discount_pct, combined_original = (
                self._parse_discounts(raw, effective_price, original_price, nights)
            )

            # Use combined original if we found discounts
            if discounts:
                original_price = combined_original

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
                price=effective_price,
                original_price=original_price,
                discount_amount=discount_amount,
                discount_pct=discount_pct,
                discount_types=[d.type for d in discounts],
                discounts=discounts,
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
            # Rating block
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
            if not title:
                # get_details title is often in raw['title'] as list
                raw_title = raw.get("title")
                if isinstance(raw_title, list):
                    title = " ".join(
                        seg.get("text", "") if isinstance(seg, dict) else str(seg)
                        for seg in raw_title
                    ).strip()
                elif isinstance(raw_title, str):
                    title = raw_title

            # Description
            description = strip_html(raw.get("description", "") or "")

            # Booleans / tier
            is_guest_favorite = bool(raw.get("is_guest_favorite", False))
            is_super_host = bool(raw.get("is_super_host", False))
            home_tier = int(raw.get("home_tier", 0) or 0)

            # Amenities
            amenities_raw = raw.get("amenities", [])
            if isinstance(amenities_raw, list):
                amenities = []
                for a in amenities_raw:
                    if isinstance(a, str):
                        amenities.append(a)
                    elif isinstance(a, dict):
                        amenities.append(a.get("title", a.get("name", str(a))))
            else:
                amenities = []

            # House rules
            house_rules_raw = raw.get("house_rules", {})
            if isinstance(house_rules_raw, dict):
                parts = [house_rules_raw.get("aditional", "")]
                for rule in house_rules_raw.get("rules", []):
                    if isinstance(rule, dict):
                        parts.append(rule.get("title", ""))
                    elif isinstance(rule, str):
                        parts.append(rule)
                house_rules = strip_html(" \n".join(p for p in parts if p).strip())
            else:
                house_rules = strip_html(str(house_rules_raw or ""))

            # Location description
            loc_desc_raw = raw.get("location_descriptions", [])
            if isinstance(loc_desc_raw, list):
                location_description = strip_html(" \n".join(
                    item.get("content", "")
                    for item in loc_desc_raw
                    if isinstance(item, dict)
                ).strip())
            else:
                location_description = ""

            return Listing(
                listing_id=listing_id,
                title=title,
                price=0.0,
                currency="USD",
                rating=rating,
                reviews=reviews,
                property_type=raw.get("room_type", ""),
                guests=int(raw.get("person_capacity", 0) or 0),
                url=f"https://www.airbnb.com/rooms/{listing_id}",
                lat=lat,
                lng=lng,
                description=description,
                is_guest_favorite=is_guest_favorite,
                is_super_host=is_super_host,
                home_tier=home_tier,
                amenities=amenities,
                house_rules=house_rules,
                location_description=location_description,
                detail_raw=raw,
            )
        except Exception as e:
            logger.warning(f"Failed to parse details for {listing_id}: {e}")
            return None
