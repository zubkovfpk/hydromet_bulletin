# project_context.md
<!-- При начале новой сессии выполни: cat docs/project_context.md -->

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
│  requirements.txt            зависимости Python
│  windsurf.rules.md           правила редактирования для AI
│
├─ docs/
│    Collecting_GFS_weather_data.md       бизнес-логика загрузки GFS
│    Collecting_ocean_disturbance_data.md бизнес-логика загрузки CMEMS
│    data_ingestion_design.md             архитектура слоя ingestion
│    project_progress.md                 прогресс разработки (Mermaid)
│    Training_Windsurf&Cursor.md         инструкции по работе с AI-агентами
│    project_context.md         контекст проекта для AI-ассистента
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
| `[GFS_SOURCES]` | NOMADS filter URL, шаблон пути модели, циклы (00z/06z/12z/18z) |
| `[GFS_DOWNLOAD]` | Расписание, timeout, retry, задержка |
| `[GFS_FORECAST]` | Шаги прогноза (hours_start/end/step), переменные и уровни для filter URL |
| `[GFS_VALIDATION]` | Форматы, флаги полноты, минимум файлов |
| `[GFS_STORAGE]` | Рабочая директория и директория вывода GFS |
| `[GFS_LOGGING]` | Уровень логирования GFS |


## 4. Статус разработки

### Реализовано и работает
- **CMEMSDownloader**: `__init__` (секции `CMEMS_SOURCES`/`CMEMS_FORECAST`), `download()` с retry + exponential backoff + `ThreadPoolExecutor` hard timeout, `_ensure_login()`.
- **GFSDownloader**: `__init__` (секции `GFS_*`), `download(date, cycle)` с retry + HTTP streaming через NOMADS filter URL. Smoke-тест: 40/40 файлов, 138.9 с.
- **Smoke-тесты**: `tests/test_smoke_downloaders.py` — все зелёные (3 теста).
- **utils-слой**: `collect_meteo_data`, `collect_wave_data`, `doc_builder`, `email_sender`, `precip_statistics`, `temp_statistics`, `wind_statistics` — реализованы (оригинальная кодовая база, конвертирована из MATLAB).
- **fetch_inputs.py**: точка входа с CLI (`--config`, `--date`, `--cycle`), валидация секций конфига.

### В работе
- Интеграционный тест CMEMS: `tests/test_integration_cmems.py` — **СОЗДАН, 3/3 PASSED**
  - `test_download_returns_true_for_recent_date` — PASSED
  - `test_download_creates_nc_files_in_storage_dir` — PASSED
  - `test_timeout_is_respected` — PASSED (проверяет логи retry, не wall-clock время)
- `pytest.ini` создан в корне, маркер `integration` зарегистрирован.

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
- **Python интерпретатор**: использовать `py` (Python Launcher для Windows) — он автоматически находит установленный Python 3.x без привязки к конкретному пути.  
  **НЕ использовать просто `python`** — в системе он указывает на Microsoft Store stub.
- **Запуск smoke-тестов**:
  ```bash
  py -m pytest tests/test_smoke_downloaders.py -v
  ```
- **Запуск интеграционных тестов CMEMS** (требуют реальных credentials и сети):
  ```bash
  CMEMS_TEST_CONFIG=config.ini py -m pytest tests/test_integration_cmems.py -v -m integration -s
  ```
- **pytest.ini** зарегистрирован в корне проекта с маркером `integration`.
- **CONFIG_PATH в тестах** читается через `os.environ.get("CMEMS_TEST_CONFIG", "config.example.ini")` — позволяет подставлять реальный `config.ini` без изменения кода.

- **Windsurf/Pyright: выбор интерпретатора (важно)**:
  - Для запуска команд в терминале использовать `py` (Python Launcher для Windows).
  - Для IDE/Pyright путь к интерпретатору фиксировать через `.vscode/settings.json` (файл в `.gitignore`):
    ```json
    {
      "python.defaultInterpreterPath": "C:\\Users\\zubko\\AppData\\Local\\Programs\\Python\\Python313\\python.exe"
    }
    ```
  - В этой сборке Windsurf Pyright `pyrightconfig.json` **не принимает** опции `pythonPath` / `pythonInterpreterPath` (ошибка `unknown config option`).
  - Предупреждение от `Python Environments` про `Default interpreter path ... could not be resolved` может появляться даже когда интерпретатор уже активен; ориентироваться на статус-бар (должно быть `Python 3.13.x`) и проверку:
    ```bash
    py -3 -c "import sys; print(sys.executable)"
    ```


