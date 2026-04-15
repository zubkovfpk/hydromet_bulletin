# project_context.md
<!-- При начале новой сессии выполни: cat project_context.md -->

## 1. Назначение проекта

Гидрометеорологический бюллетень. Автоматическая загрузка данных
GFS (NOMADS) и волновых данных CMEMS, обработка, генерация отчёта,
отправка по email.

Целевой район: Каспийское море (BoundingBox: lon 46–55, lat 42–48).
Отчёты: утренний и вечерний бюллетень в формате .docx.


## 2. Структура файлов

> `data/`, `etalon_data/`, `logs/`, `config.ini` — в `.gitignore`, в репозиторий не входят.

```
hydromet_bulletin/
│
│  .gitignore
│  config.example.ini          шаблон конфига с CHANGE_ME (коммитится)
│  fetch_inputs.py             точка входа слоя загрузки (CMEMS + GFS)          done
│  forecast_morning.py         генерация утреннего бюллетеня → docx → email     done
│  forecast_evening.py         генерация вечернего бюллетеня → docx → email     done
│  project_context.md          контекст проекта для AI-ассистента
│  requirements.txt            зависимости Python
│  windsurf.rules.md           правила редактирования для AI
│
├─ docs/
│    Collecting_GFS_weather_data.md       бизнес-логика загрузки GFS
│    Collecting_ocean_disturbance_data.md бизнес-логика загрузки CMEMS
│    data_ingestion_design.md             архитектура слоя ingestion
│    project_progress.md                 прогресс разработки (Mermaid)
│    Training_Windsurf&Cursor.md         инструкции по работе с AI-агентами
│
├─ matlab_original/             исходные MATLAB-скрипты (только для справки)
│    forecast_morning.m
│    forecast_evening.m
│    collect_meteo_data.m
│    collect_wave_data.m
│    precip_statistics.m
│    temp_statistics_morning.m
│    temp_statistics_evening.m
│    wind_statistics.m
│    Bulletin_example.docx
│
├─ scripts/                     shell-скрипты запуска / управления контейнером
│    deploy.sh  install.sh  logs.sh  run_now.sh  status.sh  stop.sh  update.sh
│
├─ tests/
│    test_smoke_downloaders.py  smoke-тесты init CMEMSDownloader + GFSDownloader  done
│
└─ utils/
     __init__.py
     collect_meteo_data.py      разбор GFS GRIB2, маскировка по shp, расчёт полей  done
     collect_wave_data.py       разбор CMEMS NetCDF (hs/tp/dp), агрегация           done
     validate_outputs.py        валидация выходов collect_* перед statistics-слоем   planned
     doc_builder.py             конструктор Word-документа (заголовки, стили)       done
     email_sender.py            отправка .docx по SMTP SSL/TLS (порт 465)           done
     precip_statistics.py       статистика осадков (freeze_rain, ice_pell, rain, snow) done
     temp_statistics.py         температурная статистика (min/max/mean)             done
     wind_statistics.py         преобладающее направление и диапазон скорости ветра done
     │
     └─ downloaders/
          cmems_downloader.py   загрузка волн через copernicusmarine + retry/timeout done
          gfs_downloader.py     загрузка GFS через NOMADS filter HTTP + retry        done
```


## 3. Конфигурация

Шаблон: `config.example.ini` (коммитится).
Рабочий: `config.ini` (в `.gitignore` — содержит реальные credentials).

| Секция | Что контролирует |
|--------|----------------|
| `[General]` | Дата запуска (`target_date`), базовые пути вывода |
| `[BoundingBox]` | Географический bbox целевого района (lon/lat) |
| `[Email]` | SMTP-сервер, порт, login/password, получатель |
| `[DOWNLOAD]` | Retry count, timeout, задержка между попытками, флаг перезаписи |
| `[STORAGE]` | `work_dir` (временные файлы), `storage_dir` (финальное хранилище) |
| `[LOGGING]` | Уровень логирования, канал оповещений |
| `[CMEMS_SOURCES]` | URL, product_path, dataset_id, динамическая маска пути, auth (token/password) |
| `[CMEMS_FORECAST]` | Горизонт прогноза, файлов на цикл, временны́е окна, glob-паттерны имён файлов |
| `[CMEMS_VALIDATION]` | Схема, обязательные переменные, bbox, флаг обрезки |
| `[CMEMS_STORAGE]` | `CMEMS_WORK_DIR` (рабочая директория), `CMEMS_OUTPUT_DIR` (директория вывода CMEMS) |
| `[GFS_SOURCES]` | NOMADS filter URL, шаблон пути модели, циклы (00z/06z/12z/18z) |
| `[GFS_DOWNLOAD]` | Расписание, timeout, retry, задержка |
| `[GFS_FORECAST]` | Шаги прогноза (hours_start/end/step), переменные и уровни для filter URL |
| `[GFS_VALIDATION]` | Форматы, флаги полноты, минимум файлов |
| `[GFS_STORAGE]` | Рабочая директория и директория вывода GFS |
| `[GFS_LOGGING]` | Уровень логирования GFS |


