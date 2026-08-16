# Airbnb AI Agent

AI-powered automation platform for Airbnb property management — competitor price monitoring, scoring, and guest communication.

## Project Structure

```
airbnb-ai-agent/
├── main.py                         # Entry point — runs full market pipeline
├── search.py                       # Standalone CLI for competitor search
├── properties.py                   # Manage properties (add/edit/view/remove)
├── reply.py                        # Draft AI replies to guest messages
├── run_daily.sh                    # Shell wrapper for cron/systemd
├── run_if_missed.py                # Catch-up runner if schedule was missed
├── requirements.txt                # Python dependencies
├── .env.example                    # Environment variable template
│
├── market_agent/                   # Market Monitoring
│   ├── scraper.py                  # Airbnb competitor data collection (pyairbnb)
│   ├── price_analysis.py           # Price analysis & recommendations
│   └── competitor_scorer.py        # Similarity scoring vs your property
│
├── guest_agent/                    # Guest Communication
│   ├── chatbot.py                  # AI guest message handler
│   └── knowledge_base.json         # Property info & FAQ
│
├── reports/                        # Daily market reports
│   ├── daily_report.py             # Report generator
│   └── market_report_*.txt         # Generated reports
│
├── data/                           # Data storage
│   ├── storage.py                  # SQLite + CSV storage layer
│   └── market_history.csv          # Historical price data
│
├── config/                         # Configuration
│   ├── settings.py                 # App settings
│   └── areas.json                  # Search areas & property profile
│
├── logs/                           # Run logs
└── tests/                          # Test suite
    ├── test_scraper.py
    └── test_price_analysis.py
```

## Setup

```bash
# 1. Clone & enter
cd coding/airbnb-ai-agent

# 2. Virtual environment
python -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env with your API keys (OpenAI, Telegram, email — optional depending on features used)

# 5. Configure your search area & property profile
# Edit config/areas.json (see Configuration below)
```

## Configuration

### `config/areas.json`

This is the core config file. It defines where to search, what to filter for, and your property profile for competitor scoring.

```json
{
  "search_areas": [
    {
      "name": "My Area",
      "location": "Austin, TX",
      "radius_km": 5,
      "property_types": ["Entire home/apt", "Private room"],

      "target_price_min": 50,
      "target_price_max": 300,

      "competitor_filters": {
        "min_bedrooms": 1,
        "max_bedrooms": 3,
        "property_types": ["Entire home", "Apartment", "Condo", "House", "Home", "Townhouse"],
        "neighborhoods": [],
        "target_price_min": 80,
        "target_price_max": 350,
        "min_rating": 4.5,
        "min_reviews": 10
      },

      "property_profile": {
        "lat": 30.2672,
        "lng": -97.7431,
        "bedrooms": 2,
        "price": 180,
        "property_type": "Home"
      },

      "max_competitor_distance_km": 15
    }
  ],
  "schedule": {
    "run_time": "08:00",
    "timezone": "America/Chicago"
  },
  "notification": {
    "email": "",
    "telegram_chat_id": ""
  }
}
```

#### Key fields

| Field | Description |
|-------|-------------|
| `location` | City or area name — used for logging and bbox lookup |
| `bbox` | Optional: `[sw_lat, sw_lng, ne_lat, ne_lng]` to override auto-detection |
| `competitor_filters` | Filters raw results down to real competitors. All fields optional — omit to skip that filter |
| `property_profile` | Your property's stats. Used by the competitor scorer to rank similarity |
| `max_competitor_distance_km` | Max distance from your property for scoring (listings beyond this get score 0) |

#### Competitor filters available

- `min_bedrooms` / `max_bedrooms` — bedroom count range
- `property_types` — substring match against listing type (e.g. "Home", "Apartment")
- `neighborhoods` — case-insensitive substring match
- `min_rating` — minimum guest rating (e.g. 4.5)
- `min_reviews` — minimum review count
- `target_price_min` / `target_price_max` — price band for filtering

### `.env`

