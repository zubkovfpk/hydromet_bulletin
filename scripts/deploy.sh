#!/bin/bash
# =============================================================================
# deploy.sh — сборка Docker-образа и запуск контейнера
#
# Запуск:
#   bash scripts/deploy.sh          # первый запуск / обновление кода
#   bash scripts/deploy.sh --rebuild # принудительная пересборка без кэша
# =============================================================================

set -euo pipefail

PROJECT_DIR="/opt/hydromet_bulletin"
cd "$PROJECT_DIR"

REBUILD=false
if [[ "${1:-}" == "--rebuild" ]]; then
    REBUILD=true
fi

echo "============================================="
echo "  Hydromet Bulletin — деплой"
echo "============================================="

# ── Проверка Docker ───────────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
    echo "ОШИБКА: Docker не установлен. Сначала запустите scripts/install.sh"
    exit 1
fi

# ── Проверка конфига ──────────────────────────────────────────────────────
if [ ! -f "config.ini" ]; then
    echo "ОШИБКА: config.ini не найден в $PROJECT_DIR"
    exit 1
fi

# ── Создание папок ────────────────────────────────────────────────────────
mkdir -p output logs

# ── Остановка старого контейнера (если есть) ──────────────────────────────
echo "Остановка существующего контейнера..."
docker compose down --remove-orphans 2>/dev/null || true

# ── Сборка образа ─────────────────────────────────────────────────────────
if [ "$REBUILD" = true ]; then
    echo "Сборка Docker-образа (без кэша)..."
    docker compose build --no-cache
else
    echo "Сборка Docker-образа..."
    docker compose build
fi

# ── Запуск ────────────────────────────────────────────────────────────────
echo "Запуск контейнера..."
docker compose up -d

# ── Статус ────────────────────────────────────────────────────────────────
sleep 2
echo ""
echo "Статус контейнера:"
docker compose ps

echo ""
echo "  Деплой завершён."
echo "  Логи: docker compose logs -f"
echo "  Тест: bash scripts/run_now.sh morning"
echo "============================================="