## 4. Статус разработки

### Реализовано и работает
- **CMEMSDownloader**: `download()` с retry + exponential backoff + hard-timeout; добавлены режимы `cmems_download_mode=auto|get|subset`, fallback `get() -> subset()` при S3-ошибках и timeout-защита для `copernicusmarine.login()`.
- **GFSDownloader**: `__init__` (секции `GFS_*`), `download(date, cycle)` с retry + HTTP streaming через NOMADS filter URL. Smoke-тест: 40/40 файлов, 138.9 с.
- **Smoke-тесты**: `tests/test_smoke_downloaders.py` — все зелёные (3 теста).
- **Интеграционные тесты CMEMS**: `tests/test_integration_cmems.py` созданы и проходят (реальный `config.ini`: 3/3 PASS; отдельный тест fallback `get()->subset`: PASS).
- **utils-слой**: `collect_meteo_data`, `collect_wave_data`, `doc_builder`, `email_sender`, `precip_statistics`, `temp_statistics`, `wind_statistics` — реализованы (оригинальная кодовая база, конвертирована из MATLAB).
- **fetch_inputs.py**: точка входа с CLI (`--config`, `--date`, `--cycle`), валидация секций конфига; устранён риск тяжёлого старта за счёт lazy-импортов в `utils/__init__.py`.

### В работе
- Длительная стадия `Listing files on remote server...` в `copernicusmarine.get()` для некоторых запусков (зависит от сети/удалённого сервиса).
- Накопление статистики по стабильности режимов `auto` vs `subset` в реальном cron-цикле.

### Согласовано на текущую сессию (не реализовано)
- **`utils/validate_outputs.py`**: архитектурный контракт согласован (см. раздел 9). Реализация не начата. Точка вставки: после `collect_meteo_data()` и `collect_wave_data()`, до statistics-слоя.
- **Вызовы валидации** в `forecast_morning.py` / `forecast_evening.py`: ожидают реализации модуля.
- **`tests/test_validate_outputs.py`**: будет создан вместе с модулем.

### Не начато
- Интеграционные тесты end-to-end (полный цикл forecast → docx → email).
- Стратегия ветвления: решить, вводить ли ветку `develop` или работать в `feature/*` → `master`.


## 5. Ключевые технические решения

- **CMEMS download**: `copernicusmarine.get()` оборачивается в `ThreadPoolExecutor` для hard timeout (`future.result(timeout=N)`). Без этого toolbox не прерывается по Ctrl-C/timeout.
- **Exponential backoff**: задержка между попытками = `retry_delay_seconds * 2^(attempt-1)`.
- **GFS download**: прямые HTTP GET к NOMADS filter URL с параметрами (`file`, `dir`, `var_*`, `lev_*`) через `requests.Session`, streaming по 1 МБ.
- **CMEMS auth**: поддерживает `token` (header `Authorization: Bearer`) и `password` (credentials file через `copernicusmarine.login()`). Env vars `COPERNICUSMARINE_SERVICE_USERNAME/PASSWORD` имеют приоритет.
- **Credentials**: никогда не коммитятся. `config.ini` в `.gitignore`. Только `config.example.ini` с `CHANGE_ME`.
- **Config**: `configparser.ConfigParser` (case-insensitive keys). Секции `CMEMS_*` и `GFS_*` разделены, общие `[DOWNLOAD]`/`[STORAGE]`/`[LOGGING]` — для CMEMS.


## 9. Архитектурные решения: validate_outputs.py

### Agreed decisions

- **Назначение**: `validate_outputs.py` — модуль для проверки результатов `collect_meteo_data()` и `collect_wave_data()`. Не является частью ingestion-слоя, не проверяет сами файлы-источники.
- **Точка вставки**: сразу после вызовов `collect_*` в `forecast_morning.py` / `forecast_evening.py`, до любых statistics-модулей и inline-вычислений.
- **Принцип аддитивности**: новый файл `utils/validate_outputs.py`; существующие модули (`collect_*`, `wind_statistics`, `precip_statistics`, `temp_statistics`, `doc_builder`) не меняются.
- **Уровни серьёзности**:
  - `ValidationError(RuntimeError)` — критичная ошибка, останавливает пайплайн;
  - `ValidationWarning(UserWarning)` — некритичная аномалия, пишется в лог, выполнение продолжается.
- **Публичный контракт** (согласован, реализация не начата):
  - `validate_meteo(meteo: dict) -> None` — проверяет наличие ключей, формы массивов `(nx,ny,n_days)`, долю NaN, физические диапазоны.
  - `validate_wave(wave: ndarray, start_date, end_date) -> None` — проверяет `start_date`/`end_date` не `None`, форму `(nx,ny,5)`, отсутствие нулевых незаполненных слоёв, диапазон высоты волны.

### Deferred tasks / Next phases