Only needed for optional features:
- `OPENAI_API_KEY` — guest chatbot AI
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` — Telegram notifications
- `EMAIL_SENDER` / `EMAIL_PASSWORD` / `EMAIL_RECIPIENT` — email reports

## Usage

### Manage Properties (`properties.py`)

Add, edit, view, and remove properties (search areas) in `config/areas.json`.

```bash
# List all properties (short format)
python properties.py list

# View details of a specific property
python properties.py view --index 0
python properties.py view --name "Destin Condo"

# View all properties (verbose)
python properties.py view

# Add a property (flags)
python properties.py add \
  --name "Destin Condo" \
  --location "Destin, FL" \
  --lat 30.393 --lng -86.495 \
  --bedrooms 2 --price 220 \
  --property-type "Condo" \
  --radius 5

# Add with competitor filters
python properties.py add \
  --name "Austin House" \
  --location "Austin, TX" \
  --lat 30.267 --lng -97.743 \
  --bedrooms 3 --price 200 \
  --min-price 100 --max-price 350 \
  --min-bedrooms 2 --max-bedrooms 4 \
  --min-rating 4.5 --min-reviews 10

# Add interactively (prompts for each field)
python properties.py add

# Edit specific fields
python properties.py edit --index 0 --price 250
python properties.py edit --name "Destin Condo" --bedrooms 3 --radius 10

# Edit interactively (pre-fills current values)
python properties.py edit --index 0 --interactive

# Remove a property
python properties.py remove --index 1
python properties.py remove --name "Destin Condo"
python properties.py remove --name "Destin Condo" --force   # skip confirm
```

**Add/Edit fields:**

| Flag | Description |
|------|-------------|
| `--name` | Property name |
| `--location` | City, State |
| `--lat / --lng` | Coordinates |
| `--bedrooms` | Bedroom count |
| `--price` | Typical nightly price |
| `--property-type` | Property type (Home, Condo, etc.) |
| `--radius` | Search radius in km (default: 5) |
| `--max-distance` | Max competitor distance in km (default: 15) |
| `--min-bedrooms / --max-bedrooms` | Competitor bedroom range |
| `--min-price / --max-price` | Competitor price range |
| `--filter-types` | Competitor property types (space-separated) |
| `--min-rating` | Minimum competitor rating |
| `--min-reviews` | Minimum competitor review count |
| `--interactive` | Prompt for each field (Enter to keep current) |

### Search competitors via CLI (`search.py`)

Standalone tool for ad-hoc competitor searches without running the full pipeline.

```bash
# Search by location (defaults to next weekend if no dates)
python search.py --location "Austin, TX"

# Search around a specific Airbnb listing URL
# Fetches the listing's coordinates, then finds competitors nearby.
# Scoring is automatic — the source listing becomes the property profile.
python search.py --url "https://www.airbnb.com/rooms/1234567890"

# Control the search radius around a URL (default: 5km)
python search.py --url "https://www.airbnb.com/rooms/1234567890" --radius 3

# Add dates and filters to a URL search
python search.py --url "https://www.airbnb.com/rooms/1234567890" --checkin 2026-08-01 --checkout 2026-08-07 --max-price 300

# Export URL search results to JSON
python search.py --url "https://www.airbnb.com/rooms/1234567890" -o competitors.json

# Specific dates
python search.py --location "Austin, TX" --checkin 2026-08-01 --checkout 2026-08-07

# Tight radius around coordinates
python search.py --lat 30.267 --lng -97.743 --radius 2

# Explicit bounding box
python search.py --bbox 30.23 -97.80 30.30 -97.70

# With filters
python search.py --location "Austin, TX" --min-price 100 --max-price 300 --bedrooms 2

# Score against your property profile (from config/areas.json)
python search.py --location "Austin, TX" --score

# Export to JSON
python search.py --location "Austin, TX" --output competitors.json

# Save to database (listings + scores stored in data/market.db)
python search.py --location "Austin, TX" --score --save

