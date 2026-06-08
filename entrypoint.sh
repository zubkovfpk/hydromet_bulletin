#!/bin/bash
# entrypoint.sh — on-demand запуск forecast_main.py
# Параметры передаются через ENV переменные или аргументы.
#
# Режим 1 (on-demand): docker-compose run bulletin
#   ENV: FORECAST_DATE, FORECAST_TIME, FORECAST_TZ (опционально)
#
# Режим 2 (cron ingest фоном): docker-compose up -d
#   Запускает cron daemon для предзагрузки GFS данных.

set -e

mkdir -p /app/output /app/logs /app/ingest_events /app/storage

export HYDROMET_INGEST_EVENTS_PATH=/app/ingest_events/ingest_events.jsonl

# Если передан аргумент "cron" — запустить cron daemon (для up -d)
if [ "${1}" = "cron" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S')  INFO  Cron mode: GFS ingest scheduler."
    touch /app/logs/cron.log
    cron
    tail -f /app/logs/cron.log
    exit 0
fi

# On-demand режим: запустить forecast_main.py
FORECAST_DATE="${FORECAST_DATE:-$(date '+%Y-%m-%d')}"
FORECAST_TIME="${FORECAST_TIME:-$(date '+%H:%M')}"
FORECAST_TZ="${FORECAST_TZ:-MSK}"

echo "$(date '+%Y-%m-%d %H:%M:%S')  INFO  On-demand bulletin: date=${FORECAST_DATE} time=${FORECAST_TIME} tz=${FORECAST_TZ}"

exec /usr/local/bin/python forecast_main.py \
    --date "${FORECAST_DATE}" \
    --time "${FORECAST_TIME}" \
    --tz "${FORECAST_TZ}"

