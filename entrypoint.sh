#!/bin/bash
# entrypoint.sh — точка входа контейнера
# Запускает cron в фоне и держит контейнер живым через tail на лог.

set -e

# Создаём папки на случай первого запуска с чистым volume
mkdir -p /app/output /app/logs

# Инициализируем лог-файл (иначе tail -f упадёт)
touch /app/logs/hydromet.log /app/logs/cron.log

echo "$(date '+%Y-%m-%d %H:%M:%S')  INFO  Контейнер запущен. Cron активирован."

# Запускаем cron daemon
cron

# Держим контейнер живым — транслируем оба лога в stdout Docker
# (это позволяет смотреть логи через: docker-compose logs -f)
tail -f /app/logs/hydromet.log /app/logs/cron.log
