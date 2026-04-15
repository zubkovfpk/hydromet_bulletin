# project_context.md
<!-- При начале новой сессии выполни: cat docs/project_context.md -->

## 1. Назначение проекта

Гидрометеорологический бюллетень. Автоматическая загрузка данных
GFS (NOMADS) и волновых данных CMEMS, обработка, генерация отчёта,
отправка по email.

Целевой район: Каспийское море (BoundingBox: lon 46–55, lat 42–48).
Отчёты: утренний и вечерний бюллетень в формате .docx.

## 1.1 Canonical documentation paths

**`docs/project_context.md`** — **единственный** source of truth по контексту проекта для всех агентов и сессий. Читать **только этот файл**. Любой файл с именем `project_context.md` за пределами `docs/` не актуален и должен игнорироваться.

- `docs/conversation_history.md` — история сессий, reasoning и согласованных решений.
- `docs/project_progress.md` — roadmap/прогресс по этапам.

Подробные правила работы с документацией, ветками и deferred-задачами — см. **раздел 11**.


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
| `[CMEMS_STORAGE]` | Рабочая директория и директория вывода CMEMS |
| `[GFS_SOURCES]` | NOMADS filter URL, шаблон пути модели, циклы (00z/06z/12z/18z) |
| `[GFS_DOWNLOAD]` | Расписание, timeout, retry, задержка |
| `[GFS_FORECAST]` | Шаги прогноза (hours_start/end/step), переменные и уровни для filter URL |
| `[GFS_VALIDATION]` | Форматы, флаги полноты, минимум файлов |
| `[GFS_STORAGE]` | Рабочая директория и директория вывода GFS |
| `[GFS_LOGGING]` | Уровень логирования GFS |


## 4. Статус разработки

### Реализовано и работает
- **CMEMSDownloader**: `__init__` (секции `CMEMS_SOURCES`/`CMEMS_FORECAST`), `download()` с retry + exponential backoff + `ThreadPoolExecutor` hard timeout, `_ensure_login()`, режимы `cmems_download_mode=auto|get|subset` и fallback `get() -> subset()` при S3/read-timeout сбоях.
- **GFSDownloader**: `__init__` (секции `GFS_*`), `download(date, cycle)` с retry + HTTP streaming через NOMADS filter URL. Smoke-тест: 40/40 файлов, 138.9 с.
- **Smoke-тесты**: `tests/test_smoke_downloaders.py` — все зелёные (3 теста).
- **utils-слой**: `collect_meteo_data`, `collect_wave_data`, `doc_builder`, `email_sender`, `precip_statistics`, `temp_statistics`, `wind_statistics` — реализованы (оригинальная кодовая база, конвертирована из MATLAB).
- **fetch_inputs.py**: точка входа с CLI (`--config`, `--date`, `--cycle`), валидация секций конфига, lazy-импорты для снижения риска тяжёлого старта.

### В работе
- Интеграционный тест CMEMS: `tests/test_integration_cmems.py` — **СОЗДАН, 3/3 PASSED**
  - `test_download_returns_true_for_recent_date` — PASSED
  - `test_download_creates_nc_files_in_storage_dir` — PASSED
  - `test_timeout_is_respected` — PASSED (проверяет логи retry, не wall-clock время)
- `pytest.ini` создан в корне, маркер `integration` зарегистрирован.
- Интеграционный тест GFS: `tests/test_integration_gfs.py` — создан (требует сеть).

### Не начато
- Интеграционные тесты end-to-end (полный цикл forecast → docx → email).
- Реализация `utils/validate_outputs.py` (API согласован в разделе 8, ведётся в `feature/bulletin-generation`).


## 5. Ключевые технические решения

