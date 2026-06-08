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

- `docs/adr/001-ondemand-ingestion.md` — архитектурное решение on-demand модели загрузки (X-variant, сессия 15).
  Ключевые параметры: GFS lag 6h, CMEMS lag 12h, polling interval 10 min, окно запуска до 19:00 MSK (6 ч от typical request time).
  Единая точка входа `forecast_main.py` с параметрами `--date YYYY-MM-DD --time HH:MM --tz MSK`; внутри MSK явно конвертируется в UTC.
  Старые `forecast_morning.py` / `forecast_evening.py` помечены deprecated и подлежат удалению после миграции (этап 15.E).


## 2. Структура файлов

> `data/`, `etalon_data/`, `logs/`, `config.ini` — в `.gitignore`, в репозиторий не входят.
> `data/shapefiles/` — **не** в `.gitignore`; шейп-файлы коммитятся (без реальных данных GRIB/NetCDF).

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
├─ data/
│    └─ shapefiles/
│         └─ Kasp_Sea/
│              Kasp_Sea.cpg
│              Kasp_Sea.dbf
│              Kasp_Sea.prj
│              Kasp_Sea.shp
│              Kasp_Sea.shx
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
     collect_meteo_data.py      читает GFS NetCDF (*.nc), маскировка по shp, расчёт полей  done
     collect_wave_data.py       разбор CMEMS NetCDF (hs/tp/dp), агрегация           done
     validate_outputs.py        validation layer (structure/shape/temporal/data-quality) done
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
- **`utils/validate_outputs.py`**: validation layer реализован, интегрирован в pipeline. Коммит: `c2017ff`.
- **`tests/test_validate_outputs.py`**: создан, **14/14 тестов passed**.
- **Guard-call `assert_valid_for_bulletin()`**: интегрирован в `forecast_morning.py` и `forecast_evening.py` — fail-fast до statistics-слоя и `doc_builder`.

### В работе
- В работе (S15, 2026-04-22, 13:00–19:00 MSK): unified `forecast_main.py` CLI (DT-14-V, hard-cut), email verify на боевом корпоративном SMTP (DT-14-U), docx filename convention (DT-14-T), wave empty-slice warning (DT-14-S), structured exit codes (DT-14-Y).
- **S16, 2026-05-13..14:** реализация Scenario X на уровне runner
  и ingestion слоя. Закрыты 15.D.3 (ingest_gfs.py + foundation +
  archive + manifest), 15.D.4 (deprecation legacy + DT-14-T
  filename + README), 15.E.1 (pipeline + .docx),
  15.E.2 (email + DT-14-Y exit codes), 15.E.2-fix (storage из
  config.ini), 15.E.2-robustness (event_logger safety, dry-run
  без FS-side-effect), 15.E.3 (README cleanup + docs closeout).
  DT-14-Y / DT-14-T / DT-14-Z / DT-15-A — closed.
  DT-14-U — deferred (S17.1 prerequisite + manual SMTP verify).
  DT-14-V — partial (final on hard-cut S18).
  DT-14-S — parking lot.
  Введены DT-16-1..5 (см. раздел 9).

### Не начато
- Интеграционные тесты end-to-end (полный цикл forecast → docx → email): **частично выполнены** (сессия 14) — dry-run → `.docx` пройден; осталось подтверждение доставки email (DT-14-U).


## 5. Ключевые технические решения

