#!/bin/bash
# Daily Airbnb market monitoring runner
set -euo pipefail

PROJECT_DIR="/home/liang/.openclaw/workspace/coding/airbnb-ai-agent"
LOG_FILE="$PROJECT_DIR/logs/daily.log"

mkdir -p "$PROJECT_DIR/logs"

cd "$PROJECT_DIR"

echo "=== $(date '+%Y-%m-%d %H:%M:%S') Starting Airbnb market monitoring ===" >> "$LOG_FILE"

# Run the pipeline
python3 main.py >> "$LOG_FILE" 2>&1

EXIT_CODE=$?
if [ $EXIT_CODE -eq 0 ]; then
    echo "=== $(date '+%Y-%m-%d %H:%M:%S') Completed successfully ===" >> "$LOG_FILE"
else
    echo "=== $(date '+%Y-%m-%d %H:%M:%S') FAILED with exit code $EXIT_CODE ===" >> "$LOG_FILE"
fi

exit $EXIT_CODE