# URL search with scoring + database save
python search.py --url "https://www.airbnb.com/rooms/1234567890" --save -o competitors.json
```

**How `--url` works:**
1. Fetches the listing's details via `pyairbnb.get_details()` to get its coordinates, bedrooms, price, and type.
2. Draws a bounding box around the listing (controlled by `--radius`, default 5km).
3. Searches that area for all listings.
4. Excludes the source listing from results.
5. Auto-scores every result against the source listing (no need for `--score`).
6. Prints the source listing's details, then the ranked competitors.

**Options:**

| Flag | Description |
|------|-------------|
| `-l, --location` | City or area to search (e.g. "Austin, TX") |
| `-u, --url` | Airbnb listing URL — fetches coordinates and finds competitors nearby |
| `--lat / --lng` | Coordinate-based search center |
| `--radius` | Search radius in km around `--url` or `--lat/--lng` (default: 5) |
| `--bbox` | Explicit bounding box: `SW_LAT SW_LNG NE_LAT NE_LNG` |
| `--checkin / --checkout` | Dates in YYYY-MM-DD (default: next Friday→Saturday) |
| `--adults` | Number of adults (default: 2) |
| `--min-price / --max-price` | Price range filter |
| `--bedrooms` | Exact bedroom count filter |
| `--property-type` | Property type filter (e.g. "Entire home", "Condo") |
| `--score` | Score competitors against property profile from config |
| `--save` | Save results to SQLite database (`data/market.db`) |
| `-o, --output` | Export results to JSON file |
| `-v, --verbose` | Debug logging |

Output includes a formatted table with prices, ratings, discount info, and listing URLs.

### Draft Guest Replies (`reply.py`)

Draft AI replies to guest messages using the property knowledge base. Supports z.ai (default) and OpenAI.

```bash
# Interactive mode (prompts for message)
python reply.py

# Pass message directly
python reply.py -m "Hi, what time is check-in?"

# With guest name
python reply.py -m "Hey, running late!" --guest "Sarah"

# Use OpenAI instead of z.ai
python reply.py -m "Is parking free?" --provider openai

# Just draft, skip auto-send decision
python reply.py -m "WiFi password?" --draft-only

# List properties in knowledge base
python reply.py --list

# Debug the system prompt
python reply.py --show-prompt
```

**How it works:**
1. Classifies the message (inquiry, check-in, amenity, issue, general).
2. Builds a system prompt from `knowledge_base.json` (property details, amenities, rules, FAQ, policies).
3. Calls the LLM to generate a reply with a confidence score.
4. Issues/complaints always escalate — never auto-send.
5. High-confidence responses (≥ threshold) are approved for auto-send.
6. Everything else is flagged for review.

**Options:**

| Flag | Description |
|------|-------------|
| `-m, --message` | Guest message text |
| `-g, --guest` | Guest name for personalization |
| `-p, --property` | Property index (see `--list`) |
| `--provider` | `zai` or `openai` (default: auto-detect from env) |
| `--model` | Model name override (default: `glm-4` for zai, `gpt-4o` for OpenAI) |
| `--api-key` | API key (default: from env var) |
| `--draft-only` | Skip auto-send/escalate decision |
| `--threshold` | Confidence threshold for auto-send (default: 0.7) |
| `--show-prompt` | Print system prompt and exit |
| `--list` | List properties in knowledge base |

**Environment variables:**

| Variable | Description |
|----------|-------------|
| `ZAI_API_KEY` | z.ai API key (get from [bigmodel.cn](https://bigmodel.cn/usercenter/proj-mgmt/apikeys)) |
| `OPENAI_API_KEY` | OpenAI API key |
| `LLM_PROVIDER` | Force `zai` or `openai` (default: auto-detect) |

**Provider:** z.ai uses the OpenAI SDK with `base_url=https://open.bigmodel.cn/api/paas/v4/`. Switching to OpenAI later is just `--provider openai`.

### Run the full market monitoring pipeline

```bash
cd coding/airbnb-ai-agent
source venv/bin/activate
python main.py
```

This will:
1. Load search areas from `config/areas.json`
2. Scrape competitor listings via `pyairbnb` (defaults to next weekend if no dates)
3. Filter results down to real competitors
4. Store raw listings in SQLite
5. Score competitors against your property profile
6. Generate a daily market report in `reports/`

