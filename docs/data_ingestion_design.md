# Проектный дизайн слоя загрузки данных

## Архитектура слоя загрузки данных

Цель: добавить отдельный слой `data ingestion` как обертку над текущей реализацией, не меняя внешний интерфейс и поведение существующих модулей `utils/*.py`, сценариев `scripts/*.sh` и основных точек формирования бюллетеней `forecast_morning.py` / `forecast_evening.py`.

### 1) Общая схема потока

1. `fetch_inputs.py` запускается как pre-step перед запуском `forecast_morning.py` и `forecast_evening.py` (или в отдельном cron/контейнере).
2. `fetch_inputs.py` читает параметры из `config.ini` (структура и ключи берутся из `config.example.ini`).
3. `fetch_inputs.py` вызывает подмодули:
   - `utils/downloaders/cmems_downloader.py`
   - `utils/downloaders/gfs_downloader.py`
4. Подмодули скачивают/проверяют сырье и складывают его в стандартизованные директории.
5. Существующие `utils.collect_wave_data` и `utils.collect_meteo_data` продолжают использоваться как ядро расчетов в `forecast_morning.py` и `forecast_evening.py` без изменения сигнатур.
6. Бюллетени формируются текущим пайплайном и сохраняются в `output/`, логи пишутся в `logs/`.

---

### 2) Целевая структура модулей

```text
.
├─ fetch_inputs.py
├─ utils/
│  ├─ downloaders/
│  │  ├─ __init__.py
│  │  ├─ cmems_downloader.py
│  │  └─ gfs_downloader.py
│  ├─ collect_wave_data.py          # существующий, не менять
│  ├─ collect_meteo_data.py         # существующий, не менять
│  ├─ wind_statistics.py            # существующий, не менять
│  ├─ precip_statistics.py          # существующий, не менять
│  ├─ temp_statistics.py            # существующий, не менять
│  ├─ doc_builder.py                # существующий, не менять
│  └─ email_sender.py               # существующий, не менять
├─ scripts/
│  ├─ deploy.sh
│  ├─ run_now.sh
│  ├─ status.sh
│  ├─ logs.sh
│  ├─ stop.sh
│  ├─ install.sh
│  └─ update.sh
├─ forecast_morning.py              # существующий, не менять
├─ forecast_evening.py              # существующий, не менять
├─ docker-compose.yml
├─ Dockerfile
└─ crontab
```

---

### 3) Модули и их ответственность

#### `fetch_inputs.py` (новый модуль верхнего уровня, entry point ingestion)

- **Ответственность:**
  - единая точка входа слоя загрузки данных;
  - координация загрузки CMEMS и GFS;
  - базовая оркестрация ретраев/таймаутов/проверок готовности;
  - возврат статуса готовности данных для последующего запуска бюллетеней.
- **Читает параметры из `config.example.ini` (через `config.ini`):**
  - CMEMS: секции `[SOURCES]`, `[AUTH]`, `[DOWNLOAD]`, `[FORECAST]`, `[VALIDATION]`, `[STORAGE]`, `[LOGGING]`;
  - GFS: секции `[GFS_SOURCES]`, `[GFS_AUTH]`, `[GFS_DOWNLOAD]`, `[GFS_FORECAST]`, `[GFS_VALIDATION]`, `[GFS_STORAGE]`, `[GFS_LOGGING]`;
  - общие: `[PATHS]`, `[APP]` (если нужны базовые директории/таймзона).
- **Вызывает функции из `utils/`:**
  - прямой вызов `utils.downloaders.cmems_downloader.*` и `utils.downloaders.gfs_downloader.*`;
  - может вызывать `utils.collect_wave_data.collect_wave_data` и `utils.collect_meteo_data.collect_meteo_data` в режиме smoke-check (опционально, без изменения сигнатур).
- **Читает/пишет:**
  - читает: `config.ini`, `.env` (если используется), входные каталоги источников;
  - пишет: `data/raw/cmems/`, `data/raw/gfs/`, `data/cache/`, `logs/ingestion.log`, технические маркеры готовности в `data/cache/`.

#### `utils/downloaders/cmems_downloader.py` (новый)

