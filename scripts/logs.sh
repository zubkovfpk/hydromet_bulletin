#!/bin/bash
# =============================================================================
# logs.sh — просмотр логов проекта
#
# Использование:
#   bash scripts/logs.sh           # все логи, следить в реальном времени
#   bash scripts/logs.sh app       # только лог Python-скриптов
#   bash scripts/logs.sh cron      # только лог cron
#   bash scripts/logs.sh docker    # логи контейнера (stdout/stderr)
#   bash scripts/logs.sh tail 100  # последние N строк всех логов
# =============================================================================

PROJECT_DIR="/opt/hydromet_bulletin"
MODE="${1:-all}"
LINES="${2:-50}"

case "$MODE" in
    app)
        echo "=== $PROJECT_DIR/logs/hydromet.log ==="
        tail -f "$PROJECT_DIR/logs/hydromet.log"
        ;;
    cron)
        echo "=== $PROJECT_DIR/logs/cron.log ==="
        tail -f "$PROJECT_DIR/logs/cron.log"
        ;;
    docker)
        cd "$PROJECT_DIR"
        docker compose logs -f --tail=100
        ;;
    tail)
        echo "=== hydromet.log (последние $LINES строк) ==="
        tail -n "$LINES" "$PROJECT_DIR/logs/hydromet.log"
        echo ""
        echo "=== cron.log (последние $LINES строк) ==="
        tail -n "$LINES" "$PROJECT_DIR/logs/cron.log"
        ;;
    all|*)
        tail -f \
            "$PROJECT_DIR/logs/hydromet.log" \
            "$PROJECT_DIR/logs/cron.log"
        ;;
esac
