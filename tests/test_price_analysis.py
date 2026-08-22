"""Tests for the price analysis module."""

from market_agent.competitor_scorer import PropertyProfile, ScoredListing
from market_agent.scraper import Listing
from market_agent.price_analysis import PriceAnalyzer, MarketStats


def _comp(price: float, rating: float | None = None, discount: float = 0.0,
          available: bool = True) -> ScoredListing:
    """Helper: a scored comp at the given price."""
    return ScoredListing(
        listing=Listing(
            listing_id=f"p{price}", title="Comp", price=price,
            rating=rating, bedrooms=4, available=available,
            discount_amount=discount,
        ),
        total_score=0.8,
    )


def _profile(**kwargs) -> PropertyProfile:
    defaults = dict(lat=32.99, lng=-96.74, bedrooms=4, price=250,
                    property_type="Home")
    defaults.update(kwargs)
    return PropertyProfile(**defaults)


def test_analyze_empty_listings():
    analyzer = PriceAnalyzer()
    result = analyzer.analyze([])
    assert result["stats"].count == 0
    assert result["recommendations"] == []


def test_analyze_basic():
    listings = [
        Listing(listing_id="1", price=100.0, rating=4.5, reviews=10, bedrooms=1),
        Listing(listing_id="2", price=150.0, rating=4.8, reviews=20, bedrooms=2),
        Listing(listing_id="3", price=200.0, rating=4.0, reviews=5, bedrooms=2),
    ]
    analyzer = PriceAnalyzer()
    result = analyzer.analyze(listings)

    stats = result["stats"]
    assert stats.count == 3
    assert stats.min_price == 100.0
    assert stats.max_price == 200.0
    assert 1 in stats.by_bedrooms
    assert 2 in stats.by_bedrooms


def test_analyze_discount_stats():
    """Discount stats should be computed when listings have discounts."""
    listings = [
        Listing(
            listing_id="1", price=90.0, original_price=100.0,
            discount_amount=30.0, discount_pct=10.0, nights=3,
            bedrooms=1,
        ),
        Listing(
            listing_id="2", price=180.0, original_price=200.0,
            discount_amount=60.0, discount_pct=10.0, nights=3,
            bedrooms=2,
        ),
        Listing(listing_id="3", price=150.0, original_price=150.0, bedrooms=2),
    ]
    analyzer = PriceAnalyzer()
    result = analyzer.analyze(listings)

    stats = result["stats"]
    assert stats.discounted_count == 2
    assert stats.avg_discount_pct == 10.0
    assert stats.avg_discount_amount == 45.0  # (30+60)/2

    trends = result["trends"]
    assert trends["discounted_listings"] == 2
    assert trends["avg_discount_pct"] == 10.0


def test_analyze_no_discounts():
    """No discounts should yield zero discount stats."""
    listings = [
        Listing(listing_id="1", price=100.0, bedrooms=1),
        Listing(listing_id="2", price=200.0, bedrooms=2),
    ]
    analyzer = PriceAnalyzer()
    result = analyzer.analyze(listings)

    stats = result["stats"]
    assert stats.discounted_count == 0
    assert stats.avg_discount_pct == 0.0
    trends = result["trends"]
    assert trends["discounted_listings"] == 0


# ----------------------------------------------------------------------
# Pricing recommendations
# ----------------------------------------------------------------------


def test_recommend_skips_tiny_comp_set():
    """Fewer than 4 priced comps → no recommendation."""
    analyzer = PriceAnalyzer()
    assert analyzer.recommend(_profile(), [_comp(200), _comp(210)]) is None


def test_recommend_anchors_to_comp_median():
    """Neutral profile → suggestion should equal the comp median (IQR-clamped, $5-rounded)."""
    # 20 comps, median 400 — well outside profile price, no quality signals
    prices = [300, 320, 340, 360, 380, 390, 395, 400, 400, 400,
              400, 400, 405, 410, 420, 440, 460, 480, 500, 520]
    scored = [_comp(p, rating=4.5) for p in prices]

    analyzer = PriceAnalyzer()
    rec = analyzer.recommend(_profile(rating=4.5), scored)

    assert rec is not None
    assert rec.current_price == 250
    # Neutral multipliers → suggestion == median effective price
    assert rec.suggested_price == 400
    assert 0.0 < rec.confidence <= 0.85
    assert "median effective $400" in rec.reasoning
    assert "+60%" in rec.reasoning  # 250 → 400


def test_recommend_quality_boost():
    """Higher rating + badges should push the suggestion above the median (within IQR)."""
    prices = [300, 320, 340, 360, 380, 390, 395, 400, 400, 400,
              400, 400, 405, 410, 420, 440, 460, 480, 500, 520]
    scored = [_comp(p, rating=4.5) for p in prices]
    strong = _profile(rating=4.9, is_guest_favorite=True, is_superhost=True)

    analyzer = PriceAnalyzer()
    rec = analyzer.recommend(strong, scored)

    assert rec.suggested_price > 400  # quality lift
    assert rec.suggested_price % 5 == 0  # $5 steps
    # IQR clamp: must not exceed p75 of comp prices
    assert rec.suggested_price <= 460


def test_recommend_soft_demand_discounts():
    """Heavy comp discounting should lean the suggestion below the median."""
    prices = [300, 320, 340, 360, 380, 390, 395, 400, 400, 400,
              400, 400, 405, 410, 420, 440, 460, 480, 500, 520]
    scored = [
        _comp(p, rating=4.5, discount=50.0 if i < 12 else 0.0)  # 60% discounting
        for i, p in enumerate(prices)
    ]

    analyzer = PriceAnalyzer()
    rec = analyzer.recommend(_profile(rating=4.5), scored)

    assert rec.suggested_price < 400
    assert "soft demand" in rec.reasoning


def test_recommend_uses_only_top_n_comps():
    """Comps beyond top_n must not influence the anchor."""
    close = [_comp(400, rating=4.5) for _ in range(20)]
    far = [_comp(9999) for _ in range(10)]  # would skew mean, not this median

    analyzer = PriceAnalyzer()
    rec = analyzer.recommend(_profile(rating=4.5), close + far, top_n=20)

    assert rec.suggested_price == 400
