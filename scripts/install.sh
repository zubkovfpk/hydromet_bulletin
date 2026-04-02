#!/bin/bash
# =============================================================================
# install.sh — первичная установка проекта на сервере Ubuntu 22 LTS
#
# Запуск (от root или sudo):
#   bash scripts/install.sh
# =============================================================================

set -euo pipefail

PROJECT_DIR="/opt/hydromet_bulletin"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

echo "============================================="
echo "  Hydromet Bulletin — установка"
echo "============================================="

# ── 1. Системные зависимости ──────────────────────────────────────────────
echo "[1/5] Обновление пакетов и установка зависимостей..."
apt-get update -qq
apt-get install -y --no-install-recommends \
    curl \
    unzip \
    docker.io \
    docker-compose-plugin
echo "      OK"

# ── 2. Docker в автозапуск ────────────────────────────────────────────────
echo "[2/5] Включение Docker в автозапуск..."
systemctl enable docker
systemctl start docker
echo "      OK"

# ── 3. Копируем проект ────────────────────────────────────────────────────
echo "[3/5] Копирование проекта в $PROJECT_DIR..."
if [ "$ROOT_DIR" != "$PROJECT_DIR" ]; then
    mkdir -p "$PROJECT_DIR"
    cp -r "$ROOT_DIR"/. "$PROJECT_DIR/"
fi
cd "$PROJECT_DIR"

# ── 4. Создаём рабочие папки ─────────────────────────────────────────────
echo "[4/5] Создание рабочих папок..."
mkdir -p output logs
chmod 755 output logs
echo "      OK"

# ── 5. Права на исполняемые файлы ────────────────────────────────────────
echo "[5/5] Установка прав на скрипты..."
chmod +x scripts/*.sh
chmod +x entrypoint.sh
echo "      OK"

echo ""
echo "  Установка завершена."
echo "  Следующий шаг: bash scripts/deploy.sh"
echo "============================================="
