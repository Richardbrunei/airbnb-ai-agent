"""
SQLite storage for Airbnb market data.

Stores individual listings per scrape, daily market snapshots, and
competitor scores — replacing the flat CSV approach.

Database: data/market.db
"""

import csv
import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from market_agent.scraper import Listing
from market_agent.price_analysis import MarketStats

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent / "market.db"


SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    scrape_date     TEXT    NOT NULL,
    listing_id      TEXT,
    title           TEXT,
    price           REAL,
    original_price  REAL,
    discount_amount REAL,
    discount_pct    REAL,
    discount_types  TEXT,   -- JSON array of discount type labels
    discounts       TEXT,   -- JSON array of {type, amount, per_night}
    nights          INTEGER,
    currency        TEXT    DEFAULT 'USD',
    rating          REAL,
    reviews         INTEGER,
    property_type   TEXT,
    bedrooms        INTEGER,
    bathrooms       REAL,
    guests          INTEGER,
    neighborhood    TEXT,
    url             TEXT,
    available       INTEGER DEFAULT 1,
    lat             REAL,
    lng             REAL,
    badges          TEXT,   -- JSON array
    raw             TEXT    -- JSON blob
);

CREATE INDEX IF NOT EXISTS idx_listings_date    ON listings(scrape_date);
CREATE INDEX IF NOT EXISTS idx_listings_airbnb  ON listings(listing_id);
CREATE INDEX IF NOT EXISTS idx_listings_hood    ON listings(neighborhood);

CREATE TABLE IF NOT EXISTS market_snapshots (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    date                    TEXT    NOT NULL UNIQUE,
    count                   INTEGER,
    median_price            REAL,
    mean_price              REAL,
    min_price               REAL,
    max_price               REAL,
    stdev_price             REAL,
    avg_rating              REAL,
    avg_reviews             REAL,
    by_bedrooms             TEXT,   -- JSON
    by_neighborhood         TEXT,   -- JSON
    discounted_count        INTEGER,
    avg_discount_pct        REAL,
    avg_discount_amount     REAL,
    median_original_price   REAL,
    median_effective_price  REAL,
    total_listings          INTEGER,
    available_count         INTEGER,
    highly_rated            INTEGER
);

CREATE INDEX IF NOT EXISTS idx_snapshots_date ON market_snapshots(date);

CREATE TABLE IF NOT EXISTS competitor_scores (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    scrape_date     TEXT    NOT NULL,
    listing_id      TEXT,
    title           TEXT,
    total_score     REAL,
    location_score  REAL,
    bedroom_score   REAL,
    price_score     REAL,
    type_score      REAL,
    price           REAL,
    bedrooms        INTEGER,
    neighborhood    TEXT,
    lat             REAL,
    lng             REAL
);