- **Ответственность:**
  - загрузка файлов CMEMS по динамическому пути `/yyyy/mm`;
  - выбор актуального набора файлов по окнам запуска;
  - контроль количества файлов и базовой целостности;
  - укладка и ротация файлов в целевой рабочей зоне.
- **Читает параметры из `config.example.ini`:**
  - `[SOURCES]`: `cmems_base_url`, `cmems_product_path`, `cmems_dataset_id`, `cmems_subdataset_template`, `cmems_dynamic_path_mask`;
  - `[AUTH]`: `cmems_auth_method`, `cmems_username`, `cmems_password`, `cmems_token`, `cmems_client_id`, `cmems_client_secret`, `auth_retry_enabled`, `auth_error_notify`;
  - `[DOWNLOAD]`: `download_schedule_cron`, `download_frequency_per_day`, `download_retry_count`, `download_timeout_seconds`, `replace_same_name_files`;
  - `[FORECAST]`: `forecast_days`, `files_per_cycle`, `run_window_1_start`, `run_window_1_end`, `run_window_2_start`, `run_window_2_end`, `file_name_patterns`;
  - `[VALIDATION]`: `reference_schema_path`, `required_variables`, `target_bbox`, `validate_file_date`, `crop_enabled`;
  - `[STORAGE]`: `work_dir`, `storage_dir`;
  - `[LOGGING]`: `log_level`, `alert_channel`.
- **Вызывает функции из `utils/`:**
  - `utils.collect_wave_data.collect_wave_data(base_dir=..., waves_dir=..., shapefile=..., lon_bounds=..., lat_bounds=...)` как этап валидации совместимости и проверка читаемости итоговых `.nc`.
- **Читает/пишет:**
  - читает: удаленный CMEMS endpoint, локальный shapefile (`Kasp_Sea.*`), `config.ini`;
  - пишет: сырые `.nc` в `data/raw/cmems/` (или в совместимый каталог `waves/` как publish-этап), кеш промежуточных проверок в `data/cache/cmems/`, логи в `logs/`.

#### `utils/downloaders/gfs_downloader.py` (новый)

- **Ответственность:**
  - формирование запросов к NOAA NOMADS CGI-фильтру;
  - выбор актуального цикла `00z/06z/12z/18z`;
  - скачивание GFS данных, контроль полноты forecast hours;
  - обеспечение доступности форматов `grb2` и `nc` (конвертация/повторный запрос по текущей логике процесса).
- **Читает параметры из `config.example.ini`:**
  - `[GFS_SOURCES]`: `GFS_BASE_URL`, `GFS_MODEL_PATH_TEMPLATE`, `GFS_CYCLES`, `GFS_UPDATE_FREQUENCY_PER_DAY`;
  - `[GFS_AUTH]`: `GFS_USERNAME`, `GFS_PASSWORD`, `GFS_TOKEN`;
  - `[GFS_DOWNLOAD]`: `GFS_DOWNLOAD_FREQUENCY_PER_DAY`, `GFS_DOWNLOAD_SCHEDULE_CRON`, `GFS_TIMEOUT_SECONDS`, `GFS_MAX_RETRIES`, `GFS_HTTP_RETRY_DELAY_SECONDS`;
  - `[GFS_FORECAST]`: `GFS_FORECAST_HOURS_START`, `GFS_FORECAST_HOURS_END`, `GFS_FORECAST_HOURS_STEP`, `GFS_VARIABLES`, `GFS_LEVELS`;
  - `[GFS_VALIDATION]`: `GFS_REQUIRED_FORMATS`, `GFS_ENABLE_CONVERSION_TO_NETCDF`, `GFS_CHECK_FORECAST_COMPLETENESS`, `GFS_MIN_EXPECTED_FILES`;
  - `[GFS_STORAGE]`: `GFS_WORK_DIR`, `GFS_OUTPUT_DIR`;
  - `[GFS_LOGGING]`: `GFS_LOG_LEVEL`, `GFS_ALERT_CHANNEL`.
- **Вызывает функции из `utils/`:**
  - `utils.collect_meteo_data.collect_meteo_data(base_dir=..., results_subdir=..., shapefile=..., run_date=...)` как проверка совместимости структуры и наличия требуемых переменных для downstream.
