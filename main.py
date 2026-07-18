"""
Airbnb AI Agent - Main Entry Point

Coordinates the Market Monitoring Agent and Guest Communication Agent.
"""

import asyncio
import logging
from pathlib import Path

from market_agent.scraper import AirbnbScraper
from market_agent.price_analysis import PriceAnalyzer
from market_agent.competitor_scorer import CompetitorScorer, PropertyProfile
from guest_agent.chatbot import GuestChatbot
from reports.daily_report import DailyReportGenerator
from data import storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def run_market_monitoring():
    """Run the daily market monitoring pipeline."""
    logger.info("Starting market monitoring...")

    # Ensure database is ready
    storage.init_db()

    scraper = AirbnbScraper()
    analyzer = PriceAnalyzer()
    reporter = DailyReportGenerator()

    # 1. Scrape competitor listings
    listings = await scraper.search_competitors()
    logger.info(f"Found {len(listings)} competitor listings")

    # 2. Store raw listings in database
    stored = storage.store_listings(listings)
    logger.info(f"Stored {stored} listings in database")

    # 3. Analyze pricing
    analysis = analyzer.analyze(listings)
    logger.info("Price analysis complete")

    # 4. Score competitors (if property profile is configured)
    scored = _score_competitors(listings)
    if scored:
        storage.store_scores(scored)
        logger.info(f"Stored {len(scored)} competitor scores")

    # 5. Generate report (also stores snapshot)
    report = reporter.generate(analysis)
    logger.info("Daily report generated")

    return report


async def run_guest_agent():
    """Initialize the guest communication agent."""
    logger.info("Starting guest communication agent...")

    chatbot = GuestChatbot()
    await chatbot.initialize()

    return chatbot


async def main():
    """Main entry point."""
    logger.info("=== Airbnb AI Agent Starting ===")

    # Run market monitoring
    await run_market_monitoring()

    # Initialize guest agent (runs persistently in production)
    # guest_bot = await run_guest_agent()


def _score_competitors(listings: list) -> list:
    """Score competitors if a property profile is configured in areas.json."""
    import json
    areas_path = Path(__file__).parent / "config" / "areas.json"
    if not areas_path.exists():
        return []

    with open(areas_path) as f:
        config = json.load(f)

    areas = config.get("search_areas", [])
    if not areas:
        return []

    profile_data = areas[0].get("property_profile", {})
    if not profile_data:
        return []

    profile = PropertyProfile(
        lat=profile_data.get("lat", 0),
        lng=profile_data.get("lng", 0),
        bedrooms=profile_data.get("bedrooms", 0),
        price=profile_data.get("price", 0),
        property_type=profile_data.get("property_type", ""),
    )

    max_dist = areas[0].get("max_competitor_distance_km", 20.0)
    scorer = CompetitorScorer(profile, max_distance_km=max_dist)
    return scorer.score_all(listings)


if __name__ == "__main__":
    asyncio.run(main())
