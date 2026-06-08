#!/bin/bash
# run.sh — запуск бюллетеня on-demand
# Использование:
#   ./run.sh                        — бюллетень с текущим временем
#   ./run.sh 2026-06-08 14:00       — бюллетень на конкретную дату/время
#   ./run.sh 2026-06-08 14:00 UTC   — с явной таймзоной

set -e

FORECAST_DATE="${1:-$(date '+%Y-%m-%d')}"
FORECAST_TIME="${2:-$(date '+%H:%M')}"
FORECAST_TZ="${3:-MSK}"

echo "Запуск бюллетеня: дата=${FORECAST_DATE} время=${FORECAST_TIME} тз=${FORECAST_TZ}"

export HYDROMET_INGEST_EVENTS_PATH="${HYDROMET_INGEST_EVENTS_PATH:-ingest_events/ingest_events.jsonl}"

# Режим 1: через Docker (если доступен)
if command -v docker-compose &> /dev/null; then
    FORECAST_DATE="${FORECAST_DATE}" \
    FORECAST_TIME="${FORECAST_TIME}" \
    FORECAST_TZ="${FORECAST_TZ}" \
      docker-compose run --rm bulletin
else
    # Режим 2: напрямую через Python
    python forecast_main.py \
        --date "${FORECAST_DATE}" \
        --time "${FORECAST_TIME}" \
        --tz "${FORECAST_TZ}"
fi