- **CMEMS download**: `copernicusmarine.get()` оборачивается в `ThreadPoolExecutor` для hard timeout (`future.result(timeout=N)`). Без этого toolbox не прерывается по Ctrl-C/timeout.
- **Exponential backoff**: задержка между попытками = `retry_delay_seconds * 2^(attempt-1)`.
- **GFS download**: прямые HTTP GET к NOMADS filter URL с параметрами (`file`, `dir`, `var_*`, `lev_*`) через `requests.Session`, streaming по 1 МБ.
- **CMEMS auth**: поддерживает `token` (header `Authorization: Bearer`) и `password` (credentials file через `copernicusmarine.login()`). Env vars `COPERNICUSMARINE_SERVICE_USERNAME/PASSWORD` имеют приоритет.
- **Credentials**: никогда не коммитятся. `config.ini` в `.gitignore`. Только `config.example.ini` с `CHANGE_ME`.
- **Config**: `configparser.ConfigParser` (case-insensitive keys). Секции `CMEMS_*` и `GFS_*` разделены, общие `[DOWNLOAD]`/`[STORAGE]`/`[LOGGING]` — для CMEMS.
- **CMEMS fallback policy**: при S3 нестабильности предпочтителен `cmems_download_mode=subset` (HTTP-only) для повышения production-стабильности.
- **Shapefile storage policy**: шейп-файлы (`Kasp_Sea.*`) хранятся в `data/shapefiles/Kasp_Sea/`, не в корне проекта. Путь управляется через конфиг-ключ `shapefile_dir` в секции `[General]` (`%(basedir)s/data/shapefiles`). `collect_meteo_data()` и `collect_wave_data()` получают `shapefile_dir` как явный параметр.
- **Контракт между ingestion layer и processing layer (формат данных GFS)**: ingestion layer (`gfs_downloader.py`) отвечает за скачивание GFS и **за приведение данных к формату `.nc`** перед тем, как они попадут в processing layer. Processing layer (`collect_meteo_data.py`) работает исключительно с `*.nc`-файлами и ничего не знает о формате GRIB2. Нарушение этого контракта (GRIB2 без конвертации) приводит к `FileNotFoundError` в `_discover_gfs_nc_files`. Реализация конвертации — DT-01 (закрыт, сессия 10).
- **Каноническая ориентация осей в processing layer** (сессия 11): `collect_meteo_data` читает NetCDF-переменные с размерностью `(lat=721, lon=1440)` и стекает их по оси 2. Каноническая форма данных внутри processing layer: **`(lat, lon, n_steps)` = `(721, 1440, n)`**, где ось 0 = lat, ось 1 = lon — NetCDF-стандарт. Маска акватории должна иметь форму **`(lat, lon)` = `(721, 1440)`** — совпадающую с первыми двумя осями данных. Транспонирование (`.T`) в логике построения meshgrid является MATLAB-легаси и нарушает эту ориентацию (Blocker #4, DT-10-3, закрыт).
- **CMEMS ingestion output contract** (сессия 12): `cmems_downloader.py` / `fetch_inputs.py` сохраняет волновой прогноз CMEMS (переменная `VHM0_WW`) в `{base_dir}/data/storage/cmems/{YYYYMMDD}/*.nc`. Шаблон имён файлов: `mfwamglocep_{YYYYMMDD}*.nc` (Copernicus Global Wave Analysis and Forecast — MFWAM). Привязка к `run_date` — через каталог `{YYYYMMDD}/`. Cycle CMEMS не кодируется явно в имени файла. Если данные за дату не загружены — каталог `{YYYYMMDD}/` отсутствует целиком.
- **collect_wave_data lookup contract** (сессия 12, DT-11-1): `_discover_cmems_nc_files()` выполняет **3-tier поиск** (Cursor, acbcfba): (1) flat dated dir `{cmems_root}/{run_date}/*.nc`; (2) nested glob `{cmems_root}/**/mfwamglocep_{run_date}*.nc`; (3) legacy dir `{base_dir}/{waves_dir}/*.nc`. Возвращает `(files, tried_descriptions)`. При отсутствии файлов `collect_wave_data` бросает `FileNotFoundError` с полным списком tried-paths. Разграничение: **«missing data»** = данные не загружены за дату (ни одного NC в любом tier); **«lookup mismatch»** = файлы есть на диске, но шаблон/путь не совпадает с ожидаемым. DoD DT-11-1: dry-run `forecast_morning.py --date YYYYMMDD` проходит `collect_wave_data` без `FileNotFoundError`.
- **Каноническая ориентация осей для wave-массивов — нормативное правило** (сессия 12, DT-12-1 ✅ закрыт, 75cf010): processing layer для волновых массивов оперирует формой **`(n_lat, n_lon, n_days)`** = lat-first, NetCDF-стандарт, аналогично `collect_meteo_data`. MATLAB-стиль транспонирование (`.T`) в `collect_wave_data` **ЗАПРЕЩЕНО** аналогично решению для `collect_meteo_data` (DT-10-3, закрыт). **Реализованный канонический паттерн чтения CMEMS (Вариант A, 75cf010):** `hw = np.asarray(ds.variables["VHM0_WW"][:])` возвращает `(time, lat, lon)`; 2D-срезы `H_Wave[:, :, slot] = hw[t, :, :]` напрямую заполняют буфер `(n_lat, n_lon, 40)` — без 3D transpose. Обрезка: `Hwave = H_Wave[lat_mask, :, :][:, lon_mask, :]` (без `np.ix_`). Meshgrid: `Lon, Lat = np.meshgrid(lon_crop, lat_crop)` (без `.T`). Evidence: dry-run 20260415: `Hwave=(73,109,40)`, `mask=(73,109)`, `inside=2202`.
- **Временно́й контракт wave-данных в collect_wave_data — Part 1 + Part 2 закрыты (сессия 13, DT-12-2, fffc359 + d377661)**: `start_date` и `end_date`, возвращаемые `collect_wave_data`, вычисляются как `min` и `max` по объединённому массиву всех `time_arr` из всех `.nc`-файлов, найденных 3-tier discovery (DT-11-1). **Нормативная формула Part 1:** `time_arr_all = concat(time_arr_f0, ..., time_arr_fN)`; `start_date = _hours_to_date(min(time_arr_all))`; `end_date = _hours_to_date(max(time_arr_all))`. **Part 1 реализован в fffc359 (на origin с 8e942d7)**. **Part 2 — закрыт (d377661):** `_validate_dates` переписан; `horizon_hours_actual >= forecast_hours − tol_hours`; tol_hours = 3 нормативное значение (код-реализация tol_hours = 3 — стартовая микро-задача сессии 14). Подробности — см. «Validation horizon semantics» выше. Ось wave-массива `(n_lat, n_lon, n_days)` (DT-12-1) не затрагивается. 3-tier discovery DT-11-1 не меняется.
- **CMEMS file naming** (сессия 13, нормативный; уточнён в сессии 14): имя файла CMEMS имеет формат `mfwamglocep_<forecast_dt>_R<run_dt>_(00H|12H).nc`, где `<forecast_dt>` (до `_R`) — дата и час прогнозной отсечки; `R<run_dt>_(00H|12H)` — дата и час запуска модели (UTC). **Принадлежность файлу к прогону определяется по метке `R<run_dt>`**, а не по timestamp-префиксу `<forecast_dt>`. Имя файла используется только для поиска и логов; для расчётов времени используется исключительно переменная `time` внутри `.nc`.
- **CMEMS forecast structure** (сессия 13, нормативный): 1 сутки = 24 ч = 8 прогнозных отсечек с шагом 3 ч, покрытые двумя файлами по 12 ч каждый. Файл `YYYYMMDD00`: отсечки 03, 06, 09, 12 текущих суток. Файл `YYYYMMDD12`: отсечки 15, 18, 21 текущих суток и 00 следующих. Часы запуска модели (00 и 12) **не входят** в соответствующий файл — совпадают с моментом запуска и по определению не являются прогнозными. Перекрытий по времени между файлами нет. Иерархии «основной/дополнительный» нет.
- **Time-steps внутри одного CMEMS wave `.nc`** (сессия 14, подтверждено локально): переменная `VHM0_WW` имеет форму `(time=4, lat, lon)`; `time` задан в часах от 1950-01-01 с шагом 3 часа. Таким образом один файл покрывает **12h window** как `4 × 3h`, при этом в `time` хранится 4 отсечки (span по min/max = 9h).
- **CMEMS forecast horizon** (сессия 13, нормативный): CMEMS — прогнозная модель с горизонтом ~10 суток вперёд. На любой момент `today` каталог CMEMS содержит файлы с `forecast_dt` на сегодня, завтра и далее до ~10 суток вперёд, привязанные к `R<run_dt>_00H` ближайшего запуска модели. `collect_wave_data` выбирает ближайшие доступные прогнозные файлы к целевому `run_datetime` бюллетеня. **«Догрузка большего числа файлов» (прежний Вариант 3 DT-12-2) неприменима:** CMEMS нормативно возвращает штатный набор из 4 отсечек × 12 ч × 2 файла/сутки без перекрытий.
- **Номинальный run для бюллетеня (сессия 14, фиксировано в коде 6efa10e):** для `forecast_days = 5` используется 10 файлов (шаг файлов 12h), что соответствует `10 × 12h = 120h` nominal window. Фактический span по `time` внутри первого/последнего файла может быть меньше на 3 часа из-за отсутствия часа запуска модели.
- **Time source of truth для wave-данных** (сессия 13, нормативный): единственный источник времени для расчётов — переменная `time` внутри каждого `.nc`-файла. Имя файла (`mfwamglocep_...`) для расчётов времени **не использовать**.
- **Dry-run date policy** (сессия 13, нормативный): основная dry-run дата — `today` (UTC); fallback — `today − 1` (обоснование: более выверенные модельные данные). Фиксация конкретной даты (например, `20260415`) в промптах — только как voluntary reference с явной пометкой; не является нормативным dry-run эталоном. Результаты dry-run 13.B на `20260415` признаются не верификационными.
- **Параметр горизонта прогноза forecast_hours** (сессия 13, DT-13-1, нормативный): единственный источник правды для объёма запроса CMEMS и для валидации горизонта — ключ `forecast_hours` в секции `[CMEMS_FORECAST]` конфига (единица: часы; дефолт 120 = 5 суток × 24 ч). Compat-window β: одновременно поддерживаются `forecast_hours` (новый) и `forecast_days` (deprecated); при отсутствии `forecast_hours` — fallback `forecast_days × 24` с deprecation warning в логах; удаление `forecast_days` — в sweep-сессии. CLI-override: флаг `--forecast-hours` у `forecast_morning.py` и `forecast_evening.py`; CLI перекрывает config. ✅ Реализовано (DT-13-1, коммиты 8e56709 + 8055651): `config.example.ini` содержит `forecast_hours = 120` и `forecast_days = 5` (deprecated fallback); `config.ini` (gitignored) согласован на 120; CLI `--forecast-hours` у `forecast_morning.py`/`forecast_evening.py` — CLI > config, без парсинга суффиксов; `forecast_days` остаётся deprecated fallback до sweep-сессии.
- **Validation horizon semantics** (сессия 13, DT-12-2 Part 2, нормативный, ✅ реализован d377661): `validate_outputs._validate_dates` сравнивает горизонт в часах: `horizon_hours_actual = (end_date − start_date).total_seconds() / 3600.0`; проверка `horizon_hours_actual >= forecast_hours − tol_hours`. Использование `.days` **запрещено**. **tol_hours = 3 — нормативное значение** (обоснование: CMEMS нормативно возвращает 8 отсечек × 3 ч без часа запуска модели → фактический горизонт = forecast_hours − 3ч; dry-run 20260415: 21.0h >= 24h − 3 → pass). **Текущее состояние кода (d377661):** `tol_hours = 0` по умолчанию в API; код-реализация `tol_hours = 3` — стартовая микро-задача сессии 14 (config-ключ или константа, на усмотрение реализатора). **Инспекция d377661 (14.A):** именованной константы или config-ключа со значением 3 в коде НЕТ — функции `_validate_dates`, `validate_wave_output`, `assert_valid_for_bulletin` имеют `tol_hours: int = 0` как дефолт API; логика сравнения (`horizon_hours_actual >= forecast_hours − tol_hours`) корректна и закрыта. **14.B verdict: code-шаг** — задача 14.B не является no-op; её scope: вынести 3 в `_NOMINAL_TOL_HOURS` (константа) или config-ключ `validation_tol_hours`; передавать явно через callers (`forecast_morning.py`, `forecast_evening.py`); поведение валидации при этом не меняется.
- **Validation horizon tol_hours=3 implementation (сессия 14, 104c791)**: `tol_hours = 3` вынесен в именованную константу `NOMINAL_TOL_HOURS` и используется в валидации wave-horizon как нормативный допуск (поведение соответствует согласованному правилу сессии 13).
- **GFS cycle selection — временная policy (DT-07-1, вариант B)**: при запуске `forecast_morning.py` / `forecast_evening.py` цикл GFS определяется как первый элемент из `GFS_CYCLES` в `[GFS_SOURCES]`:
  ```python
  gfs_cycle = cfg.get("GFS_SOURCES", "GFS_CYCLES", fallback="00z").split(",")[0].strip()
  ```
  Это **временное решение** в рамках адаптации processing layer (сессия 7); не является финальной policy. Финальное решение (явный `--cycle` CLI-параметр с приоритетом над конфигом) вынесено в DT-07-1 — см. раздел 9.
- **GFS storage path canon (after S16):**
  - Owner of truth для путей GFS-хранилища — `config.ini`,
    ключи `[GFS_STORAGE].GFS_OUTPUT_DIR` и `[GFS_STORAGE].GFS_ARCHIVE_DIR`.
  - Дефолт (`config.example.ini`): `data/storage/gfs` и
    `data/storage/archive/gfs`.
  - `ingest_gfs.py` (15.E.2-fix, `03c7969`) читает эти ключи и
    собирает `manifest['gfs']['storage_path']` от реального корня.
  - Текущий regex `^storage/gfs/...` в `schemas/manifest_v1.json` и
    `utils.manifest.validate_schema` рассинхронизирован с этим
    каноном; временно используется локальный guard в `ingest_gfs.py`.
  - Полная синхронизация — задача DT-16-1 (S17.1).
- **Python интерпретатор**: использовать `py` (Python Launcher для Windows) — он автоматически находит установленный Python 3.x без привязки к конкретному пути.  
  **НЕ использовать просто `python`** — в системе он указывает на Microsoft Store stub.
- **Dev environment runtime policy** (сессия 13, нормативный): на dev-машине проекта `hydromet_bulletin` **нет работающих автоматических процессов** (cron / scheduler / service). Любые запуски (`fetch_inputs.py`, `forecast_morning.py`, `forecast_evening.py`, загрузчики GFS/CMEMS, конвертеры) выполняются **ТОЛЬКО вручную** — в рамках промптов сессии или явных команд пользователя. Cron-выражения в `config.ini` (`GFS_DOWNLOAD_SCHEDULE_CRON` и подобные) — это **намеренные настройки для будущего продакшена**, не реальные задания на текущей машине. **Следствие для агентов:** при анализе логов и состояния storage **НЕ предполагать**, что какие-либо данные появились или обновились автоматически; если нет явного ручного запуска в рамках сессии — данных нет.
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

- **РЕШЕНО: Несогласованная структура хранилища GFS** (сессия 14, bd70c79): дефолтный `results_subdir` мигрирован на `data/storage/gfs` с legacy fallback; pipeline использует единый storage layout без caller overrides.

- **Ветки**: активны `master` и `feature/bulletin-generation`. Branch policy зафиксирована в разделе 11.2.


## 7. История ключевых коммитов

```
6efa10e feat(wave): enforce CMEMS R<run_date> contract, fill-value decode, nanmean
bd70c79 fix(storage): migrate meteo results_subdir default to data/storage/gfs + legacy fallback
90523af fix(dry-run): resolve run_date with CMEMS+GFS availability check
104c791 fix(validate): implement NOMINAL_TOL_HOURS=3 for wave horizon validation
8055651 feat(cli): add --forecast-hours + dry-run date policy (CMEMS-only scope)
8e56709 chore(config): forecast_days -> forecast_hours compat-window (beta)
d377661 fix(validate): validate wave horizon in hours (tol_hours)
fffc359 fix(wave): compute start/end from union(time_arr) across CMEMS files
75cf010 fix(wave): canonical axes (lat,lon,time) and remove MATLAB transposes
72c6557 fix(meteo): remove .T from meshgrid to align mask and data axes
c2017ff feat: add validate_outputs module with pipeline guard (v1)
47de5fe test(cmems): add integration tests for CMEMSDownloader with retry and timeout validation
0cb3678 feat: data ingestion layer — CMEMS + GFS downloaders
```

**Статус веток:**
- Актуальное состояние веток проверять перед работой через `git status -b` и `git branch --all`.
- Для этапа валидации/генерации бюллетеня рабочая ветка: `feature/bulletin-generation`.

## 8. Validate Outputs — Implemented API

### 8.1 Статус и границы

- **Implemented:** `utils/validate_outputs.py` реализован, протестирован (14/14 passed), интегрирован в pipeline. Коммит: `c2017ff`.
- **Implemented:** ingestion-слой (`fetch_inputs.py`, `utils/downloaders/*`) завершён; pipeline расчёта бюллетеней работает на `collect_meteo_data()` и `collect_wave_data()`.
- **Implemented:** guard-вызов `assert_valid_for_bulletin()` добавлен в `forecast_morning.py` и `forecast_evening.py` (fail-fast до statistics-слоя).

### 8.2 Реализованный API `utils/validate_outputs.py`

`validate_outputs.py v1` валидирует **результаты выполнения** `collect_meteo_data()` и `collect_wave_data()`:

- `class ValidationError(Exception)` — базовое исключение валидации.
- `class StructureValidationError(ValidationError)` — отсутствуют обязательные ключи, неожиданный тип/размерность.
- `class ShapeValidationError(ValidationError)` — несовместимые shape/time-depth/spatial dimensions.
- `class DataQualityValidationError(ValidationError)` — all-NaN day layers, non-finite значения, критичные quality-аномалии.
- `class TemporalValidationError(ValidationError)` — несогласованные `start_date/end_date` и временная неконсистентность.

Фактически реализованные функции:

- `validate_meteo_output(data, *, strict=True) -> dict`
- `validate_wave_output(wave, start_date, end_date, *, strict=True) -> dict`
- `validate_pipeline_outputs(*, meteo_data=None, wave_data=None, strict=True) -> dict`
- `assert_valid_for_bulletin(*, meteo_data=None, wave_data=None, strict=True) -> None`
- `summarize_validation(report: dict) -> str`

Функции возвращают `dict` (report), а не `list[str]`.

Режимы:

- `strict=True`: нарушения уровня error приводят к исключениям и остановке шага.
- `strict=False`: нарушения фиксируются в report, выполнение продолжается.

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

### 9.0 Session 15 — active scope (open 2026-04-22, 13:00 MSK)

**Session DoD (must):**
- **DT-14-V** — единый `forecast_main.py` в корне репо; `forecast_morning.py` / `forecast_evening.py` удалены (hard-cut, без deprecation shim); `crontab`, `docker-compose.yml`, `entrypoint.sh` синхронно обновлены в том же PR.
- **DT-14-U** — email delivery верифицирован на боевом корпоративном SMTP; артефакт: `Message-ID` в логах `email_sender` + подтверждение получения.

**Session DoD (should):**
- **DT-14-T** — filename convention `Прогноз_{cycle_ru}_{start_date:YYYYMMDD}.docx`; функция `resolve_start_date(cycle, run_hour, run_date)` + unit-тесты на границах суток MSK/UTC.
- **DT-14-S** — устранён `RuntimeWarning: Mean of empty slice` в `collect_wave_data.py`; регрессионный тест на all-NaN срезе.
- **DT-14-Y** — exit codes pipeline: `0` success, `1` validation fail, `2` ingestion fail, `3` delivery fail, `>=10` internal; смоук-тест на пустом GFS → exit 2.

**Stretch:**
- DT-14-Z — cron wrapper + archive rotation (если есть время до 19:00 MSK).

**Out of scope (→ S16+):**
- Финальный merge в `master`, полный E2E, DT-10-5 (_build_mask opt), DT-08-* (logging hygiene), DT-13-6 (full config cleanup).

**Архитектурные решения S15:**
- **CLI контракт** `forecast_main.py` (в корне репо):
python forecast_main.py --cycle {morning|evening}
--run-hour {00|06|12|18}
[--date YYYY-MM-DD] # MSK; default = today MSK
[--dry-run]
[--no-email]
- **Таймзона `--date`**: интерпретация в **MSK** (`Europe/Moscow`), явная конверсия в UTC внутри (`zoneinfo.ZoneInfo("Europe/Moscow")` → `astimezone(UTC)`) перед запросами к GFS/CMEMS.
- **Shared runner**: общая логика — в `utils/forecast_runner.py`; cycle-specific — через диспетчер по `--cycle`.
- **SMTP**: корпоративный; креды только в `config.ini` на машине оператора (в репо/логи/чат не попадают).

**Parking lot carried from S14 (scope S15):** DT-14-V, DT-14-U, DT-14-T, DT-14-S, DT-14-Y.
**Parking lot carried to S16:** DT-14-Z, DT-10-5, DT-08-* (logging), DT-13-6 (full config cleanup).

- **DT-01 — GFS GRIB2 → NetCDF conversion / preprocessing** ✅ **Закрыт (сессия 10, MVP).** Реализован Вариант A: `_convert_grib_to_netcdf` + `convert_existing` в `gfs_downloader.py`, sidecar `.nc` рядом с GRIB2, 9 переменных с правильным маппингом, `lat`/`lon` дименсии. DoD подтверждён: `collect_meteo_data` находит 40/40 `.nc` и читает все 9 переменных в dry-run `forecast_morning.py --date 20260415`.
- **DT-10-3 — Shape mismatch маски и данных** ✅ **Закрыт (сессия 11, Вариант A, 72c6557).** Удалён `.T` в meshgrid `collect_meteo_data.py`: `Lon, Lat = np.meshgrid(lon_arr, lat_arr)` (no `.T`). Маска `(721,1440)` = данные `(721,1440,n)`. `mask shape=(721,1440)`, `cells_inside=236`. DoD выполнен. Downstream-чек: ни один downstream-модуль не предполагает `(n_lon,n_lat)`. Новые тесты: `test_collect_meteo_mask_orientation.py` (2 теста passed).
- **DT-10-4** ✅ **Закрыт (сессия 11, 72c6557).** `convert_existing()` glob фильтрует `p.suffix.lower() != ".nc"` — sidecar-файлы не открываются как GRIB2. Тест: `test_convert_existing_skips_paths_with_nc_suffix_dt10_4` passed.
- **DT-10-5**: `_build_mask` Python-цикл ~25–30 с — не блокирует dry-run. **Deferred (сессия 12+)**: оптимизация через `geopandas.sjoin`/bbox Каспия остаётся follow-up при росте времени. Приоритет: low.
- **DT-11-1** ✅ **Закрыт (сессия 12, acbcfba).** CMEMS `.nc` not found — root cause: lookup mismatch (не missing data). Fix: 3-tier discovery. Evidence: `count=2`, `collect_wave_data` проходит без `FileNotFoundError`. DoD выполнен.
- **DT-12-1** ✅ **Закрыт (сессия 12, Вариант A, 75cf010)**: wave axes MATLAB-legacy. Fix: удалены `.T` у meshgrid; 3D transpose CMEMS заменён 2D-срезами `H_Wave[:,:,slot]=hw[t,:,:]`; без новых `transpose`/`ix_`; `Hwave=(73,109,40)`, `mask=(73,109)`, `inside=2202`. DoD выполнен.
- **DT-12-2** ✅ **Закрыт (сессия 13, fffc359 + d377661)**: Part 1 (fffc359): min/max по union(time_arr) в `collect_wave_data`. Part 2 (d377661): `_validate_dates` → часы, `horizon_hours_actual >= forecast_hours − tol_hours`. tol_hours = 3 нормативное значение; код-реализация tol_hours = 3 — стартовая микро-задача сессии 14. Вариант 3 rescinded.
- **DT-13-1** ✅ **Закрыт (сессия 13, 8e56709 + 8055651)**: compat-window β: приоритет `forecast_hours` → `forecast_days × 24` (deprecated warning) → 120h default; `config.example.ini` + `config.ini` согласованы на 120; CLI `--forecast-hours` (int); CLI > config.
- **DT-13-2** ✅ **Закрыт по scope (сессия 13, 8055651); insufficient for full E2E — см. DT-13-3**: `_resolve_run_date_for_dry_run`: explicit `--date` отключает fallback; без `--date` — today (UTC) → fallback today-1 → иначе `FileNotFoundError`; проверка через `_discover_cmems_nc_files` — только CMEMS (GFS не проверяется).
- **DT-13-3** ✅ **Закрыт (сессия 14, 90523af)**: date policy теперь учитывает GFS availability check + fallback today-1 при отсутствии GFS за today.
- **DT-13-4** ✅ **Закрыт (сессия 14, bd70c79 + 6efa10e)**: storage layout migration (meteo-side) + CMEMS wave contract/discovery (wave-side).
- **DT-13-6** ✅ **closed (S17, a06a47e)**: legacy/reserved keys помечены в `config.example.ini`.
- **DT-14-V** ✅ **closed (S18, `df75e2f`)**: hard-cut legacy runners, entrypoint.sh + docker-compose.yml on-demand, crontab только ingest.
- **DT-14-U**: email delivery verification — **closed (S17, 9ea704e)**.
- **DT-14-T**: `.docx` filename convention — **closed (15.D.4, `526e549`)**.
- **DT-14-S**: `RuntimeWarning: Mean of empty slice` от `nanmean` в `collect_wave_data.py` — **closed (S17, 172d1e6)**.
- **DT-14-Y**: exit code propagation в forecast runner — **closed (15.E.2, `4083d37`)**.
- **DT-14-Z** ✅ **closed (15.D.3-2, `f9fb17a`; semantics → DT-16-2)**.
- **DT-18-1** ✅ **closed (S18, `ebdbfec`)**: ingest_cmems.py с автовычислением CMEMS run параметров (run_hour, first_forecast_dt из UTC).
- **DT-16-1**: manifest.gfs.storage_path contract alignment — **closed (S17, 526af0d)**.
- **DT-16-2**: archive rotation semantics (before vs after download) — **closed (S17, 5742618)**.
- **DT-16-3**: forecast_main start_time ceil per ADR-001 — **closed (S17, 26e5c40)**.
- **DT-16-4**: strict-manifest mode in forecast_main — **closed (S17, 59fe717)**.
- **DT-16-5**: README cleanup of legacy operational commands — **closed (15.E.3, `0760a3f`)**.
- **Normalizing/preprocessing layer для GFS**: после v1, если прямой переход `gfs_downloader` → `collect_meteo_data` останется неудобным.
- **Downstream validation перед `doc_builder.py`**: day-level проверка сформированных диапазонов (`wind_min ≤ wind_max` и т.д.); не блокирует v1.
- **Soft quality rules**: физические диапазоны, NaN ratio thresholds, sanity checks для precipitation — warning-only layer после MVP.
- **DT-07-1 — явный выбор GFS cycle для bulletin generation**: перейти на CLI-параметр `--cycle` в `forecast_morning.py` / `forecast_evening.py`; целевая policy — CLI-параметр имеет приоритет над значением по умолчанию из конфига. Текущая временная policy (первый элемент `GFS_CYCLES`) сохраняется как fallback. Реализовывать **отдельной задачей / отдельным PR**, вне scope адаптации processing layer. Этап: сессия 8.
- **DT-08-1 — регистр `[Logging]` vs `[LOGGING]` в configparser**: **closed (S17, 42fb832)**.
- **DT-08-2 — одновременная запись в `hydromet.log`**: cron-пересечение morning + evening, один файл — строки могут чередоваться. Приоритет: средний. Этап: сессия 9.
- **DT-08-3 — ротация логов**: **closed (S17, 42fb832)**.
- **DT-08-4 — права `/app/logs/` в Dockerfile**: процесс не под root — `mkdir` может дать `PermissionError`. Решение: `RUN mkdir -p /app/logs && chown ...`. Приоритет: средний. Этап: сессия 9.
- **DT-08-5** ✅ **closed (S18, `e969294`)**: test_retry_on_bad_url изолирован от диска через tempfile.mkdtemp() — flaky тест стабилен.
- **DT-08-6 — unit-тест `shapefile_dir=None` fallback**: нет проверки дефолтного пути; 1 unit-тест в `tests/test_processing_layout_paths.py`. Приоритет: низкий. Этап: сессия 9.
- **DT-08-7 — keyword-only сигнатура `collect_*`**: `shapefile_dir` — второй positional-параметр; добавить `*` в сигнатуры для keyword-only принудительно. Приоритет: низкий. Этап: сессия 9.
- **DT-17-3** ✅ **closed (S18, `d8d9198`)**: CMEMS auto-trigger в polling loop forecast_main.py (_trigger_cmems_ingest, _cmems_manifest_is_ready).

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
- **docs-over-code push behavior (штатный паттерн, сессия 13):** при push docs-коммита, являющегося потомком локальных код-коммитов, git fast-forward автоматически тянет на origin все предшествующие код-коммиты. Наблюдалось в сессии 12 (`75cf010` ушёл вместе с docs `8413a67`) и в сессии 13 (`fffc359` ушёл вместе с docs `8e942d7`). Это **не нарушение** git policy, а её штатный эффект при схеме «код коммитируется локально — docs пушатся по шагам». Если в будущем нужно строгое разделение — docs вести в отдельной ветке; решение — на усмотрение пользователя, не в сессии 13.
- **Branch architecture audit (сессия 14):** `origin/feature/data-ingestion` существует, но текущий активный development (ingestion + bulletin) ведётся в `feature/bulletin-generation` (status quo, verdict A). `feature/data-ingestion` рассматривается как исторический artifact; архивирование/перенос коммитов — отдельный будущий рефакторинг.

---

### 11.3 Deferred-task logging policy

Всё, что **сознательно откладывается** на следующий этап, фиксируется **немедленно** — в момент принятия решения об откладывании:

1. **Обязательно**: занести в `docs/project_context.md` → раздел `## 9. Deferred tasks / Future work`.
2. **При необходимости** (если влияет на roadmap): кратко отразить в `docs/project_progress.md`.
3. **Формат**: краткое название + причина откладывания + scope/этап, на который перенесено.

**Текущие deferred items:**

- **DT-01 — GFS GRIB2 → NetCDF conversion**: ✅ **Закрыт (сессия 10, MVP).** Вариант A: `_convert_grib_to_netcdf` + `convert_existing` в `gfs_downloader.py`. DoD подтверждён dry-runом.
- **DT-10-3** ✅ **Закрыт (сессия 11, Вариант A)**: удалён `.T` в meshgrid, маска `(721,1440)`, `cells_inside=236`. DoD выполнен.
- **DT-10-4** ✅ **Закрыт (сессия 11)**: strict GRIB glob в `convert_existing` (`p.suffix != ".nc"`).
- **DT-10-5**: ~25–30 с не блокирует. Deferred (сессия 12+), приоритет low.
- **DT-11-1** ✅ **Закрыт (сессия 12, acbcfba)**: CMEMS `.nc` not found — root cause lookup mismatch. 3-tier discovery. `count=2` за 20260415. DoD выполнен.
- **DT-12-1** ✅ **Закрыт (сессия 12, 75cf010)**: MATLAB `.T` удален; 2D-срезы; `Hwave=(73,109,40)`, `inside=2202`. DoD выполнен.
- **DT-12-2** ✅ **Закрыт (сессия 13, fffc359 + d377661)**: Part 1: min/max union(time_arr). Part 2: `_validate_dates` → часы; tol_hours = 3 нормативное значение; код-реализация — сессия 14.
- **DT-12-2 Part 3** ✅ **Закрыт (сессия 14, fbb2830)**: проверка wave temporal contract разделена на daily span (24h) и forecast depth (120h).
- **DT-12-2 Part 4** ✅ **Закрыт (сессия 14, 6efa10e)**: CMEMS wave contract по метке `R<run_date>` + NaN init + fill-value decode + `nanmean`.
- **DT-13-1** ✅ **Закрыт (сессия 13, 8e56709 + 8055651)**: compat-window β; `forecast_hours` приоритет; CLI `--forecast-hours`; config согласованы на 120.
- **DT-13-2** ✅ **Закрыт по scope (сессия 13, 8055651)**: CMEMS-only fallback; GFS не проверяется → DT-13-3.
- **DT-13-3** ✅ **Закрыт (сессия 14, 90523af)**: dry-run date policy учитывает GFS availability check + fallback today-1.
- **DT-13-4** ✅ **Закрыт (сессия 14, bd70c79 + 6efa10e)**: meteo-side `results_subdir` migration + wave-side CMEMS contract/discovery.
- **DT-13-6** ✅ **closed (S17, a06a47e)**: legacy/reserved keys помечены в `config.example.ini`.
- **Config legacy/reserved keys (DT-13-6, решение B):** ключи `cmems_auth_method`, `cmems_token`, `cmems_subdataset_template`, `cmems_dynamic_path_mask`, `cmems_product_path` (в `[CMEMS_SOURCES]`) и `files_per_cycle` (в `[CMEMS_FORECAST]`) считаются `legacy/reserved`: присутствуют для совместимости/будущих расширений, но текущим кодом не читаются.
- **Normalizing/preprocessing layer для GFS**: после v1, если прямой переход `gfs_downloader` → `collect_meteo_data` останется неудобным.
- **Downstream validation перед `doc_builder.py`**: day-level проверка сформированных диапазонов (`wind_min ≤ wind_max` и т.д.); не блокирует v1.
- **Soft quality rules**: физические диапазоны, NaN ratio thresholds, sanity checks для precipitation — warning-only layer после MVP `validate_outputs.py`.
- **DT-07-1 — явный выбор GFS cycle**: CLI-параметр `--cycle` для `forecast_*.py`; CLI имеет приоритет над значением из `GFS_CYCLES`. Вне scope текущего change set (processing layer adaptation). Отдельная задача/PR. Этап: сессия 8.
- **DT-08-1 — регистр `[Logging]` vs `[LOGGING]`**: **closed (S17, 42fb832)**.
- **DT-08-2 — одновременная запись в `hydromet.log`**: cron-пересечение morning + evening, один файл — строки могут чередоваться. Приоритет: средний. Этап: сессия 9.
- **DT-08-3 — ротация логов**: **closed (S17, 42fb832)**.
- **DT-08-4 — права `/app/logs/` в Dockerfile**: процесс не под root — `mkdir` может дать `PermissionError`. Решение: `RUN mkdir -p /app/logs && chown ...`. Приоритет: средний. Этап: сессия 9.
- **DT-08-6 — unit-тест `shapefile_dir=None` fallback**: нет проверки дефолтного пути; 1 unit-тест в `tests/test_processing_layout_paths.py`. Приоритет: низкий. Этап: сессия 9.
- **DT-08-7 — keyword-only сигнатура `collect_*`**: `shapefile_dir` — второй positional-параметр; добавить `*` в сигнатуры для keyword-only принудительно. Приоритет: низкий. Этап: сессия 9.
