"""
Price Analysis - Analyzes competitor pricing data.

Computes market statistics, identifies pricing trends, and generates
recommendations.
"""

import logging
import statistics
from dataclasses import dataclass, field
from typing import Optional

from market_agent.scraper import Listing

logger = logging.getLogger(__name__)


@dataclass
class MarketStats:
    """Aggregated market statistics for a search area."""
    count: int = 0
    mean_price: float = 0.0
    median_price: float = 0.0
    min_price: float = 0.0
    max_price: float = 0.0
    stdev_price: float = 0.0
    avg_rating: Optional[float] = None
    avg_reviews: float = 0.0
    by_bedrooms: dict[int, float] = field(default_factory=dict)
    by_neighborhood: dict[str, float] = field(default_factory=dict)
    # Discount stats
    discounted_count: int = 0
    avg_discount_pct: float = 0.0
    avg_discount_amount: float = 0.0
    median_original_price: float = 0.0
    median_effective_price: float = 0.0


@dataclass
class PricingRecommendation:
    """A single pricing recommendation."""
    current_price: float
    suggested_price: float
    reasoning: str
    confidence: float = 0.0


class PriceAnalyzer:
    """Analyzes competitor pricing and generates recommendations."""

    def analyze(self, listings: list[Listing]) -> dict:
        """
        Analyze a list of competitor listings.

        Returns a dict with:
            - stats: MarketStats
            - recommendations: list[PricingRecommendation]
            - trends: dict of trend observations
        """
        if not listings:
            logger.warning("No listings to analyze")
            return {"stats": MarketStats(), "recommendations": [], "trends": {}}

        prices = [l.price for l in listings if l.price > 0]
        stats = self._compute_stats(listings, prices)
        trends = self._identify_trends(listings)

        logger.info(
            f"Analyzed {len(listings)} listings | "
            f"median: ${stats.median_price:.0f} | "
            f"range: ${stats.min_price:.0f}-${stats.max_price:.0f}"
        )

        return {
            "stats": stats,
            "recommendations": [],
            "trends": trends,
        }

    def _compute_stats(self, listings: list[Listing], prices: list[float]) -> MarketStats:
        stats = MarketStats(
            count=len(prices),
            mean_price=statistics.mean(prices),
            median_price=statistics.median(prices),
            min_price=min(prices),
            max_price=max(prices),
            stdev_price=statistics.stdev(prices) if len(prices) > 1 else 0.0,
        )

        ratings = [l.rating for l in listings if l.rating is not None]
        if ratings:
            stats.avg_rating = statistics.mean(ratings)

        reviews = [l.reviews for l in listings]
        if reviews:
            stats.avg_reviews = statistics.mean(reviews)

        # Group by bedrooms
        by_bed: dict[int, list[float]] = {}
        for l in listings:
            by_bed.setdefault(l.bedrooms, []).append(l.price)
        stats.by_bedrooms = {k: statistics.median(v) for k, v in by_bed.items()}

        # Group by neighborhood
        by_hood: dict[str, list[float]] = {}
        for l in listings:
            if l.neighborhood:
                by_hood.setdefault(l.neighborhood, []).append(l.price)
        stats.by_neighborhood = {k: statistics.median(v) for k, v in by_hood.items()}

        # Discount statistics
        discounted = [l for l in listings if l.discount_amount > 0]
        if discounted:
            stats.discounted_count = len(discounted)
            stats.avg_discount_pct = statistics.mean(l.discount_pct for l in discounted)
            stats.avg_discount_amount = statistics.mean(l.discount_amount for l in discounted)
            stats.median_original_price = statistics.median(
                l.original_price for l in discounted
            )
            stats.median_effective_price = statistics.median(
                l.price for l in discounted
            )

        return stats

    def _identify_trends(self, listings: list[Listing]) -> dict:
        """Identify market trends from listing data."""
        discounted = [l for l in listings if l.discount_amount > 0]
        return {
            "total_listings": len(listings),
            "available_count": sum(1 for l in listings if l.available),
            "highly_rated": sum(1 for l in listings if l.rating and l.rating >= 4.5),
            "discounted_listings": len(discounted),
            "avg_discount_pct": (
                round(statistics.mean(l.discount_pct for l in discounted), 1)
                if discounted else 0.0
            ),
        }
