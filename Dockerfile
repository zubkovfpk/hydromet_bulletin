# ─────────────────────────────────────────────────────────────────────────────
# Dockerfile — hydromet_bulletin
# Базовый образ: Python 3.11 slim (Ubuntu 22-совместимый)
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim

# Системные зависимости:
#   cron        — планировщик задач внутри контейнера
#   libgdal-dev — нужен для geopandas / fiona
#   libhdf5-dev — нужен для netCDF4
#   tzdata      — корректная работа с часовыми поясами
RUN apt-get update && apt-get install -y --no-install-recommends \
        cron \
        libgdal-dev \
        libhdf5-dev \
        libnetcdf-dev \
        tzdata \
        && rm -rf /var/lib/apt/lists/*

# Часовой пояс сервера: UTC (скрипты сами знают своё MSK-время)
ENV TZ=UTC
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Рабочая директория
WORKDIR /app

# Сначала копируем только requirements — слой кэшируется при неизменных зависимостях
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь проект
COPY . .

# Создаём папки для результатов и логов
RUN mkdir -p /app/output /app/logs

# Устанавливаем cron-расписание:
#   09:00 MSK = 06:00 UTC
#   19:00 MSK = 16:00 UTC
COPY crontab /etc/cron.d/hydromet
RUN chmod 0644 /etc/cron.d/hydromet \
    && crontab /etc/cron.d/hydromet

# Скрипт запуска контейнера
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