### Run via shell wrapper (for cron)

```bash
bash run_daily.sh
```

Logs go to `logs/daily.log`.

### Run tests

```bash
cd coding/airbnb-ai-agent
source venv/bin/activate
pytest
```

## How Competitor Scraping Works

1. **Bounding box search** — The scraper calls `pyairbnb.search_all()` with coordinates covering your area. Built-in defaults exist for Austin, Dallas, Houston, and San Antonio. For other areas, add a `"bbox"` field to `areas.json`.

2. **Price extraction** — Each listing's price is parsed from multiple sources in the raw data (per-night rate, multi-night breakdown, discounts). The scraper captures:
   - Effective nightly price (post-discount)
   - Original nightly price (pre-discount)
   - Discount types (last-minute, long stay, special offer, etc.)
   - Discount amount and percentage

3. **Filtering** — Raw results are filtered using `competitor_filters` from config (bedrooms, property type, price range, rating, reviews, neighborhood).

4. **Scoring** — Filtered competitors are scored against your `property_profile` using distance, bedroom count, property type, and price similarity. Closer match = higher score.

5. **Storage** — Listings and scores go to SQLite (`data/` module). A CSV snapshot is also kept in `data/market_history.csv`.

6. **Reporting** — A human-readable report is generated in `reports/market_report_YYYY-MM-DD.txt`.

## Finding Competitors for a Specific Property

1. Edit `config/areas.json`:
   - Set `location` to your property's city
   - Set `property_profile` with your property's lat/lng, bedrooms, price, and type
   - Adjust `competitor_filters` to match comparable listings
   - Optionally add `"bbox": [sw_lat, sw_lng, ne_lat, ne_lng]` for a tight radius around your property

2. Run:
   ```bash
   python main.py
   ```

3. Check `reports/market_report_*.txt` for the analysis.

## Adding a New Search Area

Add a new entry to the `search_areas` array in `areas.json`:

```json
{
  "name": "Destin, FL",
  "location": "Destin, FL",
  "bbox": [30.36, -86.52, 30.43, -86.40],
  "property_profile": {
    "lat": 30.393,
    "lng": -86.495,
    "bedrooms": 3,
    "price": 250,
    "property_type": "Condo"
  },
  "max_competitor_distance_km": 10,
  "competitor_filters": {
    "min_bedrooms": 2,
    "property_types": ["Condo", "Apartment"],
    "target_price_max": 400
  }
}
```

For the `bbox`, go to Google Maps, zoom to your area, and note the southwest and northeast corner coordinates. Or use an online tool like [bboxfinder.com](http://bboxfinder.com/).

## Automation

### Cron (daily run)

```bash
# Run every day at 8:00 AM CT
0 8 * * * /home/liang/.openclaw/workspace/coding/airbnb-ai-agent/run_daily.sh
```

### Catch-up runner

If a scheduled run was missed, `run_if_missed.py` checks whether today's run happened and executes it if not:

```bash
python run_if_missed.py
```

## Output

### Market Report (`reports/market_report_YYYY-MM-DD.txt`)

Human-readable summary including:
- Number of competitors found
- Price statistics (min, max, median, average)
- Top competitors by score
- Notable discounts or pricing trends

### Database (`data/`)

SQLite storage with:
- Raw listing data per scrape
- Competitor scores per run
- Historical pricing for trend analysis

### CSV (`data/market_history.csv`)

Flat-file snapshot of each run for quick spreadsheet analysis.

## Tech Stack

- **Python 3.11+**
- **[pyairbnb](https://pypi.org/project/pyairbnb/)** — Airbnb data scraping (no API key needed)
- **SQLite** — local data storage
- **[z.ai GLM](https://bigmodel.cn)** — guest chatbot LLM (default, OpenAI-compatible)
- **[OpenAI](https://openai.com)** — guest chatbot LLM (optional alternative)
- **Telegram / Email** — notification delivery (optional)
