# Hydromet Bulletin — Python + Docker

Автоматическое формирование **Гидрометеорологического бюллетеня**
(акватория Северного Каспия) с отправкой на email по расписанию.

---

## Структура проекта

```
hydromet_bulletin/
│
├── forecast_morning.py        ← утренний бюллетень (09:00 MSK)
├── forecast_evening.py        ← вечерний бюллетень (19:00 MSK)
├── config.ini                 ← все настройки (SMTP, пути, bbox)
├── requirements.txt           ← Python-зависимости
│
├── Dockerfile                 ← образ контейнера
├── docker-compose.yml         ← запуск сервиса
├── crontab                    ← расписание внутри контейнера
├── entrypoint.sh              ← точка входа контейнера
│
├── scripts/
│   ├── install.sh             ← первичная установка на сервер
│   ├── deploy.sh              ← сборка и запуск Docker
│   ├── run_now.sh             ← ручной запуск бюллетеня
│   ├── status.sh              ← статус: контейнер, файлы, лог
│   ├── logs.sh                ← просмотр логов
│   ├── stop.sh                ← остановка контейнера
│   └── update.sh              ← обновление кода из нового архива
│
├── utils/
│   ├── collect_meteo_data.py  ← чтение NetCDF GFS → агрегация
│   ├── collect_wave_data.py   ← чтение NetCDF CMEMS → агрегация
│   ├── wind_statistics.py     ← направление ветра по румбам
│   ├── precip_statistics.py   ← тип осадков
│   ├── temp_statistics.py     ← температура день/ночь
│   ├── doc_builder.py         ← генерация .docx (замена mlreportgen)
│   └── email_sender.py        ← отправка через SMTP
│
├── matlab_original/           ← исходные .m скрипты (для справки)
│
├── Meteo_Parser_2026/         ← парсер GFS (оригинальный .exe + config)
│   └── results/YYYYMMDD/...
├── waves/                     ← NetCDF волн CMEMS (mfwamglocep_*.nc)
├── Kasp_Sea.shp + .dbf/.prj/.shx/.cpg
├── output/                    ← готовые .docx (монтируется с хоста)
└── logs/                      ← лог-файлы (монтируется с хоста)
```

---

## Быстрый старт (первый деплой)

```bash
# 1. Скопировать архив на сервер
scp hydromet_bulletin_python.zip user@SERVER_IP:/opt/
ssh user@SERVER_IP

# 2. Распаковать
cd /opt && unzip hydromet_bulletin_python.zip
cd hydromet_bulletin

# 3. Установить зависимости сервера (Docker и т.д.)
sudo bash scripts/install.sh

# 4. Собрать образ и запустить
sudo bash scripts/deploy.sh

# 5. Проверить статус
bash scripts/status.sh
```

---

## Управление сервисом

| Действие | Команда |
|---|---|
| Запустить / обновить код | `bash scripts/deploy.sh` |
| Ручной запуск бюллетеня | `bash scripts/run_now.sh morning` |
| Ручной запуск с датой | `bash scripts/run_now.sh evening 20260331` |
| Статус и последние файлы | `bash scripts/status.sh` |
| Смотреть логи live | `bash scripts/logs.sh` |
| Только лог Python | `bash scripts/logs.sh app` |
| Только лог cron | `bash scripts/logs.sh cron` |
| Последние N строк | `bash scripts/logs.sh tail 100` |
| Остановить | `bash scripts/stop.sh` |
| Остановить и удалить образ | `bash scripts/stop.sh --rm` |
| Обновить из нового архива | `bash scripts/update.sh /tmp/new.zip` |

---

## Расписание

| Бюллетень | MSK   | UTC   | cron (UTC)   |
|-----------|-------|-------|--------------|
| Утренний  | 09:00 | 06:00 | `0 6 * * *`  |
| Вечерний  | 19:00 | 16:00 | `0 16 * * *` |

Изменить расписание: отредактируйте `crontab`, затем `bash scripts/deploy.sh`.

---

## Настройка (config.ini)

`config.ini` монтируется с хоста — редактировать можно без пересборки образа.

```ini
[Email]
smtp_host = mail.hosting.reg.ru
smtp_port = 465
login     = oceanography@vizard.tech
password  = ...
recipient = адрес1@example.com, адрес2@example.com   # несколько через запятую
```

---

## Telegram-бот (подмодуль)

`telegram_bot/` — git submodule ([Beavisinc/bulletin_tg_bot](https://github.com/Beavisinc/bulletin_tg_bot)), разработан коллегой в рамках платформы VIZARD. Подключён как самостоятельный командный интерфейс: Telegram-бот на aiogram + Flask API, генерирует бюллетень по точке (lat/lon) по запросу пользователя, в отличие от основного конвейера этого репозитория (ежедневный email-бюллетень по всей акватории).

Статус: код подключен рядом, архитектурная интеграция (общий слой чтения NetCDF, единый конвейер данных для обоих интерфейсов) запланирована отдельным этапом.

```bash
# клонирование с submodule
git clone --recurse-submodules https://github.com/zubkovfpk/hydromet_bulletin.git

# инициализация submodule в уже скачанном репозитории
git submodule update --init --recursive
```

⚠️ `telegram_bot/configs/wave_downloader.conf` содержит учётные данные в открытом виде (наследие исходного репозитория) — не публиковать этот репозиторий и не давать доступ к submodule без ротации этих данных.

## Соответствие MATLAB → Python

| MATLAB | Python |
|---|---|
| `ncread(...)` | `netCDF4.Dataset` |
| `shaperead` + `inpolygon` | `geopandas` + `shapely` |
| `quantile`, `histcounts` | `numpy.quantile`, `numpy.bincount` |
| `mlreportgen.dom.*` | `python-docx` |
| `datestr` / `datenum` | `datetime` + `timedelta` |

---

## Автозапуск после перезагрузки сервера

Параметр `restart: unless-stopped` в `docker-compose.yml` обеспечивает
автоматический старт контейнера. Docker должен быть в автозапуске:

```bash
sudo systemctl enable docker
```