## 6. Известные проблемы

- **РЕШЕНО: CMEMS зависал на S3 CloudFerro `waw3-1`** (`copernicusmarine.get()` висел на `"Listing files on remote server..."`, падал с `boto3.exceptions.RetriesExceededError` через 45+ мин).
  - Fix: `ThreadPoolExecutor` hard timeout + exponential backoff retry.
  - Результат: 3/3 интеграционных теста проходят; 2 из них завершаются за ~2 с (файлы уже кешированы).
  - **Known limitation**: `ThreadPoolExecutor` не убивает зависший поток — поток `boto3` продолжает висеть в фоне после `future.result(timeout=N)`. Это ограничение `copernicusmarine` toolbox.
  - `test_timeout_is_respected` переработан: проверяет наличие строк `"timed out after 10s"` и `"retry attempts exhausted"` в логах, а не wall-clock время.

- **Ветки**: активны `master` и `feature/data-ingestion`. Стратегия дальнейшего ветвления не определена.


## 7. История ключевых коммитов

```
47de5fe test(cmems): add integration tests for CMEMSDownloader with retry and timeout validation
XXXXXXX docs(project): add project_context.md for AI session continuity
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
- `HEAD -> master` — локальная ветка, 1 коммит впереди origin (`5d97490` не запушен)
- `origin/master` — последний запушенный коммит `0cb3678`
- `feature/data-ingestion` / `origin/feature/data-ingestion` — feature-ветка, синхронизирована


## 8. Инструкция для AI-ассистента

**При начале новой сессии:**
```bash
cat docs/project_context.md
```

**В конце каждой сессии или завершённого блока задач:**
- Обновить `docs/project_progress.md` — статус задач, диаграмма Ганта, хронология сессий.
- Обновить `docs/project_context.md` — разделы, которые изменились: структура файлов, технические решения, известные проблемы, статус веток.
- Если в сессии принимались архитектурные решения или обсуждались важные подходы — добавить краткую запись в `docs/conversation_history.md`.

**Запуск тестов:**

Smoke-тесты (без сети):
```bash
py -m pytest tests/test_smoke_downloaders.py -v
```

Интеграционные тесты CMEMS (требуют сети и credentials):
```bash
CMEMS_TEST_CONFIG=config.ini py -m pytest tests/test_integration_cmems.py -v -m integration -s
```

> Использовать `py` (Python Launcher для Windows), не `python` (Microsoft Store stub).  
> `CONFIG_PATH` в тестах управляется через `CMEMS_TEST_CONFIG` env var.

> Для Windsurf/Pyright интерпретатор задаётся через `.vscode/settings.json` (`python.defaultInterpreterPath`).
> `pyrightconfig.json` хранит только настройки type checking и **не** должен содержать `pythonPath`/`pythonInterpreterPath`.

**Merge feature-ветки в master:**

Всегда делать через Git Bash, **не через GitHub UI**:
```bash
git checkout master
git merge --no-ff feature/data-ingestion -m "feat: <описание>

- пункт 1
- пункт 2"
git push origin master
```

Затем закрыть PR на GitHub вручную, если он был открыт.  
**НЕ использовать GitHub UI для merge — только Git Bash.**

**Стиль работы:**
- Промпты для агентов Cursor/Windsurf вместо листингов кода — описывать задачу, не диктовать реализацию.
- Коммиты через Git Bash в формате Conventional Commits (`feat:`, `fix:`, `chore:`, `docs:`, `test:`).
- Не трогать `config.ini` (secrets). Шаблон — только `config.example.ini` с `CHANGE_ME`.
- Проверять имена секций конфига перед правкой загрузчиков: `CMEMS_SOURCES`, `CMEMS_FORECAST`, `GFS_SOURCES`, `GFS_DOWNLOAD`, `GFS_FORECAST`, `GFS_STORAGE`.
- Smoke-тесты: см. блок «Запуск тестов» выше.
