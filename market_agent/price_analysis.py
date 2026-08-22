"""
Price Analysis - Analyzes competitor pricing data.

Computes market statistics, identifies pricing trends, and generates
recommendations.
"""

import logging
import statistics
from dataclasses import dataclass, field
from typing import Optional

from market_agent.competitor_scorer import PropertyProfile, ScoredListing
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

    #: Only the N closest competitors (by CompetitorScorer rank) set the
    #: recommended price. Non-competitors don't matter.
    COMP_SET_SIZE = 20

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

    # ------------------------------------------------------------------
    # Pricing recommendation
    # ------------------------------------------------------------------

    def recommend(
        self,
        profile: PropertyProfile,
        scored: list[ScoredListing],
        top_n: int | None = None,
    ) -> Optional[PricingRecommendation]:
        """
        Generate a pricing recommendation anchored to the closest comps.

        The comp set is the top-N ranked ScoredListings (closest first).
        The anchor is the comp-set median *effective* price (post-discount),
        adjusted by bounded quality/demand multipliers, then clamped to
        the comp-set interquartile range so no adjustment pushes the
        suggestion outside what the market bears.

        Returns None when there aren't enough priced comps (< 4).
        """
        top_n = top_n or self.COMP_SET_SIZE
        comps = [s.listing for s in scored[:top_n] if s.listing.price > 0]
        n = len(comps)

        if n < 4:
            logger.warning(
                f"Pricing recommendation skipped: only {n} priced comps "
                f"(need >= 4)"
            )
            return None

        prices = [l.price for l in comps]
        anchor = statistics.median(prices)
        p25, p75 = statistics.quantiles(prices, n=4)[0::2]
        cv = statistics.stdev(prices) / anchor if anchor > 0 else 1.0

        quality_mult, quality_notes = self._quality_multiplier(profile, comps)
        demand_mult, demand_notes = self._demand_multiplier(comps)

        suggested = anchor * quality_mult * demand_mult
        suggested = max(p25, min(p75, suggested))
        suggested = round(suggested / 5) * 5  # hosts price in $5 steps

        # Confidence: comp-set size and price dispersion
        size_factor = min(1.0, n / 15)
        disp_factor = max(0.0, 1.0 - cv / 0.5)
        confidence = round(min(0.85, 0.2 + 0.65 * size_factor * disp_factor), 2)

        parts = [
            f"Comp set: {n} closest listings, median effective "
            f"${anchor:.0f} (IQR ${p25:.0f}-${p75:.0f}, CV {cv:.2f})"
        ]
        parts += quality_notes + demand_notes

        if profile.price > 0:
            delta_pct = (suggested - profile.price) / profile.price * 100
            parts.append(
                f"Current ${profile.price:.0f} → suggested ${suggested:.0f} "
                f"({delta_pct:+.0f}%)"
            )
        else:
            parts.append(
                f"Suggested anchor price ${suggested:.0f} (no current price set)"
            )

        logger.info(
            f"Pricing recommendation: ${suggested:.0f} "
            f"(anchor ${anchor:.0f}, quality x{quality_mult:.2f}, "
            f"demand x{demand_mult:.2f}, confidence {confidence})"
        )

        return PricingRecommendation(
            current_price=profile.price,
            suggested_price=suggested,
            reasoning=". ".join(parts) + ".",
            confidence=confidence,
        )

    def _quality_multiplier(
        self, profile: PropertyProfile, comps: list[Listing]
    ) -> tuple[float, list[str]]:
        """
        Quality adjustment (0.90-1.15) vs the comp set.

        Rating difference vs comp median drives most of it; Guest Favorite
        and Superhost add small absolute premiums.
        """
        mult = 1.0
        notes: list[str] = []

        ratings = [l.rating for l in comps if l.rating is not None]
        if profile.rating and ratings:
            comp_median_rating = statistics.median(ratings)
            delta = profile.rating - comp_median_rating
            # ±0.5 rating stars ≈ ±10% price support, capped
            adj = max(-0.10, min(0.10, delta * 0.2))
            mult += adj
            if adj != 0:
                notes.append(
                    f"Your {profile.rating:.1f}★ vs comp median "
                    f"{comp_median_rating:.1f}★ → {adj:+.0%} quality adjustment"
                )

        if profile.is_guest_favorite:
            mult += 0.03
            notes.append("Guest Favorite badge → +3%")
        if profile.is_superhost:
            mult += 0.02
            notes.append("Superhost → +2%")

        mult = max(0.90, min(1.15, mult))
        if not notes:
            notes.append("No quality signals on profile → neutral (x1.00)")
        return mult, notes

    def _demand_multiplier(
        self, comps: list[Listing]
    ) -> tuple[float, list[str]]:
        """
        Soft-demand adjustment (0.90-1.10) from current comp-set signals.

        Heavy discounting among comps = soft demand → lean down.
        Low availability = comps booking up → lean up.
        """
        mult = 1.0
        notes: list[str] = []
        n = len(comps)

        disc_share = sum(1 for l in comps if l.discount_amount > 0) / n
        if disc_share > 0.5:
            mult -= 0.06
            notes.append(f"{disc_share:.0%} of comps discounting → soft demand, -6%")
        elif disc_share > 0.3:
            mult -= 0.03
            notes.append(f"{disc_share:.0%} of comps discounting → -3%")
        else:
            notes.append(f"Only {disc_share:.0%} of comps discounting → stable demand")

        avail_share = sum(1 for l in comps if l.available) / n
        if avail_share < 0.3:
            mult += 0.03
            notes.append(f"Only {avail_share:.0%} of comps still available → +3%")

        mult = max(0.90, min(1.10, mult))
        return mult, notes

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
