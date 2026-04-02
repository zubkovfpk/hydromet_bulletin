#!/bin/bash
# =============================================================================
# run_now.sh — ручной запуск бюллетеня вне расписания
#
# Использование:
#   bash scripts/run_now.sh morning          # утренний, сегодняшняя дата
#   bash scripts/run_now.sh evening          # вечерний, сегодняшняя дата
#   bash scripts/run_now.sh morning 20260331 # утренний, конкретная дата
#   bash scripts/run_now.sh evening 20260331 # вечерний, конкретная дата
# =============================================================================

set -euo pipefail

TYPE="${1:-morning}"
DATE_ARG="${2:-}"

if [[ "$TYPE" != "morning" && "$TYPE" != "evening" ]]; then
    echo "ОШИБКА: первый аргумент должен быть 'morning' или 'evening'"
    echo "Пример: bash scripts/run_now.sh morning"
    exit 1
fi

PROJECT_DIR="/opt/hydromet_bulletin"
cd "$PROJECT_DIR"

# Проверяем, что контейнер запущен
if ! docker compose ps | grep -q "Up"; then
    echo "Контейнер не запущен. Запустите: bash scripts/deploy.sh"
    exit 1
fi

echo "============================================="
echo "  Запуск: forecast_${TYPE}.py"
[[ -n "$DATE_ARG" ]] && echo "  Дата:   $DATE_ARG" || echo "  Дата:   сегодня"
echo "============================================="

if [[ -n "$DATE_ARG" ]]; then
    docker compose exec bulletin python "forecast_${TYPE}.py" \
        --config /app/config.ini \
        --date "$DATE_ARG"
else
    docker compose exec bulletin python "forecast_${TYPE}.py" \
        --config /app/config.ini
fi

echo ""
echo "  Готово. Файл в: $PROJECT_DIR/output/"
echo "============================================="
