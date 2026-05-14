# Hydromet Bulletin — Python + Docker

Формирование **Гидрометеорологического бюллетеня**
(акватория Северного Каспия) по запросу оператора с отправкой на email.

---

## Структура проекта

```
hydromet_bulletin/
│
├── ingest_gfs.py              ← загрузка GFS в storage/manifest (Scenario X)
├── forecast_main.py           ← основной on-demand runner бюллетеня
├── forecast_morning.py        ← deprecated (15.D.4), hard-cut в S18
├── forecast_evening.py        ← deprecated (15.D.4), hard-cut в S18
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
│   ├── run_now.sh             ← legacy wrapper; для Scenario X используйте CLI ниже
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

## Architecture

### Scenario X (ADR-001)

```
[ ingest_gfs.py ] --(storage/gfs/YYYYMMDD/HHz/)-->
[ storage/manifest.json + ingest_events.jsonl ]
                                             |
                                             v
                                    [ forecast_main.py ]
                                             |
                                             v
                                  Прогноз_YYYYMMDD_HHMM.docx
```

GFS забирается отдельно через `ingest_gfs.py`; слой forecast не скачивает
данные напрямую. `forecast_main.py` читает локальный `storage/`/manifest и
собирает бюллетень по запросу оператора в окне до 19:00 MSK.

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

## CLI Quick Start

### Ingest (GFS)

```bash
python ingest_gfs.py --cycle 2026-05-13T12Z --max-retries 12 --retry-interval-min 10
python ingest_gfs.py --dry-run
```

### Forecast (on-demand)

```bash
python forecast_main.py --date 2026-05-13 --time 18:00 --tz MSK --dry-run
```

`forecast_main.py` использует ingestion-данные из локального `storage/` и
резолвит имя выходного `.docx` по DT-14-T:
`Прогноз_{YYYYMMDD}_{HHMM}.docx`.

---

## Управление сервисом

| Действие | Команда |
|---|---|
| Запустить / обновить код | `bash scripts/deploy.sh` |
| Загрузить GFS | `python ingest_gfs.py --cycle 2026-05-13T12Z` |
| Dry-run загрузки GFS | `python ingest_gfs.py --dry-run` |
| Сформировать бюллетень | `python forecast_main.py --date 2026-05-13 --time 18:00 --tz MSK` |
| Dry-run бюллетеня | `python forecast_main.py --date 2026-05-13 --time 18:00 --tz MSK --dry-run` |
| Перезаписать существующий `.docx` | `python forecast_main.py --date 2026-05-13 --time 18:00 --tz MSK --force` |
| Сформировать без отправки email | `python forecast_main.py --date 2026-05-13 --time 18:00 --tz MSK --no-email` |
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

Scenario X — on-demand runner: на текущем этапе `ingest_gfs.py` и
`forecast_main.py` запускаются вручную оператором. Автоматизация через
cron-bridge запланирована на S18; до этого не используйте старые
morning/evening cron-команды как штатный путь запуска.

---

## Deprecation Note

`forecast_morning.py` и `forecast_evening.py` deprecated с 15.D.4. Hard-cut
запланирован на S18 по ADR-001 §11; рекомендуемая замена:
`ingest_gfs.py` для загрузки GFS и `forecast_main.py` для on-demand генерации.

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