- **CMEMS download**: `copernicusmarine.get()` оборачивается в `ThreadPoolExecutor` для hard timeout (`future.result(timeout=N)`). Без этого toolbox не прерывается по Ctrl-C/timeout.
- **Exponential backoff**: задержка между попытками = `retry_delay_seconds * 2^(attempt-1)`.
- **GFS download**: прямые HTTP GET к NOMADS filter URL с параметрами (`file`, `dir`, `var_*`, `lev_*`) через `requests.Session`, streaming по 1 МБ.
- **CMEMS auth**: поддерживает `token` (header `Authorization: Bearer`) и `password` (credentials file через `copernicusmarine.login()`). Env vars `COPERNICUSMARINE_SERVICE_USERNAME/PASSWORD` имеют приоритет.
- **Credentials**: никогда не коммитятся. `config.ini` в `.gitignore`. Только `config.example.ini` с `CHANGE_ME`.
- **Config**: `configparser.ConfigParser` (case-insensitive keys). Секции `CMEMS_*` и `GFS_*` разделены, общие `[DOWNLOAD]`/`[STORAGE]`/`[LOGGING]` — для CMEMS.
- **CMEMS fallback policy**: при S3 нестабильности предпочтителен `cmems_download_mode=subset` (HTTP-only) для повышения production-стабильности.
- **Python интерпретатор**: использовать `py` (Python Launcher для Windows) — он автоматически находит установленный Python 3.x без привязки к конкретному пути.  
  **НЕ использовать просто `python`** — в системе он указывает на Microsoft Store stub.
- **Запуск smoke-тестов** (PowerShell):
  ```powershell
  py -m pytest tests/test_smoke_downloaders.py -v
  ```
- **Запуск интеграционных тестов CMEMS** (требуют реальных credentials и сети, PowerShell):
  ```powershell
  $env:CMEMS_TEST_CONFIG="config.ini"; py -m pytest tests/test_integration_cmems.py -v -m integration -s
  ```
