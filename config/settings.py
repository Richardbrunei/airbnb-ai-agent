"""
Configuration settings for Airbnb AI Agent.
"""

from pathlib import Path

# Project paths
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
REPORT_DIR = BASE_DIR / "reports"
CONFIG_DIR = BASE_DIR / "config"

# API Keys (load from environment variables)
OPENAI_API_KEY = ""  # Set via env: OPENAI_API_KEY
AIRBNB_API_KEY = ""  # If using direct API

# Notification settings
EMAIL_SENDER = ""
EMAIL_RECIPIENT = ""
TELEGRAM_BOT_TOKEN = ""
TELEGRAM_CHAT_ID = ""

# Market monitoring settings
SEARCH_LOCATION = ""
DEFAULT_ADULTS = 2
DEFAULT_NIGHTS = 1

# Guest agent settings
AUTO_REPLY_ENABLED = False  # Start with manual review
ESCALATION_THRESHOLD = 0.7  # Confidence below this gets escalated
