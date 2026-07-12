"""Tests for the Airbnb scraper module."""

import pytest
from market_agent.scraper import Listing, AirbnbScraper


from datetime import date, timedelta


def _next_weekend():
    """Get next Friday/Saturday for test dates."""
    today = date.today()
    days_to_friday = (4 - today.weekday()) % 7 or 7
    fri = today + timedelta(days=days_to_friday)
    sat = fri + timedelta(days=1)
    return fri.isoformat(), sat.isoformat()


@pytest.mark.asyncio
async def test_search_competitors_returns_list():
    """search_competitors should return a list of Listings."""
    scraper = AirbnbScraper()
    checkin, checkout = _next_weekend()
    results = await scraper.search_competitors(
        location="Austin, TX",
        checkin=checkin,
        checkout=checkout,
    )
    assert isinstance(results, list)
    assert len(results) > 0
    assert all(isinstance(r, Listing) for r in results)


@pytest.mark.asyncio
async def test_search_results_have_prices():
    """Most search results should have a non-zero price."""
    scraper = AirbnbScraper()
    checkin, checkout = _next_weekend()
    results = await scraper.search_competitors(
        location="Austin, TX",
        checkin=checkin,
        checkout=checkout,
    )
    priced = [l for l in results if l.price > 0]
    assert len(priced) > 0


@pytest.mark.asyncio
async def test_all_prices_are_per_night():
    """Every listing should have a per-night price > 0."""
    scraper = AirbnbScraper()
    checkin, checkout = _next_weekend()
    results = await scraper.search_competitors(
        location="Austin, TX",
        checkin=checkin,
        checkout=checkout,
    )
    assert len(results) > 0
    for l in results:
        assert l.price > 0, f"Listing {l.listing_id} ({l.title}) has no price"


@pytest.mark.asyncio
async def test_get_listing_details():
    """get_listing_details should return a Listing with key fields populated."""
    scraper = AirbnbScraper()
    listing = await scraper.get_listing_details("52773926")
    assert listing is not None
    assert listing.listing_id == "52773926"
    assert listing.property_type  # e.g. "Entire home/apt"
    assert listing.rating is not None
    assert listing.reviews > 0


def test_extract_nightly_price_unit_amount():
    """_extract_nightly_price should parse unit.amount for 1-night stays."""
    scraper = AirbnbScraper()
    price_data = {"unit": {"amount": 150.0, "qualifier": "for 1 night"}}
    price, nights = scraper._extract_nightly_price(price_data)
    assert price == 150.0
    assert nights == 1


def test_extract_nightly_price_multi_night():
    """_extract_nightly_price should derive nightly from break_down for multi-night."""
    scraper = AirbnbScraper()
    price_data = {
        "unit": {"amount": 3046.0, "qualifier": "for 6 nights"},
        "break_down": [{"description": "6 nights x $507.60", "amount": 3045.0}],
    }
    price, nights = scraper._extract_nightly_price(price_data)
    assert price == 507.6
    assert nights == 6


def test_extract_nightly_price_breakdown_only():
    """Should extract per-night rate from break_down when unit.amount is missing.
    
    Format 'N nights x $X.XX' means $X.XX is the per-night price.
    """
    scraper = AirbnbScraper()
    price_data = {
        "break_down": [{"description": "2 nights x $100.00", "amount": 200.0}],
    }
    price, nights = scraper._extract_nightly_price(price_data)
    assert price == 100.0
    assert nights == 2


def test_extract_nightly_price_no_data():
    """Should return (0.0, 1) when no price data exists."""
    scraper = AirbnbScraper()
    price, nights = scraper._extract_nightly_price({})
    assert price == 0.0
    assert nights == 1


def test_parse_discount_empty():
    """No long_stay_discount should yield zero discount."""
    scraper = AirbnbScraper()
    original, amount, pct = scraper._parse_discount({}, 100.0, 3)
    assert original == 100.0
    assert amount == 0.0
    assert pct == 0.0