- **Читает/пишет:**
  - читает: NOAA endpoint, `config.ini`, возможные прокси/секреты из окружения;
  - пишет: сырье в `data/raw/gfs/`, конвертированные/подготовленные файлы в `data/cache/gfs/` или совместимый каталог `Meteo_Parser_2026/results/<YYYYMMDD>/`, логи в `logs/`.

#### `utils/downloaders/__init__.py` (новый)

- **Ответственность:**
  - экспорт стабильных функций загрузки (`fetch_cmems`, `fetch_gfs`) для импорта из `fetch_inputs.py`.
- **Параметры/IO:**
  - напрямую не читает/не пишет, только реэкспорт.

---

### 4) Использование существующих `utils/*.py` как ядра расчетов

- `utils.collect_meteo_data.collect_meteo_data` и `utils.collect_wave_data.collect_wave_data` остаются неизменными по сигнатуре и контракту.
- Новый ingestion-слой гарантирует, что входные директории и форматы подготовлены в ожидаемом виде до запуска `forecast_morning.py`/`forecast_evening.py`.
- Статистические и документные модули (`wind_statistics`, `precip_statistics`, `temp_statistics_*`, `doc_builder`, `email_sender`) не затрагиваются.

---

### 5) Интеграция с `scripts/*.sh`, Docker и cron

#### Вариант A (предпочтительный на 1 этапе): pre-step в том же контейнере

- Перед запуском `forecast_morning.py` и `forecast_evening.py` выполнять:
  - `python fetch_inputs.py --config /app/config.ini --target both`
  - затем уже текущий запуск бюллетеня.
- Точки интеграции:
  - `crontab`: добавить pre-step перед существующими командами;
  - `scripts/run_now.sh`: добавить опциональный pre-step перед `forecast_${TYPE}.py`.
- Преимущество: минимальные изменения операционного контура, единый лог и единое окружение.

#### Вариант B: отдельный ingestion-контейнер

- `fetch_inputs.py` выполняется в отдельном сервисе `docker-compose` по собственному расписанию.
- `forecast_*` читают уже готовые данные из общих volume.
- Преимущество: развязка по ответственности и независимое масштабирование.

---

### 6) Файлы/директории: чтение и запись по слоям

- **Ingestion (новый слой):**
  - чтение: внешние источники CMEMS/NOAA, `config.ini`, `.env`, `Kasp_Sea.*`;
  - запись: `data/raw/cmems/`, `data/raw/gfs/`, `data/cache/`, `logs/`.
- **Текущий слой бюллетеней (без изменений):**
  - чтение: `Meteo_Parser_2026/results/<YYYYMMDD>/`, `waves/`, `Kasp_Sea.*`, `config.ini`;
  - запись: `output/`, `logs/hydromet.log`, `logs/cron.log`.
- **Публикация/совместимость:**
  - ingestion после загрузки публикует данные в каталогах, совместимых с текущими `collect_*` (например, `waves/` и `Meteo_Parser_2026/results/...`) без изменения интерфейса существующих модулей.

---

### 7) Нельзя менять на первом этапе

- `forecast_morning.py`
- `forecast_evening.py`
- `utils/collect_meteo_data.py`
- `utils/collect_wave_data.py`
- `utils/wind_statistics.py`
- `utils/precip_statistics.py`
- `utils/temp_statistics.py`
- `utils/doc_builder.py`
- `utils/email_sender.py`
- все `scripts/*.sh`
- `Dockerfile`
- `docker-compose.yml`
- `crontab`

Интеграция нового слоя с этими файлами на 1 этапе:

- **Способ интеграции:** внешний вызов как pre-step (wrapper orchestration), без изменения контрактов существующих скриптов/модулей.
- **Точка запуска:** `fetch_inputs.py` вызывается отдельно (ручной запуск, cron pre-step или отдельный контейнер), после чего штатно выполняются `forecast_morning.py`/`forecast_evening.py`.

---

### 8) Этапность внедрения (без переписывания текущих модулей)

1. Добавить `fetch_inputs.py` и `utils/downloaders/*` как новую прослойку.
2. Реализовать публикацию данных в каталоги, уже ожидаемые `collect_*`.
3. Подключить pre-step в операционном запуске (сначала ручной `scripts/run_now.sh`, затем cron).
4. После стабилизации рассмотреть выделение ingestion в отдельный контейнер.
