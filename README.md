# Airbnb AI Agent

AI-powered automation platform for Airbnb property management — competitor price monitoring and guest communication.

## Project Structure

```
airbnb-ai-agent/
├── main.py                    # Entry point
├── requirements.txt           # Python dependencies
├── .env.example               # Environment variable template
├── README.md
│
├── market_agent/              # Market Monitoring Agent
│   ├── __init__.py
│   ├── scraper.py             # Airbnb competitor data collection
│   └── price_analysis.py      # Price analysis & recommendations
│
├── guest_agent/               # Guest Communication Agent
│   ├── __init__.py
│   ├── chatbot.py             # AI guest message handler
│   └── knowledge_base.json    # Property info & FAQ
│
├── reports/                   # Daily market reports
│   ├── daily_report.py        # Report generator
│   └── market_report_*.txt    # Generated reports
│
├── data/                      # Data storage
│   └── market_history.csv     # Historical price data
│
├── config/                    # Configuration
│   ├── settings.py            # App settings
│   └── areas.json             # Search area definitions
│
└── tests/                     # Test suite
    ├── test_scraper.py
    └── test_price_analysis.py
```

## Setup

1. Clone the repository
2. Create a virtual environment: `python -m venv venv && source venv/bin/activate`
3. Install dependencies: `pip install -r requirements.txt`
4. Copy `.env.example` to `.env` and fill in your API keys
5. Edit `config/areas.json` with your target search areas
6. Edit `guest_agent/knowledge_base.json` with your property details

## Usage

### Run market monitoring
```bash
python main.py
```

### Run tests
```bash
pytest
```

## Features

### MVP
- [ ] Competitor price scraper
- [ ] Daily market report
- [ ] AI guest message auto-reply
- [ ] Data storage (CSV/SQLite)
- [ ] Email report delivery

### Roadmap
- Phase 1: Single property prototype
- Phase 2: Multi-property dashboard
- Phase 3: Automated dynamic pricing
- Phase 4: Full SaaS platform