def test_parse_discount_zero_amount():
    """A zero discount amount should be treated as no discount."""
    scraper = AirbnbScraper()
    raw = {"long_stay_discount": {"amount": 0}}
    original, amount, pct = scraper._parse_discount(raw, 100.0, 3)
    assert original == 100.0
    assert amount == 0.0
    assert pct == 0.0


def test_parse_discount_negative_amount():
    """A negative discount amount (pyairbnb convention) should be parsed."""
    scraper = AirbnbScraper()
    raw = {"long_stay_discount": {"amount": -272.0, "currency_symbol": "$.80"}}
    # effective price $507.60/night, 6 nights, $272 total discount
    # per-night discount = 272/6 = 45.33
    # original = 507.60 + 45.33 = 552.93
    original, amount, pct = scraper._parse_discount(raw, 507.60, 6)
    assert amount == 272.0
    assert original > 507.60
    assert pct > 0
    # ~8.2% discount
    assert 7.0 < pct < 10.0


def test_parse_result_with_discount():
    """_parse_result should populate discount fields from raw data."""
    scraper = AirbnbScraper()
    raw = {
        "room_id": 999,
        "name": "Discounted Loft",
        "title": "Apartment in Austin",
        "price": {
            "unit": {"amount": 800.0, "qualifier": "for 2 nights"},
            "break_down": [{"description": "2 nights x $400.00", "amount": 800.0}],
        },
        "long_stay_discount": {"amount": -100.0, "currency_symbol": "$.00"},
        "rating": {"value": 4.9, "reviewCount": "15"},
        "coordinates": {"latitude": 30.27, "longitude": -97.74},
        "structuredContent": {"primaryLine": [
            {"body": "1 bedroom", "type": "BEDINFO"},
            {"body": "1 bath", "type": "BATHROOMINFO"},
        ]},
    }
    listing = scraper._parse_result(raw)
    assert listing is not None
    assert listing.price == 400.0          # effective nightly from break_down
    assert listing.nights == 2
    assert listing.discount_amount == 100.0
    assert listing.original_price > 400.0  # 400 + (100/2) = 450
    assert listing.discount_pct > 0        # ~11.1%


def test_parse_result_no_discount():
    """Listing without discount should have original_price == price."""
    scraper = AirbnbScraper()
    raw = {
        "room_id": 123,
        "name": "Regular Spot",
        "title": "Home in Austin",
        "price": {"unit": {"amount": 150.0, "qualifier": "for 1 night"}},
        "rating": {"value": 4.5, "reviewCount": "10"},
    }
    listing = scraper._parse_result(raw)
    assert listing is not None
    assert listing.price == 150.0
    assert listing.original_price == 150.0
    assert listing.discount_amount == 0.0
    assert listing.discount_pct == 0.0


def test_listing_dataclass():
    listing = Listing(
        listing_id="123",
        title="Test Listing",
        price=100.0,
        rating=4.5,
        reviews=10,
    )
    assert listing.listing_id == "123"
    assert listing.price == 100.0
    assert listing.currency == "USD"
    assert listing.bedrooms == 0
    assert listing.badges == []


def test_listing_defaults():
    listing = Listing()
    assert listing.listing_id == ""
    assert listing.price == 0.0
    assert listing.rating is None
    assert listing.raw == {}


def test_parse_structured_content_studio():
    """Studio listings should parse as 0 bedrooms."""
    scraper = AirbnbScraper()
    raw = {
        "structuredContent": {
            "primaryLine": [
                {"body": "Studio", "type": "BEDINFO"},
                {"body": "1 queen bed", "type": "BEDINFO"},
                {"body": "1 bath", "type": "BATHROOMINFO"},
            ]
        }
    }
    bedrooms, bathrooms = scraper._parse_structured_content(raw)
    assert bedrooms == 0
    assert bathrooms == 1.0


