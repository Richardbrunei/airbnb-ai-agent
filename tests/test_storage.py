"""Tests for the SQLite storage module."""

import json
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from data import storage
from market_agent.scraper import Listing
from market_agent.price_analysis import MarketStats
from market_agent.competitor_scorer import ScoredListing, PropertyProfile, CompetitorScorer


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_db():
    """Provide a temporary database file for each test."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    storage.init_db(db_path)
    yield db_path
    # Cleanup: remove db + WAL/SHM sidecars
    for suffix in ("", "-wal", "-shm"):
        p = db_path.with_suffix(db_path.suffix + suffix if suffix else db_path.suffix)
        p.unlink(missing_ok=True)


@pytest.fixture
def sample_listings():
    return [
        Listing(
            listing_id="abc123",
            title="Cozy Downtown Condo",
            price=180.0,
            original_price=200.0,
            discount_amount=20.0,
            discount_pct=10.0,
            nights=1,
            rating=4.8,
            reviews=120,
            property_type="Condo",
            bedrooms=2,
            bathrooms=1.5,
            guests=4,
            neighborhood="Downtown",
            url="https://airbnb.com/rooms/abc123",
            lat=30.27,
            lng=-97.74,
            badges=["Superhost"],
            raw={"extra": "data"},
        ),
        Listing(
            listing_id="def456",
            title="Spacious Suburb Home",
            price=250.0,
            original_price=250.0,
            discount_amount=0.0,
            discount_pct=0.0,
            nights=1,
            rating=4.6,
            reviews=85,
            property_type="Home",
            bedrooms=3,
            bathrooms=2.0,
            guests=6,
            neighborhood="Round Rock",
            url="https://airbnb.com/rooms/def456",
            lat=30.51,
            lng=-97.68,
            badges=[],
            raw={},
        ),
        Listing(
            listing_id="ghi789",
            title="Budget Studio",
            price=75.0,
            original_price=90.0,
            discount_amount=15.0,
            discount_pct=16.7,
            nights=1,
            rating=4.3,
            reviews=30,
            property_type="Studio",
            bedrooms=0,
            bathrooms=1.0,
            guests=2,
            neighborhood="East Austin",
            url="https://airbnb.com/rooms/ghi789",
            lat=30.26,
            lng=-97.71,
            badges=["New"],
            raw={},
        ),
    ]


@pytest.fixture
def sample_stats():
    return MarketStats(
        count=3,
        mean_price=168.33,
        median_price=180.0,
        min_price=75.0,
        max_price=250.0,
        stdev_price=88.0,
        avg_rating=4.57,
        avg_reviews=78.3,
        by_bedrooms={0: 75.0, 2: 180.0, 3: 250.0},
        by_neighborhood={"Downtown": 180.0, "Round Rock": 250.0, "East Austin": 75.0},
        discounted_count=2,
        avg_discount_pct=13.35,
        avg_discount_amount=17.5,
        median_original_price=145.0,
        median_effective_price=127.5,
    )


@pytest.fixture
def sample_trends():
    return {
        "total_listings": 3,
        "available_count": 3,
        "highly_rated": 2,
        "discounted_listings": 2,
        "avg_discount_pct": 13.4,
    }


# ── Init ──────────────────────────────────────────────────────────────────────


def test_init_db_creates_tables(tmp_db):
    """init_db should create all required tables."""
    conn = storage.get_db(tmp_db)
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    conn.close()

    assert "listings" in tables
    assert "market_snapshots" in tables
    assert "competitor_scores" in tables


# ── Listings ──────────────────────────────────────────────────────────────────


def test_store_listings_inserts_all(tmp_db, sample_listings):
    """store_listings should insert every listing."""
    count = storage.store_listings(sample_listings, "2026-07-18", tmp_db)
    assert count == 3

    rows = storage.get_listings_by_date("2026-07-18", tmp_db)
    assert len(rows) == 3


def test_store_listings_empty(tmp_db):
    """store_listings with empty list should be a no-op."""
    assert storage.store_listings([], "2026-07-18", tmp_db) == 0


def test_store_listings_preserves_fields(tmp_db, sample_listings):
    """All listing fields should round-trip through the database."""
    storage.store_listings(sample_listings, "2026-07-18", tmp_db)
    rows = storage.get_listings_by_date("2026-07-18", tmp_db)

    condo = next(r for r in rows if r["listing_id"] == "abc123")
    assert condo["title"] == "Cozy Downtown Condo"
    assert condo["price"] == 180.0
    assert condo["original_price"] == 200.0
    assert condo["discount_amount"] == 20.0
    assert condo["rating"] == 4.8
    assert condo["bedrooms"] == 2
    assert condo["neighborhood"] == "Downtown"
    assert condo["lat"] == 30.27
    assert json.loads(condo["badges"]) == ["Superhost"]
    assert json.loads(condo["raw"])["extra"] == "data"


def test_listing_history_tracks_price_over_time(tmp_db, sample_listings):
    """Same listing on different dates should be queryable as history."""
    # Day 1
    storage.store_listings(sample_listings, "2026-07-10", tmp_db)
    # Day 2 — bump the price
    day2 = [Listing(**{**sample_listings[0].__dict__, "price": 195.0})]
    storage.store_listings(day2, "2026-07-11", tmp_db)

    history = storage.get_listing_history("abc123", tmp_db)
    assert len(history) == 2
    assert history[0]["scrape_date"] == "2026-07-10"
    assert history[0]["price"] == 180.0
    assert history[1]["price"] == 195.0


# ── Snapshots ─────────────────────────────────────────────────────────────────


def test_store_and_get_snapshot(tmp_db, sample_stats, sample_trends):
    """Snapshots should round-trip through the database."""
    storage.store_snapshot(sample_stats, sample_trends, "2026-07-18", tmp_db)

    snapshots = storage.get_snapshots(limit=10, db_path=tmp_db)
    assert len(snapshots) == 1
    s = snapshots[0]
    assert s["date"] == "2026-07-18"
    assert s["count"] == 3
    assert s["median_price"] == 180.0
    assert s["discounted_count"] == 2
    assert s["highly_rated"] == 2
    assert json.loads(s["by_bedrooms"])["0"] == 75.0


def test_snapshot_upsert_replaces_same_date(tmp_db, sample_stats, sample_trends):
    """Storing a snapshot for the same date should replace, not duplicate."""
    storage.store_snapshot(sample_stats, sample_trends, "2026-07-18", tmp_db)

    updated = MarketStats(**sample_stats.__dict__)
    updated.median_price = 999.0
    storage.store_snapshot(updated, sample_trends, "2026-07-18", tmp_db)

    snapshots = storage.get_snapshots(db_path=tmp_db)
    assert len(snapshots) == 1
    assert snapshots[0]["median_price"] == 999.0


# ── Competitor Scores ─────────────────────────────────────────────────────────


def test_store_and_get_scores(tmp_db, sample_listings):
    """Competitor scores should be stored and retrieved correctly."""
    profile = PropertyProfile(
        lat=30.27, lng=-97.74, bedrooms=2, price=180, property_type="Condo"
    )
    scorer = CompetitorScorer(profile, max_distance_km=20.0)
    scored = scorer.score_all(sample_listings)

    stored = storage.store_scores(scored, "2026-07-18", tmp_db)
    assert stored == 3

    top = storage.get_top_competitors("2026-07-18", top_n=2, db_path=tmp_db)
    assert len(top) == 2
    # Scores should be in descending order
    assert top[0]["total_score"] >= top[1]["total_score"]
    # Should have breakdown scores
    assert "location_score" in top[0]
    assert "price_score" in top[0]


def test_store_scores_empty(tmp_db):
    """Empty scores list should be a no-op."""
    assert storage.store_scores([], "2026-07-18", tmp_db) == 0


# ── CSV Export ────────────────────────────────────────────────────────────────


def test_export_csv(tmp_db, sample_stats, sample_trends):
    """CSV export should produce the legacy format."""
    storage.store_snapshot(sample_stats, sample_trends, "2026-07-18", tmp_db)

    csv_path = storage.export_csv(db_path=tmp_db)
    assert csv_path.exists()

    import csv as csv_mod
    with open(csv_path) as f:
        reader = csv_mod.DictReader(f)
        rows = list(reader)

    assert len(rows) == 1
    assert rows[0]["date"] == "2026-07-18"
    assert rows[0]["median_price"] == "180.0"


# ── Migration ─────────────────────────────────────────────────────────────────


def test_migrate_csv(tmp_db):
    """Migration should import existing CSV data into snapshots."""
    import csv as csv_mod

    csv_path = Path(tempfile.mktemp(suffix=".csv"))
    with open(csv_path, "w", newline="") as f:
        writer = csv_mod.writer(f)
        writer.writerow([
            "date", "count", "median_price", "mean_price",
            "min_price", "max_price", "avg_rating",
        ])
        writer.writerow(["2026-06-27", "269", "204.0", "249.59", "49.0", "1475.0", "4.81"])

    migrated = storage.migrate_csv(csv_path, tmp_db)
    assert migrated == 1

    snapshots = storage.get_snapshots(db_path=tmp_db)
    assert len(snapshots) == 1
    assert snapshots[0]["date"] == "2026-06-27"
    assert snapshots[0]["count"] == 269
    assert snapshots[0]["median_price"] == 204.0

    csv_path.unlink(missing_ok=True)


def test_migrate_csv_missing_file(tmp_db):
    """Migration with no CSV should return 0 gracefully."""
    result = storage.migrate_csv(Path("/nonexistent/file.csv"), tmp_db)
    assert result == 0