- **Запуск интеграционных тестов GFS** (требуют реальных credentials и сети, PowerShell):
  ```powershell
  $env:GFS_TEST_CONFIG="config.ini"; py -m pytest tests/test_integration_gfs.py -v -m integration -s
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

- **РЕШЕНО: Несогласованная структура хранилища GFS**:
  - CMEMS сохраняет файлы в `data/storage/` (финальное хранилище).
  - GFS сохраняет в `data/work/gfs/` (рабочая директория) — несоответствие назначению.
  - Часть файлов лежит в `data/work/gfs/` без подкаталогов, часть в `data/work/gfs/gfs/YYYYMMDD/` — двойной `gfs/gfs`, непоследовательно.
  - `.idx`-файлы (индексы GRIB2) не фильтруются и засоряют хранилище.
  - При параллельной загрузке возможна перезапись файлов с одинаковыми именами.
  - **Целевая структура** (исправить в следующей задаче):
    ```
    data/
    ├── work/cmems/        # временные файлы CMEMS
    ├── work/gfs/          # временные файлы GFS
    └── storage/
        ├── cmems/YYYYMMDD/
        └── gfs/YYYYMMDD/HHz/
    ```
  - **Что нужно исправить**: `gfs_downloader.py` (путь сохранения, фильтрация `.idx`), `config.example.ini` (`GFS_OUTPUT_DIR = data/storage/gfs`), привести `config.ini` в соответствие.

- **Ветки**: активны `master` и `feature/bulletin-generation`. Branch policy зафиксирована в разделе 11.2.


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
- Актуальное состояние веток проверять перед работой через `git status -b` и `git branch --all`.
- Для этапа валидации/генерации бюллетеня рабочая ветка: `feature/bulletin-generation`.

## 8. Validate Outputs Contract (agreed current session)

### 8.1 Статус и границы

- **Implemented:** ingestion-слой (`fetch_inputs.py`, `utils/downloaders/*`) завершён; текущий pipeline расчёта бюллетеней работает на `collect_meteo_data()` и `collect_wave_data()`.
- **Agreed for current session:** зафиксирован planned API и scope для `utils/validate_outputs.py` (реализация пока не начата).
- **Proposed / deferred:** фактическая интеграция guard-вызовов в `forecast_morning.py` / `forecast_evening.py` и unit-тесты в отдельной следующей задаче.

### 8.2 Planned API для `utils/validate_outputs.py`

`validate_outputs.py v1` валидирует **результаты выполнения** `collect_meteo_data()` и `collect_wave_data()`:

- `class ValidationError(Exception)` — базовое исключение валидации.
- `class StructureValidationError(ValidationError)` — отсутствуют обязательные ключи, неожиданный тип/размерность.
- `class ShapeValidationError(ValidationError)` — несовместимые shape/time-depth/spatial dimensions.
- `class DataQualityValidationError(ValidationError)` — all-NaN day layers, non-finite значения, критичные quality-аномалии.
- `class TemporalValidationError(ValidationError)` — несогласованные `start_date/end_date` и временная неконсистентность.

Функции:

- `validate_meteo_output(meteo: dict, strict: bool = True) -> list[str]`
- `validate_wave_output(wave: np.ndarray, start_date, end_date, strict: bool = True) -> list[str]`
- `validate_pipeline_outputs(meteo: dict, wave: np.ndarray, start_date, end_date, strict: bool = True) -> list[str]`
- `assert_valid_for_bulletin(...) -> None`
- `summarize_validation(warnings: list[str]) -> str`

Режимы:

- `strict=True`: нарушения уровня error приводят к исключениям и остановке шага.
- `strict=False`: нарушения фиксируются как warning-сообщения, возвращаются списком для логирования/мониторинга качества.

### 8.3 MVP scope (v1, agreed)

Обязательные проверки для v1:

- обязательные ключи в выходе `collect_meteo_data()` (`Temp`, `Rain`, `Freeze_Rain`, `Ice_Pell`, `Snow`, `Wind_Gust`, `U_wind`, `V_wind`, `Vis`);
- `ndim/shape/time-depth`:
  - `Temp`: ожидаемо `(nx, ny, 10)`,
  - суточные метеополя: `(nx, ny, 5)`,
  - `Wave`: `(nx, ny, 5)`;
- согласованность spatial dimensions (`nx, ny`) между метео-полями и wave-полем;
- корректность `start_date/end_date` (тип, порядок, базовая temporal consistency);
- отсутствие day-level слоёв, полностью заполненных `NaN`;
- отсутствие `inf/-inf` в массивах;
- `wave` zero-filled layer detection как индикатор незаполненных временных слоёв.

### 8.4 Soft checks (warning-only layer, agreed)

Проверки второго слоя, не блокирующие v1 по умолчанию:

- физические диапазоны (температура, ветер, видимость, высота волны);
- NaN ratio thresholds по переменным/дням;
- sanity checks для категориальных precipitation полей;
- horizon/date consistency warnings (если даты/горизонт выходят за ожидаемое окно, но не нарушают базовый контракт).

## 9. Deferred tasks / Future work

- **Следующий обязательный шаг после согласования реализации:** `tests/test_validate_outputs.py` (позитивные/негативные кейсы, проверка исключений и warning-режима).
- **Возможная интеграция после реализации v1:** guard-вызов(ы) в `forecast_morning.py` и `forecast_evening.py` сразу после `collect_meteo_data()` / `collect_wave_data()`.
- **Более поздний этап:** day-level validation перед `doc_builder.py` (проверка уже сформированных суточных диапазонов/текстовых артефактов).
- **Вне scope `validate_outputs.py v1`:** конвертация GFS `GRIB2 -> NetCDF`; рассматривается как отдельная задача preprocessing/normalization.

## 10. Инструкция для AI-ассистента

**При начале новой сессии:**
```bash
cat docs/project_context.md
```

**В конце каждой сессии или завершённого блока задач:**
- Обновить `docs/project_progress.md` — статус задач, диаграмма Ганта, хронология сессий.
- Обновить `docs/project_context.md` — разделы, которые изменились: структура файлов, технические решения, известные проблемы, статус веток.
- Если в сессии принимались архитектурные решения или обсуждались важные подходы — добавить краткую запись в `docs/conversation_history.md`.

**Запуск тестов:**

Терминал в Windsurf — **PowerShell**. Синтаксис env var: `$env:VAR="value"; command`.

Smoke-тесты (без сети):
```powershell
py -m pytest tests/test_smoke_downloaders.py -v
```

Интеграционные тесты CMEMS (требуют сети и credentials):
```powershell
$env:CMEMS_TEST_CONFIG="config.ini"; py -m pytest tests/test_integration_cmems.py -v -m integration -s
```

Интеграционные тесты GFS (требуют сети):
```powershell
$env:GFS_TEST_CONFIG="config.ini"; py -m pytest tests/test_integration_gfs.py -v -m integration -s
```

> Использовать `py` (Python Launcher для Windows), не `python` (Microsoft Store stub).  
> Bash-синтаксис `VAR=value command` в PowerShell **не работает**.

> Для Windsurf/Pyright интерпретатор задаётся через `.vscode/settings.json` (`python.defaultInterpreterPath`).
> `pyrightconfig.json` хранит только настройки type checking и **не** должен содержать `pythonPath`/`pythonInterpreterPath`.

**Merge feature-ветки в master:**

Всегда делать через Git Bash, **не через GitHub UI**:
```bash
git checkout master
git merge --no-ff feature/bulletin-generation -m "feat: <описание>

- пункт 1
- пункт 2"
git push origin master
```

Затем закрыть PR на GitHub вручную, если он был открыт.  
**НЕ использовать GitHub UI для merge — только Git Bash.**

**Branch discipline (обязательно):**

- Текущая работа по `validate_outputs.py` и bulletin generation ведётся в `feature/bulletin-generation`.
- `master` не использовать для прямых feature-коммитов.
- Merge в `master` только после review/согласования.

**Стиль работы:**
- Промпты для агентов Cursor/Windsurf вместо листингов кода — описывать задачу, не диктовать реализацию.
- Коммиты через Git Bash в формате Conventional Commits (`feat:`, `fix:`, `chore:`, `docs:`, `test:`).
- **`config.ini` (secrets)** — не изменять без явного разрешения пользователя. Если задача требует правки `config.ini`: сначала спросить «Разрешаешь внести изменение в `config.ini` через PowerShell?». При положительном ответе — выполнить командой. При отрицательном — описать, что и как пользователь должен добавить/изменить вручную. Шаблон — только `config.example.ini` с `CHANGE_ME`.
- Проверять имена секций конфига перед правкой загрузчиков: `CMEMS_SOURCES`, `CMEMS_FORECAST`, `GFS_SOURCES`, `GFS_DOWNLOAD`, `GFS_FORECAST`, `GFS_STORAGE`.
- Smoke-тесты: см. блок «Запуск тестов» выше.


## 11. Process Rules

### 11.1 Canonical documentation paths

`docs/project_context.md` — **единственный** source of truth по контексту проекта.

Агент **обязан читать `docs/project_context.md`** при старте сессии, **до** любых правок. Если в репозитории обнаруживается файл `project_context.md` в любом другом месте (корень, подпапки) — он не актуален и должен игнорироваться или удаляться.

| Файл | Назначение | Кто обновляет |
|------|-----------|----------------|
| `docs/project_context.md` | Архитектура, статус, решения, контракты, process rules | AI-агент в конце сессии |
| `docs/conversation_history.md` | История сессий, reasoning, ключевые решения с обоснованием | AI-агент в конце сессии |
| `docs/project_progress.md` | Roadmap и прогресс этапов (Gantt, хронология) | AI-агент при изменении плана |

> **Почему это важно.** Два агента (Windsurf и Cursor), читая разные версии `project_context.md`, могут принимать противоречивые решения, перезаписывать результаты друг друга или не знать об актуальных договорённостях. Дублирование context-файла — прямой risk для multi-agent workflow.

---

### 11.2 Branch policy

| Ветка | Назначение | Feature-коммиты |
|-------|-----------|------------------|
| `master` | Стабильная ветка; только готовый, протестированный код | **Запрещены** |
| `feature/bulletin-generation` | Текущая рабочая ветка: `validate_outputs.py`, bulletin generation | Разрешены |
| `feature/*` | Будущие отдельные фичи | Разрешены в своей ветке |

**Правила:**

- Текущий этап (`validate_outputs.py`, bulletin generation) ведётся **исключительно** в `feature/bulletin-generation`.
- Прямые feature-коммиты в `master` **запрещены**.
- Merge в `master` — только через Git Bash (`git merge --no-ff`), после явного согласования с пользователем.
- Коммиты `docs:`, `chore:`, `fix:` без незавершённого feature-кода допустимы в `master`.

---

### 11.3 Deferred-task logging policy

Всё, что **сознательно откладывается** на следующий этап, фиксируется **немедленно** — в момент принятия решения об откладывании:

1. **Обязательно**: занести в `docs/project_context.md` → раздел `## 9. Deferred tasks / Future work`.
2. **При необходимости** (если влияет на roadmap): кратко отразить в `docs/project_progress.md`.
3. **Формат**: краткое название + причина откладывания + scope/этап, на который перенесено.

**Текущие deferred items:**

- **GFS GRIB2 → NetCDF conversion / preprocessing**: не входит в `validate_outputs.py v1`; отдельная задача при переходе на unified NetCDF-pipeline.
- **Normalizing/preprocessing layer для GFS**: после v1, если прямой переход `gfs_downloader` → `collect_meteo_data` останется неудобным.
- **Downstream validation перед `doc_builder.py`**: проверка day-level диапазонов (`wind_min ≤ wind_max` и т.д.); не блокирует v1.
- **Soft quality rules**: физические диапазоны, NaN ratio thresholds, sanity checks для precipitation — warning-only layer после MVP `validate_outputs.py`.