CREATE INDEX IF NOT EXISTS idx_scores_date ON competitor_scores(scrape_date);
"""


def get_db(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Open a database connection with row factory enabled."""
    path = db_path or DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Optional[Path] = None) -> None:
    """Create tables if they don't exist."""
    conn = get_db(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        logger.info(f"Database initialized at {db_path or DB_PATH}")
    finally:
        conn.close()


# ── Listings ──────────────────────────────────────────────────────────────────


def store_listings(
    listings: list[Listing],
    scrape_date: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> int:
    """
    Insert all listings from a scrape run.

    Returns the number of rows inserted.
    """
    if not listings:
        return 0

    date_str = scrape_date or datetime.now().strftime("%Y-%m-%d")
    conn = get_db(db_path)
    inserted = 0

    try:
        for l in listings:
            conn.execute(
                """
                INSERT INTO listings (
                    scrape_date, listing_id, title, price, original_price,
                    discount_amount, discount_pct, discount_types, discounts,
                    nights, currency, rating,
                    reviews, property_type, bedrooms, bathrooms, guests,
                    neighborhood, url, available, lat, lng, badges, raw
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    date_str,
                    l.listing_id,
                    l.title,
                    l.price,
                    l.original_price,
                    l.discount_amount,
                    l.discount_pct,
                    json.dumps(l.discount_types),
                    json.dumps([
                        {"type": d.type, "amount": d.amount, "per_night": d.per_night}
                        for d in l.discounts
                    ]),
                    l.nights,
                    l.currency,
                    l.rating,
                    l.reviews,
                    l.property_type,
                    l.bedrooms,
                    l.bathrooms,
                    l.guests,
                    l.neighborhood,
                    l.url,
                    int(l.available),
                    l.lat,
                    l.lng,
                    json.dumps(l.badges),
                    json.dumps(l.raw),
                ),
            )
            inserted += 1

        conn.commit()
        logger.info(f"Stored {inserted} listings for {date_str}")
    finally:
        conn.close()

    return inserted


def get_listings_by_date(
    scrape_date: str, db_path: Optional[Path] = None
) -> list[dict]:
    """Retrieve all listings from a specific scrape date."""
    conn = get_db(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM listings WHERE scrape_date = ? ORDER BY price",
            (scrape_date,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_listing_history(
    listing_id: str, db_path: Optional[Path] = None
) -> list[dict]:
    """Get price history for a specific Airbnb listing across all scrape dates."""
    conn = get_db(db_path)
    try:
        rows = conn.execute(
            """
            SELECT scrape_date, price, original_price, discount_pct, available
            FROM listings
            WHERE listing_id = ?
            ORDER BY scrape_date
            """,
            (listing_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ── Market Snapshots ──────────────────────────────────────────────────────────


def store_snapshot(
    stats: MarketStats,
    trends: dict,
    date_str: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> None:
    """Insert or replace a daily market snapshot."""
    date_str = date_str or datetime.now().strftime("%Y-%m-%d")
    conn = get_db(db_path)

    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO market_snapshots (
                date, count, median_price, mean_price, min_price, max_price,
                stdev_price, avg_rating, avg_reviews, by_bedrooms, by_neighborhood,
                discounted_count, avg_discount_pct, avg_discount_amount,
                median_original_price, median_effective_price,
                total_listings, available_count, highly_rated
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                date_str,
                stats.count,
                stats.median_price,
                stats.mean_price,
                stats.min_price,
                stats.max_price,
                stats.stdev_price,
                stats.avg_rating,
                stats.avg_reviews,
                json.dumps(stats.by_bedrooms),
                json.dumps(stats.by_neighborhood),
                stats.discounted_count,
                stats.avg_discount_pct,
                stats.avg_discount_amount,
                stats.median_original_price,
                stats.median_effective_price,
                trends.get("total_listings", stats.count),
                trends.get("available_count", 0),
                trends.get("highly_rated", 0),
            ),
        )
        conn.commit()
        logger.info(f"Snapshot stored for {date_str}")
    finally:
        conn.close()


def get_snapshots(
    limit: int = 30, db_path: Optional[Path] = None
) -> list[dict]:
    """Get recent market snapshots, most recent first."""
    conn = get_db(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM market_snapshots ORDER BY date DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ── Competitor Scores ─────────────────────────────────────────────────────────


def store_scores(
    scored_listings: list,
    scrape_date: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> int:
    """
    Store competitor scoring results.

    Accepts ScoredListing objects from CompetitorScorer.
    Returns rows inserted.
    """
    if not scored_listings:
        return 0

    date_str = scrape_date or datetime.now().strftime("%Y-%m-%d")
    conn = get_db(db_path)
    inserted = 0

    try:
        for sl in scored_listings:
            l = sl.listing
            conn.execute(
                """
                INSERT INTO competitor_scores (
                    scrape_date, listing_id, title, total_score,
                    location_score, bedroom_score, price_score, type_score,
                    price, bedrooms, neighborhood, lat, lng
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    date_str,
                    l.listing_id,
                    l.title,
                    sl.total_score,
                    sl.breakdown.get("location", 0),
                    sl.breakdown.get("bedrooms", 0),
                    sl.breakdown.get("price", 0),
                    sl.breakdown.get("property_type", 0),
                    l.price,
                    l.bedrooms,
                    l.neighborhood,
                    l.lat,
                    l.lng,
                ),
            )
            inserted += 1

        conn.commit()
        logger.info(f"Stored {inserted} competitor scores for {date_str}")
    finally:
        conn.close()

    return inserted


def get_top_competitors(
    scrape_date: str, top_n: int = 10, db_path: Optional[Path] = None
) -> list[dict]:
    """Get top-ranked competitors for a given date."""
    conn = get_db(db_path)
    try:
        rows = conn.execute(
            """
            SELECT * FROM competitor_scores
            WHERE scrape_date = ?
            ORDER BY total_score DESC
            LIMIT ?
            """,
            (scrape_date, top_n),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ── CSV Export (backwards compatibility) ──────────────────────────────────────


def export_csv(db_path: Optional[Path] = None) -> Path:
    """Export market_snapshots to the legacy CSV format."""
    conn = get_db(db_path)
    csv_path = Path(__file__).parent / "market_history.csv"

    try:
        rows = conn.execute(
            """
            SELECT date, count, median_price, mean_price, min_price, max_price, avg_rating
            FROM market_snapshots ORDER BY date
            """
        ).fetchall()

        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "date", "count", "median_price", "mean_price",
                "min_price", "max_price", "avg_rating",
            ])
            for r in rows:
                writer.writerow([
                    r["date"], r["count"], r["median_price"], r["mean_price"],
                    r["min_price"], r["max_price"], r["avg_rating"] or "",
                ])

        logger.info(f"CSV export written to {csv_path}")
    finally:
        conn.close()

    return csv_path


# ── Migration ─────────────────────────────────────────────────────────────────


def migrate_csv(
    csv_path: Optional[Path] = None, db_path: Optional[Path] = None
) -> int:
    """
    Migrate legacy market_history.csv into market_snapshots table.

    Returns rows migrated.
    """
    csv_path = csv_path or (Path(__file__).parent / "market_history.csv")
    if not csv_path.exists():
        logger.info("No CSV to migrate")
        return 0

    init_db(db_path)
    conn = get_db(db_path)
    migrated = 0

    try:
        with open(csv_path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO market_snapshots (
                        date, count, median_price, mean_price,
                        min_price, max_price, avg_rating
                    ) VALUES (?,?,?,?,?,?,?)
                    """,
                    (
                        row["date"],
                        int(row["count"]),
                        float(row["median_price"]),
                        float(row["mean_price"]),
                        float(row["min_price"]),
                        float(row["max_price"]),
                        float(row["avg_rating"]) if row["avg_rating"] else None,
                    ),
                )
                migrated += 1

        conn.commit()
        logger.info(f"Migrated {migrated} rows from {csv_path}")
    finally:
        conn.close()

    return migrated
