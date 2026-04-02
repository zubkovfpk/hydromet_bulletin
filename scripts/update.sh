#!/bin/bash
# =============================================================================
# update.sh — обновление проекта из нового zip-архива
#
# Использование:
#   bash scripts/update.sh /path/to/hydromet_bulletin_python.zip
#
# Сохраняет: config.ini, output/, logs/
# Заменяет:  весь Python-код, Dockerfile, docker-compose.yml
# =============================================================================

set -euo pipefail

ZIP_PATH="${1:-}"
PROJECT_DIR="/opt/hydromet_bulletin"
BACKUP_DIR="/opt/hydromet_backup_$(date +%Y%m%d_%H%M%S)"

if [ -z "$ZIP_PATH" ] || [ ! -f "$ZIP_PATH" ]; then
    echo "ОШИБКА: укажите путь к zip-архиву"
    echo "Пример: bash scripts/update.sh /tmp/hydromet_bulletin_python.zip"
    exit 1
fi

echo "============================================="
echo "  Hydromet Bulletin — обновление"
echo "============================================="

# ── Бэкап текущей версии ──────────────────────────────────────────────────
echo "[1/4] Создание резервной копии → $BACKUP_DIR"
cp -r "$PROJECT_DIR" "$BACKUP_DIR"
echo "      OK"

# ── Остановка контейнера ──────────────────────────────────────────────────
echo "[2/4] Остановка контейнера..."
cd "$PROJECT_DIR"
docker compose down --remove-orphans 2>/dev/null || true
echo "      OK"

# ── Распаковка нового кода (без перезаписи config.ini, output, logs) ──────
echo "[3/4] Обновление кода..."
TMP_DIR=$(mktemp -d)
unzip -q "$ZIP_PATH" -d "$TMP_DIR"

# Копируем всё, кроме конфига и данных
rsync -a --exclude='config.ini' \
         --exclude='output/' \
         --exclude='logs/' \
         "$TMP_DIR/hydromet_bulletin/" "$PROJECT_DIR/"

rm -rf "$TMP_DIR"
chmod +x scripts/*.sh entrypoint.sh
echo "      OK"

# ── Пересборка и запуск ───────────────────────────────────────────────────
echo "[4/4] Пересборка и запуск..."
docker compose build
docker compose up -d
echo "      OK"

echo ""
echo "  Обновление завершено."
echo "  Бэкап сохранён в: $BACKUP_DIR"
echo "  Статус: bash scripts/status.sh"
echo "============================================="