- **Конвертация GFS из GRIB2 в NetCDF**: `GFS_ENABLE_CONVERSION_TO_NETCDF` уже есть в `[GFS_VALIDATION]` как флаг. Реализация конвертации — отдельная задача, не входит в v1 `validate_outputs.py`. Необходима при переходе на unified NetCDF-pipeline.
- **Downstream-проверка day-level statistics**: опциональная функция `validate_day_stats(day: dict) -> None` перед `create_bulletin_doc()` — проверяет `wind_min ≤ wind_max`, `vis_min ≤ vis_max`, `wave_min ≤ wave_max`. Отложена на после v1.
- **Normalizing/preprocessing step для GFS**: если прямой переход от download-layer (`gfs_downloader.py` → GRIB2) к `collect_meteo_data()` (ожидает NetCDF) останется неудобным — потребуется отдельный preprocessing модуль. Не входит в текущий scope.
- **Рефакторинг inline-вычислений из `forecast_*.py`**: `np.nanmax(Wind_Gust)`, `np.nanmin/nanmax(Vis)`, `np.nanmin/nanmax(HWave)` — логика разбросана по оркестратору. Вынесение в отдельные helper-функции с NaN-защитой рассматривается как следующий шаг после `validate_outputs.py`.

---

## 6. Известные проблемы

- **CMEMS: нестабильность S3-пути в `copernicusmarine.get()` (частично mitigated)**.
  - Причина: `get()` использует S3 (`s3.waw3-1.cloudferro.com`), где из внешней сети возможны read-timeout/обрывы и длинный metadata listing.
  - Что сделано: добавлены режимы `cmems_download_mode` (`auto|get|subset`), fallback `get() -> subset()` при S3 retry/read-timeout, hard-timeout на `login()` и существующий retry/backoff.
  - Текущий статус: интеграционные тесты проходят, но для production-стабильности рекомендован режим `cmems_download_mode=subset` (HTTP-only) в нестабильной сети.

- **Ветки**: активны `master` и `feature/data-ingestion`. Стратегия дальнейшего ветвления не определена.


## 7. История ключевых коммитов

```
9888ea8 (HEAD -> master) chore(config): add missing [CMEMS_STORAGE] section to config.example.ini
5d97490 fix(cmems): add retry + timeout protection to CMEMSDownloader
0cb3678 (origin/master) feat: data ingestion layer — CMEMS + GFS downloaders
e478c1d (origin/feature/data-ingestion, feature/data-ingestion) fix(fetch_inputs): update required sections to CMEMS_*/GFS_* pattern
a161f2c test(smoke): fix attribute names after gfs_downloader refactor
6eefb07 docs: update project progress after session 3
a289908 chore: fix .gitignore for data dirs, add copernicusmarine to requirements
0f91038 fix(cmems): update section names to CMEMS_SOURCES/CMEMS_FORECAST
6087377 chore(config): sync config.example.ini with current structure
548137d fix(gfs): rewrite downloader to use NOMADS filter URL via requests
7c9d352 docs: add project progress tracking with Mermaid diagrams
00ceed4 fix: GFS direct URL, CMEMS copernicusmarine toolbox, silent login
ad6f9e2 Add smoke tests for CMEMSDownloader, GFSDownloader init and fetch_inputs import
485cb10 Implement GFSDownloader.download() with URL build, retry, validation, completeness check
877e5d3 Implement CMEMSDownloader.download() — move config reads to __init__, eliminate redundancy
92dbf0f Add fetch_inputs entry point and downloaders skeleton (CMEMS + GFS)
7438bda Add data ingestion architecture, GFS docs and update Windsurf rules
e92d3ea Extend config.example.ini with GFS parameters
c82607c Ignore local etalon_data samples
4adb86e Add data ingestion config example and docs
6345d8e Update gitignore for etalon NetCDF files
be11493 Add Windsurf rules for secrets and configs
7632f2b Update gitignore for matlab_original docs
d63ae3a Baseline hydromet bulletin project (Python + Docker)
```

**Статус веток:**
- `HEAD -> master` == `origin/master` — синхронизированы (последний коммит `9888ea8` запушен)
- `feature/data-ingestion` / `origin/feature/data-ingestion` — feature-ветка, синхронизирована


## 8. Инструкция для AI-ассистента

**При начале новой сессии:**
```bash
cat project_context.md
```

**Стиль работы:**
- Промпты для агентов Cursor/Windsurf вместо листингов кода — описывать задачу, не диктовать реализацию.
- Коммиты через Git Bash в формате Conventional Commits (`feat:`, `fix:`, `chore:`, `docs:`, `test:`).
- Не трогать `config.ini` (secrets). Шаблон — только `config.example.ini` с `CHANGE_ME`.
- Проверять имена секций конфига перед правкой загрузчиков: `CMEMS_SOURCES`, `CMEMS_FORECAST`, `GFS_SOURCES`, `GFS_DOWNLOAD`, `GFS_FORECAST`, `GFS_STORAGE`.
- Smoke-тесты запускать из корня: `python -m pytest tests/test_smoke_downloaders.py -v`.
