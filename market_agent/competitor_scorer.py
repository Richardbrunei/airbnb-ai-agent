"""
Competitor Scoring - Weighted similarity scoring for competitor ranking.

Scores listings against a reference property profile. Location/proximity
carries the most weight, followed by bedroom count, price tier, and
property type.
"""

import logging
import math
from dataclasses import dataclass, field

from market_agent.scraper import Listing

logger = logging.getLogger(__name__)


@dataclass
class PropertyProfile:
    """The reference property to score competitors against."""
    lat: float = 0.0
    lng: float = 0.0
    bedrooms: int = 0
    price: float = 0.0          # Your typical nightly rate
    property_type: str = ""     # e.g. "Home", "Apartment"


@dataclass
class ScoredListing:
    """A listing with its competitor score breakdown."""
    listing: Listing
    total_score: float = 0.0
    breakdown: dict[str, float] = field(default_factory=dict)

    def __repr__(self):
        return f"ScoredListing({self.listing.title[:30]!r}, score={self.total_score:.1f})"


class CompetitorScorer:
    """
    Scores listings by how directly they compete with a reference property.

    Weights (sum to 1.0):
        location    — 0.40  (distance via haversine)
        bedrooms    — 0.25  (similarity in bedroom count)
        price       — 0.20  (similarity in nightly rate)
        prop_type   — 0.15  (exact match vs different category)

    Override weights via the constructor if needed.
    """

    def __init__(
        self,
        profile: PropertyProfile,
        weights: dict[str, float] | None = None,
        max_distance_km: float = 20.0,
    ):
        self.profile = profile
        self.max_distance_km = max_distance_km

        # Default weights — location dominates
        self.weights = {
            "location": 0.40,
            "bedrooms": 0.25,
            "price": 0.20,
            "property_type": 0.15,
        }
        if weights:
            self.weights.update(weights)

        # Normalize weights to sum to 1.0
        total = sum(self.weights.values())
        if total > 0:
            self.weights = {k: v / total for k, v in self.weights.items()}

    def score(self, listing: Listing) -> ScoredListing:
        """Score a single listing against the profile."""
        breakdown = {
            "location": self._score_location(listing) * self.weights["location"],
            "bedrooms": self._score_bedrooms(listing) * self.weights["bedrooms"],
            "price": self._score_price(listing) * self.weights["price"],
            "property_type": self._score_property_type(listing) * self.weights["property_type"],
        }
        total = sum(breakdown.values())
        return ScoredListing(listing=listing, total_score=total, breakdown=breakdown)

    def score_all(
        self, listings: list[Listing], top_n: int | None = None
    ) -> list[ScoredListing]:
        """Score and rank listings. Optionally return only top N."""
        scored = [self.score(l) for l in listings]
        scored.sort(key=lambda s: s.total_score, reverse=True)

        if top_n:
            return scored[:top_n]
        return scored

    def _score_location(self, listing: Listing) -> float:
        """
        Distance-based score (0-1).

        Uses haversine distance. 0km = 1.0 (perfect), max_distance_km = 0.0.
        Linear falloff — listings right next door dominate.
        """
        if listing.lat is None or listing.lng is None:
            # No coordinates — can't score distance, give neutral score
            return 0.5

        if self.profile.lat == 0 and self.profile.lng == 0:
            # No reference coordinates — neutral
            return 0.5

        dist = _haversine_km(
            self.profile.lat, self.profile.lng,
            listing.lat, listing.lng,
        )
        # Linear falloff: perfect at 0km, zero at max_distance_km
        score = max(0.0, 1.0 - (dist / self.max_distance_km))
        return score

    def _score_bedrooms(self, listing: Listing) -> float:
        """
        Bedroom similarity score (0-1).

        Exact match = 1.0. Score drops linearly per bedroom of difference.
        1 BR off = 0.75, 2 BR off = 0.5, etc.
        """
        if self.profile.bedrooms == 0:
            return 0.5  # No reference — neutral

        diff = abs(listing.bedrooms - self.profile.bedrooms)
        return max(0.0, 1.0 - (diff * 0.25))

    def _score_price(self, listing: Listing) -> float:
        """
        Price similarity score (0-1).

        Measures how close the listing's price is to the reference price.
        Uses ratio: if listing is within ±20% of reference, score is high.
        Falls off quickly beyond that — a $500 listing is not a direct
        competitor to a $100 property.
        """
        if self.profile.price == 0 or listing.price == 0:
            return 0.5  # No reference — neutral

        ratio = listing.price / self.profile.price

        # ratio of 1.0 = exact match = 1.0 score
        # ratio of 0.5 or 2.0 = poor match
        if ratio <= 0:
            return 0.0

        # Log-based distance: 1.0 = perfect, falls off symmetrically
        log_ratio = abs(math.log(ratio))
        # Within 20% (log(1.2) ≈ 0.18) → score > 0.8
        # Within 2x (log(2) ≈ 0.69) → score ≈ 0.25
        return max(0.0, 1.0 - (log_ratio / 1.0))

    def _score_property_type(self, listing: Listing) -> float:
        """
        Property type match score (0-1).

        Exact match = 1.0. Related types (Home/Townhouse) get partial credit.
        Fundamentally different (Private room vs Entire home) = 0.0.
        """
        if not self.profile.property_type or not listing.property_type:
            return 0.5  # No data — neutral

        ref = self.profile.property_type.lower()
        cand = listing.property_type.lower()

        if ref == cand:
            return 1.0

        # Related categories
        GROUPS = [
            {"home", "house", "townhouse", "cabin", "cottage", "bungalow", "villa"},
            {"apartment", "condo", "loft"},
            {"room", "private room", "shared room"},
            {"studio", "tiny home", "tiny house"},
        ]

        for group in GROUPS:
            if ref in group and cand in group:
                return 0.7  # Same broad category

        return 0.0  # Different category entirely


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Calculate distance between two lat/lng points in kilometers."""
    R = 6371.0  # Earth radius in km

    lat1_r = math.radians(lat1)
    lat2_r = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)

    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlng / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c