def test_parse_structured_content_multi():
    """Multi-bedroom listings should parse correctly."""
    scraper = AirbnbScraper()
    raw = {
        "structuredContent": {
            "primaryLine": [
                {"body": "3 bedrooms", "type": "BEDINFO"},
                {"body": "2.5 baths", "type": "BATHROOMINFO"},
            ]
        }
    }
    bedrooms, bathrooms = scraper._parse_structured_content(raw)
    assert bedrooms == 3
    assert bathrooms == 2.5


def test_parse_structured_content_missing():
    """Missing structuredContent should return zeros."""
    scraper = AirbnbScraper()
    bedrooms, bathrooms = scraper._parse_structured_content({})
    assert bedrooms == 0
    assert bathrooms == 0.0


def test_get_bbox_known_location():
    """Known locations should return predefined bbox."""
    scraper = AirbnbScraper()
    bbox = scraper._get_bbox({}, "Austin, TX")
    assert len(bbox) == 4
    sw_lat, sw_lng, ne_lat, ne_lng = bbox
    assert sw_lat < ne_lat
    assert sw_lng < ne_lng


def test_get_bbox_from_config():
    """Explicit bbox in area config should take priority."""
    scraper = AirbnbScraper()
    custom = [10.0, -20.0, 15.0, -15.0]
    bbox = scraper._get_bbox({"bbox": custom}, "Unknown Place")
    assert bbox == tuple(custom)


def test_parse_result_full():
    """_parse_result should correctly map a raw pyairbnb result."""
    scraper = AirbnbScraper()
    raw = {
        "room_id": 12345,
        "name": "Beautiful Downtown Loft",
        "title": "Apartment in Austin · Downtown",
        "price": {"unit": {"amount": 150.0, "curency_symbol": "$"}},
        "rating": {"value": 4.8, "reviewCount": "42"},
        "coordinates": {"latitude": 30.27, "longitude": -97.74},
        "badges": ["GUEST_FAVORITE"],
        "structuredContent": {
            "primaryLine": [
                {"body": "1 bedroom", "type": "BEDINFO"},
                {"body": "1 bath", "type": "BATHROOMINFO"},
            ]
        },
    }
    listing = scraper._parse_result(raw)
    assert listing is not None
    assert listing.listing_id == "12345"
    assert listing.title == "Beautiful Downtown Loft"
    assert listing.price == 150.0
    assert listing.rating == 4.8
    assert listing.reviews == 42
    assert listing.bedrooms == 1
    assert listing.bathrooms == 1.0
    assert listing.property_type == "Apartment"
    assert listing.neighborhood == "Downtown"
    assert listing.lat == 30.27
    assert listing.lng == -97.74
    assert listing.url == "https://www.airbnb.com/rooms/12345"
    assert "GUEST_FAVORITE" in listing.badges


# --- Competitor filter tests ---

def _make_listing(**kwargs):
    """Helper to build a Listing with sensible defaults."""
    defaults = {
        "listing_id": "1",
        "price": 150.0,
        "rating": 4.5,
        "reviews": 20,
        "bedrooms": 2,
        "bathrooms": 1.0,
        "property_type": "Home",
        "neighborhood": "East Austin",
    }
    defaults.update(kwargs)
    return Listing(**defaults)


def test_filter_no_config_returns_all():
    """With no competitor_filters and no price range, return everything."""
    scraper = AirbnbScraper()
    listings = [_make_listing(price=50), _make_listing(price=500)]
    result = scraper._filter_competitors(listings, {})
    assert len(result) == 2


def test_filter_price_range_only():
    """Legacy price filter (area root) should still work without competitor_filters."""
    scraper = AirbnbScraper()
    listings = [_make_listing(price=50), _make_listing(price=150), _make_listing(price=500)]
    result = scraper._filter_competitors(listings, {"target_price_min": 100, "target_price_max": 300})
    assert len(result) == 1
    assert result[0].price == 150


