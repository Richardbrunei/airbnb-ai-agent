"""Tests for the price analysis module."""

from market_agent.scraper import Listing
from market_agent.price_analysis import PriceAnalyzer, MarketStats


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
