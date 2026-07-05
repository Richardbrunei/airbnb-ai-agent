"""
Airbnb AI Agent - Main Entry Point

Coordinates the Market Monitoring Agent and Guest Communication Agent.
"""

import asyncio
import logging
from pathlib import Path

from market_agent.scraper import AirbnbScraper
from market_agent.price_analysis import PriceAnalyzer
from guest_agent.chatbot import GuestChatbot
from reports.daily_report import DailyReportGenerator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def run_market_monitoring():
    """Run the daily market monitoring pipeline."""
    logger.info("Starting market monitoring...")

    scraper = AirbnbScraper()
    analyzer = PriceAnalyzer()
    reporter = DailyReportGenerator()

    # 1. Scrape competitor listings
    listings = await scraper.search_competitors()
    logger.info(f"Found {len(listings)} competitor listings")

    # 2. Analyze pricing
    analysis = analyzer.analyze(listings)
    logger.info("Price analysis complete")

    # 3. Generate and send report
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


if __name__ == "__main__":
    asyncio.run(main())