def test_filter_bedrooms():
    """Bedroom range filter should narrow by min/max."""
    scraper = AirbnbScraper()
    listings = [
        _make_listing(listing_id="1", bedrooms=0),
        _make_listing(listing_id="2", bedrooms=2),
        _make_listing(listing_id="3", bedrooms=5),
    ]
    cf = {"competitor_filters": {"min_bedrooms": 1, "max_bedrooms": 3}}
    result = scraper._filter_competitors(listings, cf)
    assert len(result) == 1
    assert result[0].listing_id == "2"


def test_filter_property_types():
    """Property type filter should match by substring (case-insensitive)."""
    scraper = AirbnbScraper()
    listings = [
        _make_listing(listing_id="1", property_type="Home"),
        _make_listing(listing_id="2", property_type="Apartment"),
        _make_listing(listing_id="3", property_type="Private room"),
    ]
    cf = {"competitor_filters": {"property_types": ["home", "apartment"]}}
    result = scraper._filter_competitors(listings, cf)
    assert len(result) == 2
    assert {l.listing_id for l in result} == {"1", "2"}


def test_filter_neighborhoods():
    """Neighborhood filter should match by substring."""
    scraper = AirbnbScraper()
    listings = [
        _make_listing(listing_id="1", neighborhood="East Austin"),
        _make_listing(listing_id="2", neighborhood="Downtown"),
        _make_listing(listing_id="3", neighborhood="Zilker"),
    ]
    cf = {"competitor_filters": {"neighborhoods": ["east", "zilker"]}}
    result = scraper._filter_competitors(listings, cf)
    assert len(result) == 2
    assert {l.listing_id for l in result} == {"1", "3"}


def test_filter_min_rating():
    """Min rating filter should exclude poorly-rated listings."""
    scraper = AirbnbScraper()
    listings = [
        _make_listing(listing_id="1", rating=3.8),
        _make_listing(listing_id="2", rating=4.6),
        _make_listing(listing_id="3", rating=None),  # no rating
    ]
    cf = {"competitor_filters": {"min_rating": 4.3}}
    result = scraper._filter_competitors(listings, cf)
    assert len(result) == 1
    assert result[0].listing_id == "2"


def test_filter_min_reviews():
    """Min reviews filter should exclude new/unproven listings."""
    scraper = AirbnbScraper()
    listings = [
        _make_listing(listing_id="1", reviews=2),
        _make_listing(listing_id="2", reviews=50),
    ]
    cf = {"competitor_filters": {"min_reviews": 10}}
    result = scraper._filter_competitors(listings, cf)
    assert len(result) == 1
    assert result[0].listing_id == "2"


def test_filter_combined():
    """Multiple filters should stack (AND logic)."""
    scraper = AirbnbScraper()
    listings = [
        _make_listing(listing_id="1", price=120, bedrooms=2, rating=4.8, reviews=30, property_type="Home"),
        _make_listing(listing_id="2", price=90,  bedrooms=2, rating=4.8, reviews=30, property_type="Home"),   # too cheap
        _make_listing(listing_id="3", price=150, bedrooms=5, rating=4.8, reviews=30, property_type="Home"),   # too many BR
        _make_listing(listing_id="4", price=150, bedrooms=2, rating=4.0, reviews=30, property_type="Home"),   # low rating
        _make_listing(listing_id="5", price=150, bedrooms=2, rating=4.8, reviews=2,  property_type="Home"),    # too few reviews
        _make_listing(listing_id="6", price=150, bedrooms=2, rating=4.8, reviews=30, property_type="Private room"),  # wrong type
    ]
    cf = {
        "competitor_filters": {
            "target_price_min": 100,
            "target_price_max": 300,
            "min_bedrooms": 1,
            "max_bedrooms": 3,
            "min_rating": 4.3,
            "min_reviews": 10,
            "property_types": ["Home", "Apartment"],
        }
    }
    result = scraper._filter_competitors(listings, cf)
    assert len(result) == 1
    assert result[0].listing_id == "1"
