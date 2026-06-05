
# ADR-001: On-demand ingestion + bulletin generation (Scenario X)

Status: Accepted (Session 15, 2026-04-22)

Deciders: Оператор проекта, Comet

Scope: Целевая production-архитектура hydromet_bulletin. Заменяет cron-driven встроенный ingestion образца S1–S14.

Supersedes: implicit architecture of forecast_morning.py / forecast_evening.py with embedded ingestion (S1–S14).

Related: DT-14-V (переформулирован), DT-14-T (filename — расширен минутами), DT-14-U (email verify — переезжает в S18), DT-14-S, DT-14-Y, DT-15-AI-1 (AI-scheduler), DT-15-ADR-GOV-1 (governance).

## 1. Context и проблема

До S14 бюллетень строился через два скрипта (forecast_morning.py, forecast_evening.py), каждый из которых внутри себя качал свежие GFS + CMEMS, обрабатывал и генерил .docx. Это — cron-driven монолит с встроенной загрузкой.

Проблемы такой архитектуры при переходе к целевому сценарию:

Latency: пользовательский запрос «дай бюллетень сейчас» ждёт 2–5 минут пока скачаются данные. Недопустимо.

Связанность отказов: один сбой CMEMS ломает и GFS-pipeline, и генерацию.

Нет единой точки правды о свежести данных: каждый запуск качает «на удачу».

GFS и CMEMS обновляются с разной частотой и разным lag: GFS 4×/сутки (6h интервал), CMEMS 1×/сутки (lag 12h). Одно расписание для двоих — всегда компромисс.

Нет основы для обучения умного расписания: события poll_attempt / success / failure нигде не записываются систематически.

## 2. Принятое решение (Scenario X)

Разделить систему на три независимых компонента:
┌──────────────────────────────────────────┐
│   INGESTION LAYER (background pollers)   │
│   - ingest_gfs.py   (каждые 6h + retry)  │
│   - ingest_cmems.py (каждые 24h + retry) │
│   - пишут в storage/ и manifest.json     │
│   - пишут события в ingest_events.jsonl  │
└──────────────────┬───────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────┐
│   STORAGE LAYER                          │
│   storage/cmems/… storage/gfs/…          │
│   storage/manifest.json                  │
│   storage/archive/ (24h-back, 48h-back)  │
└──────────────────┬───────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────┐
│   FORECAST LAYER (on-demand)             │
│   forecast_main.py --request-time ...    │
│   - читает manifest.json                 │
│   - выбирает свежие GFS+CMEMS            │
│   - генерит .docx                        │
│   - отправляет email                     │
└──────────────────────────────────────────┘

Ключевые свойства:

Компоненты независимы. Ingestion падает — forecast работает на прошлых данных (с пометкой о lag). Forecast падает — данные продолжают накапливаться.

forecast_main.py никогда не качает данные. Его работа — читать manifest, выбирать годные, рендерить .docx, отправлять email.

ingest_*.py никогда не читают manifest (только пишут). Их работа — получить свежий пакет из источника, положить в storage, обновить manifest.

Единственная точка связи между слоями — storage/manifest.json (с атомарной записью) плюс собственно файлы в storage/.

Единый бюллетень, без morning/evening: сценарий X отменяет разделение на утренний/вечерний. Бюллетень формируется по запросу (CLI сейчас, HTTP API в S20+). Первый прогнозный час = ceil(request_time, 1h) в MSK, с защитой от попадания на границу часа: если request_time.minute == 0 and request_time.second == 0, то start_time = request_time + 1h (иначе бюллетень начинался бы в уже наступивший момент). Окно = 24 часа.

## 3. Storage layout и retention policy

### 3.1 Директории

Фиксируем существующую раскладку (не меняем — она уже создана и согласована со структурой источников):
storage/
├── cmems/
│   └── GLOBAL_ANALYSISFORECAST_WAV_001_027/
│       └── cmems_mod_glo_wav_anfc_0.083deg_PT3H-i_202411/
│           └── YYYY/MM/<files>.nc
├── gfs/
│   └── YYYYMMDD/
│       ├── 00z/<files>
│       ├── 06z/<files>
│       ├── 12z/<files>
│       └── 18z/<files>
├── manifest.json              # единая точка правды о свежести
├── archive/                   # только 2 слота отката на источник: 24h-back и 48h-back
│   ├── cmems/
│   └── gfs/
└── work/                      # временные файлы обработки (как сейчас)
Решение по CMEMS-пути: длинная Copernicus-style раскладка (GLOBAL_ANALYSISFORECAST_WAV_001_027/...) сохраняется — она соответствует идентификаторам продукта Copernicus Marine и упрощает миграцию на другие CMEMS-продукты в будущем.

### 3.2 Retention / archive — правило downloader'а (нормативное)

Перед началом каждой загрузки downloader выполняет последовательность:

Move current → archive. Текущие файлы в storage/cmems/…/YYYY/MM/ или storage/gfs/YYYYMMDD/HHz/ переносятся в archive/ со слот-меткой 24h-back. Предыдущий 24h-back сдвигается в 48h-back. То что было в 48h-back — удаляется безвозвратно, но только после того, как новая ротация прошла без ошибок (атомарность на уровне файловой системы — через временные имена).

Download new. Скачивание нового пакета в основную раскладку.

On success: удалить слот 48h-back (он теперь реально лишний), в архиве остаётся один слот — свежевытесненный 24h-back.

On failure: новый пакет не появляется; в архиве остаются два слота (24h-back, 48h-back) — из любого можно быстро восстановиться, скопировав обратно в основную раскладку.

Почему так: расчётные данные исторической ценности не имеют. Держать всё — бессмысленно (storage распухнет). Но два слота на откат — страховка на случай, если один из них битый.

Инвариант (проверяется тестом в S16):

После успешной загрузки: в archive/{source}/ ровно один слот на источник.

После неудачной загрузки: в archive/{source}/ ровно два слота.

Три и больше слотов — баг ротации, падать с exit code 2.

### 3.3 Output .docx

Файлы бюллетеней (output/) не архивируются и не ротируются в S16–S18. Решение по ротации — отдельный ADR в S20+ (кандидаты: S3, БД).


## 4. Manifest.json — единая точка правды

Путь: storage/manifest.json.

### 4.1 Схема
{
  "schema_version": "1.0",
  "updated_at": "2026-04-22T16:42:19Z",
  "gfs": {
    "latest_successful_cycle": "2026-04-22T12Z",
    "latest_successful_fetched_at": "2026-04-22T16:42:18Z",
    "latest_successful_source_timestamp": "2026-04-22T12:00:00Z",
    "storage_path": "storage/gfs/20260422/12z/",
    "archive_slots": {
      "24h-back": {"id": "2026-04-22T06Z", "path": "storage/archive/gfs/20260422/06z/"},
      "48h-back": {"id": "2026-04-21T18Z", "path": "storage/archive/gfs/20260421/18z/"}
    }
  },
  "cmems": {
    "latest_successful_snapshot": "2026-04-22",
    "latest_successful_fetched_at": "2026-04-22T09:11:07Z",
    "latest_successful_source_timestamp": "2026-04-22T00:00:00Z",
    "storage_path": "storage/cmems/GLOBAL_ANALYSISFORECAST_WAV_001_027/cmems_mod_glo_wav_anfc_0.083deg_PT3H-i_202411/2026/04/",
    "archive_slots": {
      "24h-back": {"id": "2026-04-21", "path": "storage/archive/cmems/GLOBAL_ANALYSISFORECAST_WAV_001_027/cmems_mod_glo_wav_anfc_0.083deg_PT3H-i_202411/2026/04/21/"},
      "48h-back": {"id": "2026-04-20", "path": "storage/archive/cmems/GLOBAL_ANALYSISFORECAST_WAV_001_027/cmems_mod_glo_wav_anfc_0.083deg_PT3H-i_202411/2026/04/20/"}
    }
  }
}
### 4.2 Контракт чтения/записи

manifest.json — единственный источник правды для forecast_main.py о том, что доступно в storage и насколько свежо.

Запись манифеста — атомарная: сначала manifest.json.tmp, затем os.replace(tmp, manifest.json). Никогда не редактируем in-place (иначе при падении downloader'а между двумя json.dump-write'ами получим повреждённый манифест).

Поле updated_at обновляется при каждой успешной записи.

forecast_main.py только читает манифест; записывают только ingest_*.py.

При повреждении манифеста (невалидный JSON, отсутствие обязательных полей schema_version, gfs.latest_successful_*, cmems.latest_successful_*) — forecast_main.py падает с exit code 2 («ingestion data unavailable or manifest corrupted»).

При отсутствии манифеста (первый запуск на чистом volume) — то же: exit 2 с подсказкой «run ingest_gfs.py and ingest_cmems.py first».

### 4.3 Валидация схемы

В S16 вводится модуль utils/manifest.py с функциями:

read_manifest(path) -> dict — читает и валидирует схему. Падает с ManifestCorruptedError при несоответствии.

write_manifest(path, data) — атомарная запись с валидацией на входе.

validate_schema(data) -> list[str] — возвращает список ошибок (пусто = ok).

JSON Schema формально описывается в schemas/manifest_v1.json в S16 (для возможности валидации снаружи, например через jsonschema).

## 5. CLI-контракты трёх компонентов

### 5.1 ingest_gfs.py
python ingest_gfs.py
    [--cycle YYYY-MM-DDTHHZ]    # explicit cycle override; default = ближайший прошедший GFS cycle
    [--max-retries N]           # default = 12 (2 часа опроса каждые 10 мин)
    [--retry-interval-min M]    # default = 10
    [--force]                   # игнорировать «уже есть этот cycle в manifest»
    [--dry-run]
Поведение:

Определить target_cycle: если не передан — floor(now_utc, 6h) к ближайшему прошедшему из {00, 06, 12, 18} UTC. Пример: в 14:00 UTC → 2026-04-22T12Z.

Прочитать manifest: если gfs.latest_successful_cycle == target_cycle и не --force → exit 0 («nothing to do»).

Actuality window = 6 часов от issue_time cycle'а. После 6 часов считается «устаревшим» и downloader должен переключиться на следующий cycle.

Poll loop: попытка скачать → при not_ready (HTTP 404 или отсутствие ключевых переменных) ждать retry-interval-min минут и повторить. Максимум max-retries попыток.

При успехе: move current storage slot → archive (см. §3.2), download, write files, update manifest (атомарно), удалить 48h-back слот в archive.

При неудаче после всех ретраев: exit code 2. В archive остаются 2 слота (откат возможен).

Каждая попытка и каждый этап пишутся событиями в ingest_events.jsonl (см. §7).

### 5.2 ingest_cmems.py
python ingest_cmems.py
    [--snapshot YYYY-MM-DD]     # explicit snapshot override; default = сегодня UTC
    [--max-retries N]           # default = 24 (4 часа опроса каждые 10 мин)
    [--retry-interval-min M]    # default = 10
    [--force]
    [--dry-run]
Поведение аналогично §5.1 с адаптацией:

--snapshot YYYY-MM-DD вместо --cycle.

Default --max-retries = 24 (CMEMS публикуется с большим разбросом по времени — держим окно опроса 4 часа).

Actuality window = 12 часов от полуночи UTC даты snapshot'а.

Остальное (archive rotation, manifest update, событийное логирование) — по тем же правилам.

### 5.3 forecast_main.py (on-demand)
python forecast_main.py
    [--request-time "YYYY-MM-DD HH:MM"]   # MSK; default = datetime.now(Europe/Moscow)
    [--no-email]
    [--dry-run]
    [--output-dir PATH]                   # default = output/
    [--force]                             # перезаписать существующий .docx
Поведение:

Принять request_time в MSK (ISO-формат YYYY-MM-DD HH:MM). Конвертировать в UTC через zoneinfo.ZoneInfo("Europe/Moscow") → astimezone(UTC).

Вычислить start_time_utc: если request_time.minute == 0 and request_time.second == 0, то start_time_utc = request_time_utc + timedelta(hours=1); иначе start_time_utc = ceil(request_time_utc, 1h). Примеры: 14:35 → 15:00; 15:17 → 16:00; 15:00:00 → 16:00.

Окно прогноза = [start_time_utc, start_time_utc + timedelta(hours=24)].

Прочитать storage/manifest.json через utils/manifest.read_manifest().

Проверить freshness (см. §6.4):

GFS latest_successful_source_timestamp покрывает окно прогноза через доступные forecast hours.

CMEMS latest_successful_source_timestamp не старше 24h от start_time_utc.

При недостатке — exit 2 с читаемой ошибкой: "CMEMS snapshot too old: last is 2026-04-20T00:00:00Z, need ≥ 2026-04-21T15:00:00Z".

Сгенерить .docx (путь по §5.4), отправить email (если не --no-email), exit 0.

forecast_main.py не качает данных. Если их нет — это не его зона ответственности.

### 5.4 Filename convention (DT-14-T, обновлённая под X)

Базовое имя:
Прогноз_{start_date:YYYYMMDD}_{start_time:HHMM}.docx

Примеры:

Запрос 22.04.2026 14:35 MSK → start = 15:00 MSK → Прогноз_20260422_1500.docx.

Запрос 22.04.2026 15:17 MSK → start = 16:00 MSK → Прогноз_20260422_1600.docx.

Запрос 22.04.2026 15:47 MSK → start = 16:00 MSK → коллизия с предыдущим.

Правило коллизии: если файл с базовым именем уже существует и не передан --force:
Прогноз_{start_date}_{start_time}_req-{request_time:HHMM}.docx

Пример коллизии: Прогноз_20260422_1600_req-1547.docx.

Обоснование включения минут: два пользовательских запроса в один час могут попадать на один start_time, но быть сделаны на разных снапшотах данных (если между ними прошло обновление источника). Полный differentiator = (start_time, request_time).

Инвариант: forecast_main.py никогда не перезаписывает существующий .docx без --force.

## 6. Lag-политика (нормативная)

### 6.1 GFS actuality window — 6 часов

GFS-cycle считается «актуальным» 6 часов от его issue_time (т.е. до выпуска следующего cycle'а: 00→06, 06→12, 12→18, 18→00+1). После 6 часов ingestion-layer переключается на опрос следующего cycle'а (старый больше не обновляем).

Обоснование: GFS публикуется 4 раза в сутки с интервалом 6 часов. Держать cycle «живым» дольше интервала выпуска — бессмысленно (есть более свежий). Короче интервала — теряем cycle, который пришёл с задержкой публикации NOAA.

### 6.2 CMEMS actuality window — 12 часов

CMEMS-snapshot считается «актуальным target'ом» в течение 12 часов от полуночи UTC даты snapshot'а. Это означает: если ingest_cmems.py запущен без явного --snapshot после 12:00 UTC, target по умолчанию — следующий день, а не текущий (который уже считается «слишком старым, чтобы опрашивать»).

Важное разделение понятий:

1. Ingestion retry window = max_retries × retry_interval_min (для CMEMS default: 24 × 10 мин = 4 часа). Это сколько времени downloader ретраит один target после запуска.
2. Actuality window (12 часов) = после этого времени target считается «просроченным», и при следующем запуске downloader берёт более свежий target.
3. Forecast freshness threshold (24 часа, §6.4) = сколько времени forecast_main.py готов использовать уже загруженные данные.

Все три параметра независимы и служат разным целям.

Обоснование 12h: CMEMS Copernicus Marine-продукт GLOBAL_ANALYSISFORECAST_WAV_001_027 публикуется один раз в сутки с типичной задержкой 8–11 часов от номинального timestamp'а. 12 часов — разумная верхняя граница; после неё логичнее переключиться на следующий день, чем продолжать ждать «вчерашний».

### 6.3 Polling policy

После истечения actuality window — опрос каждые 10 минут, пока не появится новый пакет или не исчерпаются ретраи (--max-retries).

10 минут — базовая константа. Она зафиксирована здесь как baseline на S16–S19. В S20+ заменяется обученным расписанием через DT-15-AI-1 (AI-scheduler, см. §7.4).

Обоснование выбора 10 мин: компромисс между нагрузкой на NOAA/Copernicus (не DDoS'им) и latency обнаружения нового пакета (не ждём час сверх необходимого). При 10-мин интервале средний over-wait = 5 мин — приемлемо.

### 6.4 Freshness requirement для forecast_main.py

Когда пользователь запрашивает бюллетень, forecast_main.py проверяет данные в storage:

Hard thresholds (exit 2 при нарушении):

GFS: (start_time_utc - latest_gfs_issue_time) > timedelta(hours=24) — данные слишком старые, "GFS data too stale". Проверка покрытия окна через max_forecast_hours не нужна: GFS всегда даёт прогноз до +384h, что тривиально покрывает 24h-окно при любом cycle, прошедшем hard threshold.

CMEMS: (start_time_utc - latest_cmems_source_timestamp) > timedelta(hours=24) — "CMEMS snapshot too old".

Soft warnings (не блокируют, пишутся в лог и footnote в .docx):

GFS старше 12 часов от start_time → пометка "degraded GFS freshness".

CMEMS старше 18 часов от start_time → пометка "degraded CMEMS freshness".

Обоснование soft-thresholds: бюллетень на основе GFS 12-часовой давности всё ещё полезен (forecast остаётся валидным), но пользователь должен видеть предупреждение. Hard threshold = 24h — граница, за которой качество прогноза заметно деградирует.

### 6.5 Сводная таблица
| Параметр                      | GFS                        | CMEMS           | Примечание                       |
| ----------------------------- | -------------------------- | --------------- | -------------------------------- |
| Публикация источника          | 4×/сутки (00/06/12/18 UTC) | 1×/сутки        |                                  |
| Actuality window              | 6 ч                        | 12 ч            | переключение на следующий slot   |
| Poll interval после actuality | 10 мин                     | 10 мин          | baseline; заменится AI-scheduler |
| Default --max-retries         | 12 (2 ч опроса)            | 24 (4 ч опроса) |                                  |
| Forecast hard threshold       | 24 ч                       | 24 ч            | exit 2                           |
| Forecast soft warning         | > 12 ч                     | > 18 ч          | footnote в .docx                 |

## 7. AI-scheduler logging (DT-15-AI-1 — foundation events)

Цель. Накапливать события poll_attempt / ingest_* / archive_rotation с первого дня S16, чтобы в S20+ обучить модель умного расписания опроса. Без систематического логирования учить будет не на чём.

### 7.1 Путь и расположение

Формат: JSONL (JSON Lines — один JSON-объект на строку).

Файл: ingest_events.jsonl.

Расположение: volume вне git-репо.

В Docker: mount ./ingest_events/:/var/lib/hydromet/ingest_events/.

Путь внутри контейнера: /var/lib/hydromet/ingest_events/ingest_events.jsonl.

На хосте: ./ingest_events/ingest_events.jsonl.

.gitignore: добавить ingest_events/ в .gitignore в S16.

Ротация: daily, gzip старых файлов — ingest_events.jsonl.2026-04-22.gz.

Retention: 365 дней (год событий — минимум для обучения сезонных паттернов доступности NOAA/Copernicus).

### 7.2 Схема события (schema_version 1.0)

Обязательные поля:
| поле                       | тип                 | описание                                                                                                     |
| -------------------------- | ------------------- | ------------------------------------------------------------------------------------------------------------ |
| ts                         | ISO 8601 UTC        | момент записи события                                                                                        |
| source                     | "gfs" \| "cmems"    | источник данных                                                                                              |
| event                      | enum                | poll_attempt / ingest_started / ingest_complete / ingest_failed / archive_rotation / manifest_update         |
| target_cycle \| target_date | string              | что пытались получить (2026-04-22T12Z для GFS, 2026-04-22 для CMEMS)                                         |
| result                     | enum                | success / not_ready / network_error / parse_error / auth_error / timeout                                     |
| http_status                | int \| null         | если применимо (для HTTP-запросов)                                                                           |
| latency_ms                 | int \| null         | время ответа сервера; null для событий без HTTP-запроса (archive_rotation, manifest_update, итоговый ingest_complete) |
| source_timestamp           | ISO 8601 UTC \| null | когда данные появились у источника (из Last-Modified header или метаданных NetCDF)                           |
| bytes_downloaded           | int \| null         |                                                                                                              |
| duration_ms                | int                 | общее время операции                                                                                         |
| user_ip_region             | string \| null      | регион исходящего IP сервера (например, "RU-MOW"). Нужен для учёта geo-эффектов на latency к NOAA/Copernicus |

Опциональные поля (для debug / будущих фичей):
| поле                 | тип    | описание                                        |
| -------------------- | ------ | ----------------------------------------------- |
| error_message        | string | краткое описание ошибки при result != "success" |
| retry_number         | int    | номер попытки в текущем poll loop (0 = первая)  |
| storage_path_written | string | куда записали файл (при event=ingest_complete)  |

### 7.3 Примеры записей

Серия попыток для GFS 12z cycle 22.04.2026 — два неудачных опроса, третий успешный, затем завершение ingest:
{"ts":"2026-04-22T16:30:00Z","source":"gfs","event":"poll_attempt","target_cycle":"2026-04-22T12Z","result":"not_ready","http_status":404,"latency_ms":342,"source_timestamp":null,"bytes_downloaded":null,"duration_ms":342,"user_ip_region":"RU-MOW","retry_number":0}
{"ts":"2026-04-22T16:40:00Z","source":"gfs","event":"poll_attempt","target_cycle":"2026-04-22T12Z","result":"not_ready","http_status":404,"latency_ms":298,"source_timestamp":null,"bytes_downloaded":null,"duration_ms":298,"user_ip_region":"RU-MOW","retry_number":1}
{"ts":"2026-04-22T16:42:18Z","source":"gfs","event":"poll_attempt","target_cycle":"2026-04-22T12Z","result":"success","http_status":200,"latency_ms":411,"source_timestamp":"2026-04-22T12:00:00Z","bytes_downloaded":15728640,"duration_ms":411,"user_ip_region":"RU-MOW","retry_number":2}
{"ts":"2026-04-22T16:42:19Z","source":"gfs","event":"archive_rotation","target_cycle":"2026-04-22T12Z","result":"success","http_status":null,"latency_ms":null,"source_timestamp":null,"bytes_downloaded":null,"duration_ms":47,"user_ip_region":"RU-MOW"}
{"ts":"2026-04-22T16:42:23Z","source":"gfs","event":"ingest_complete","target_cycle":"2026-04-22T12Z","result":"success","http_status":null,"latency_ms":null,"source_timestamp":"2026-04-22T12:00:00Z","bytes_downloaded":15728640,"duration_ms":5089,"user_ip_region":"RU-MOW","storage_path_written":"storage/gfs/20260422/12z/"}
{"ts":"2026-04-22T16:42:23Z","source":"gfs","event":"manifest_update","target_cycle":"2026-04-22T12Z","result":"success","http_status":null,"latency_ms":null,"source_timestamp":null,"bytes_downloaded":null,"duration_ms":12,"user_ip_region":"RU-MOW"}

### 7.4 Future work: DT-15-AI-1 (AI-scheduler)

Мотивация. Fixed-interval polling (10 мин, §6.3) — расточительно. NOAA/Copernicus публикуют пакеты в предсказуемое время с небольшим джиттером. Обученная модель может предсказать «момент T, после которого с вероятностью p=0.95 пакет уже доступен» и запускать первый poll ровно в T, сокращая число холостых запросов в 5–10 раз.

Подход (draft, детали — ADR-002 в S20+):

Вход: исторический ingest_events.jsonl за последние 30–90 дней.

Признаки: cycle/date target, день недели, sezon, user_ip_region, предыдущие not_ready → success переходы, latency distribution.

Выход: predicted_ready_at для следующего target + confidence.

Политика: первый poll в predicted_ready_at - 5 min, далее escalation на 10-мин baseline.

Требования к logging с первого дня (для feasibility обучения):

Ни одна попытка не теряется (durable writes, fsync после каждого append).

source_timestamp извлекается честно (а не подменяется на ts).

user_ip_region заполняется автоматически при старте ingest-процесса (через внешний lookup IP → region, кэшируется в памяти процесса).

### 7.5 Governance

Любой новый ingest_*.py-скрипт обязан писать события. Без событий — не мержим в master.

Формат схемы заморожен на schema_version: "1.0" до ADR-002. Изменения — только через новый ADR с schema_version: "2.0" и скриптом миграции исторических событий.

В S16 создаётся модуль utils/event_logger.py с функцией log_event(source, event, **fields), обязательной к использованию во всех ingest-скриптах.

## 8. Cron schedule (S16+)

Расписание в целевой архитектуре:
# ───────────────────────────────────────────────────────────────
# hydromet_bulletin — cron schedule (S16+, Scenario X)
# MSK = UTC+3
#
# Формат: минута час день месяц день_недели команда
# ───────────────────────────────────────────────────────────────

# GFS: 4×/сутки, запуск через 30 мин после каждого cycle issue time
# (с запасом на типичную задержку публикации NOAA ~15–25 мин)
30 0,6,12,18 * * * root cd /app && /usr/local/bin/python ingest_gfs.py >> /var/lib/hydromet/ingest_events/cron_gfs.log 2>&1

# CMEMS: 1×/сутки, запуск в 08:00 UTC (типичная задержка публикации Copernicus 8–11 ч от 00 UTC)
0 8 * * * root cd /app && /usr/local/bin/python ingest_cmems.py >> /var/lib/hydromet/ingest_events/cron_cmems.log 2>&1

# forecast_main.py в cron НЕ запускается — он on-demand (CLI сейчас, HTTP API в S20+).
# Для обратной совместимости с сегодняшним 2×/сутки email-flow — см. §8.1.

# Пустая строка в конце — обязательно для cron

### 8.1 Обратная совместимость с 2×/сутки email (bridge S16–S19)

До полноценного HTTP API (S20+) пользователи ожидают получать бюллетень по email без явного запроса — как было до S15 с forecast_morning.py / forecast_evening.py.

Решение на переходный период S16–S19: автоматический запуск forecast_main.py по расписанию через cron, но как on-demand клиент, а не как часть ingestion:
# Bridge: автоматическая генерация 2×/сутки с email-доставкой.
# После появления HTTP API в S20+ — этот блок удаляется.

# Утренний: 09:00 MSK = 06:00 UTC (будет взят GFS 00z сегодня, CMEMS сегодня если есть)
0 6 * * * root cd /app && /usr/local/bin/python forecast_main.py >> /var/lib/hydromet/ingest_events/cron_forecast.log 2>&1

# Вечерний: 19:00 MSK = 16:00 UTC (будет взят GFS 12z сегодня, CMEMS сегодня)
0 16 * * * root cd /app && /usr/local/bin/python forecast_main.py >> /var/lib/hydromet/ingest_events/cron_forecast.log 2>&1

Оба запуска — без --no-email, без --dry-run, без явного --request-time. request_time = now() MSK в момент запуска cron.

Важно: этот cron — не часть архитектуры X, это bridge. В S20+ удаляется, email-доставка становится опциональной настройкой пользовательского запроса.

OQ-11 (S18): После фиксации ceil-семантики start_time = ceil(request_time, 1h) (§2, §5.3) конкретные часы bridge-cron требуют пересмотра. Запуск в 06:00 UTC (09:00 MSK) даёт start_time = 10:00 MSK (07:00 UTC). Проверки покрытия данными:

- GFS: к 06:00 UTC доступен cycle 00z (issue 00:00 UTC, опубликован ~04:30 UTC через ingest_gfs.py в 00:30 UTC). Покрытие 07:00 UTC от 00z — forecast hour +7. Доступно.
- CMEMS: ingest_cmems.py запускается в 08:00 UTC (§8, позже утреннего bridge-cron). Значит утренний bulletin в 06:00 UTC работает на CMEMS-snapshot **вчерашнего** дня — возраст от 07:00 UTC = 31 час. Это превышает hard threshold §6.4 (24h) → bulletin не будет сгенерирован.

Варианты решения (выбор в S18):

- (a) Перенести утренний bridge-cron на 09:00 UTC = 12:00 MSK (после успеха ingest_cmems). Минус: меняет пользовательское обещание «утренний бюллетень в 09 MSK».
- (b) Перенести ingest_cmems раньше, на 05:00 UTC, и полагаться на retry loop (max_retries=24 = 4 часа опроса) до появления сегодняшнего snapshot. Минус: 4 часа холостого опроса Copernicus.
- (c) Ослабить CMEMS hard threshold до 36 часов специально для bridge-cron runs (флаг --allow-stale-cmems). Минус: снижает качество бюллетеня в утренний слот.

Вечерний bridge-cron в 16:00 UTC (19:00 MSK) проблемы не имеет: start_time = 20:00 MSK (17:00 UTC), CMEMS (загружен в 08:00 UTC) возрастом 9 часов, GFS 12z cycle (issue 12:00 UTC, забран в 12:30 UTC) возрастом 5 часов — оба в пределах soft warning thresholds.

Решение OQ-11 — отдельный коммит в S18 с выбранным вариантом и обновлением §8.1.

### 8.2 Обоснование момента запуска GFS-ingest (cycle + 30 мин)

NOAA публикует GFS cycle с типичной задержкой 15–25 минут от issue_time. Запуск ingest в cycle + 30 мин даёт окно:

Обычно: первый poll → success (http 200), пакет забран, 1 событие.

В худшем случае: первый poll → not_ready (404), запускается retry loop каждые 10 мин, по max_retries=12 = 2 часа окна опроса. Этого хватит даже на retro-задержки NOAA до 2.5 часов.

Если 2 часа не хватило — переходим на следующий cycle (§6.1) в следующем cron-запуске.

### 8.3 Обоснование момента запуска CMEMS-ingest (08:00 UTC)

CMEMS-продукт GLOBAL_ANALYSISFORECAST_WAV_001_027 публикуется с типичной задержкой 8–11 часов от номинального timestamp'а (00:00 UTC). Запуск в 08:00 UTC = на нижней границе окна доступности:

Обычно: первые 1–3 попытки → not_ready, к 08:30–09:00 UTC пакет появляется.

В худшем случае: 4 часа опроса (max_retries=24) покрывают до 12:00 UTC — верхняя граница actuality window (§6.2).

## 9. Migration plan из S14-состояния

### 9.1 Текущее состояние (на начало S16)

Код: forecast_morning.py, forecast_evening.py, fetch_inputs.py — монолитные скрипты с встроенной загрузкой.

Storage: storage/cmems/..., storage/gfs/... уже создан оператором вручную по Copernicus-style раскладке.

Manifest: storage/manifest.json не существует.

Archive: storage/archive/ не существует.

Events log: ingest_events.jsonl не существует.

Downloaders: utils/cmems_downloader.py, utils/gfs_downloader.py существуют и работают (закрыты в S13–S14).

### 9.2 Пошаговый план миграции

S16 — Ingest GFS + Storage foundation (DoD-критично):

Prerequisite (OQ-1 resolved, обязательный шаг перед всеми остальными): Создать utils/process_lock.py с контекстным менеджером на базе fcntl.flock (Linux/Docker) или msvcrt.locking (Windows). Каждый ingest_*.py оборачивает main() в with ProcessLock("storage/.ingest_{source}.lock"). При занятом lock — log event "lock_contention" и exit 0 (не ошибка; просто другой инстанс уже работает). Unit-тест: два subprocess'а одновременно на один лок — ровно один проходит.

Создать utils/manifest.py (read/write/validate, атомарная запись).

Создать utils/event_logger.py (JSONL append с fsync).

Создать ingest_gfs.py — CLI по §5.1, использует существующий utils/gfs_downloader.py.

Реализовать archive rotation по §3.2 (отдельный модуль utils/archive_rotation.py).

На первом запуске: если manifest.json отсутствует — создаётся пустой {"schema_version": "1.0", "updated_at": "...", "gfs": null, "cmems": null}, дальше обычная логика.

Тесты: unit на resolve_target_cycle, rotate_archive, write_manifest; integration — полный прогон ingest_gfs.py --dry-run на fixture'е NOMADS.

S17 — Ingest CMEMS:

Создать ingest_cmems.py — CLI по §5.2, использует utils/cmems_downloader.py.

Те же компоненты archive/manifest/events — переиспользуются.

Тесты: симметричные S16.

S18 — forecast_main.py + hard-cut старых скриптов:

Создать forecast_main.py — CLI по §5.3.

Реализовать resolve_start_time() с ceil-семантикой (§2, §5.3.2).

Реализовать freshness check по §6.4.

Реализовать filename convention по §5.4.

Hard-cut: удалить forecast_morning.py, forecast_evening.py. fetch_inputs.py — оставить как library module или тоже удалить (решить в начале S18, зависит от того, используется ли он из других мест).

Обновить crontab, docker-compose.yml (комментарий-шпаргалку), README.md, entrypoint.sh (если нужен первичный ingest при старте контейнера — на усмотрение оператора).

DT-14-U — email verify на корпоративном SMTP (перенесён сюда из S15).

Bridge-cron из §8.1 активируется.

S19 — Stabilization:

DT-14-S (empty-slice warning).

DT-14-Y (exit codes propagation — с учётом новых трёх CLI).

End-to-end тест всего pipeline: ingest_gfs → ingest_cmems → forecast_main → email на реальном SMTP.

Final merge feature/bulletin-generation → master.

S20+ — Extensions:

HTTP API на FastAPI/Flask для on-demand (замена CLI в пользовательском сценарии).

ADR-002: DT-15-AI-1 (AI-scheduler) — spike, если событий достаточно.

ADR-003: output rotation (S3/БД).

DT-10-5, DT-08-* и прочий технический долг.

### 9.3 Риски миграции и митигация
| Риск                                                                     | Вероятность | Воздействие                | Митигация                                                                                                      |
| ------------------------------------------------------------------------ | ----------- | -------------------------- | -------------------------------------------------------------------------------------------------------------- |
| Первый запуск ingest_*.py на чистом storage без manifest                 | высокая     | средне                     | §9.2 шаг 5 — пустой manifest создаётся автоматически                                                           |
| Сломанный archive rotation → потеря последнего рабочего слота            | низкая      | высокое                    | Инвариант §3.2 + unit-тесты + atomic fs ops                                                                    |
| Несогласованность manifest.json и реальных файлов (кто-то руками удалил) | средняя     | среднее                    | forecast_main.py проверяет существование storage_path из манифеста перед чтением; если нет — exit 2            |
| Старый forecast_morning.py случайно запустится из забытого cron          | низкая      | высокое                    | В S18 hard-cut удаляет эти файлы и обновляет crontab; дополнительно — health check в entrypoint.sh             |
| Потеря событий ingest_events.jsonl (volume не смонтирован)               | средняя     | критическое для DT-15-AI-1 | event_logger.py падает с exit 2 если не может писать; docker-compose.yml со строгим check существования volume |

### 9.4 Rollback plan

На любом этапе S16–S18 возможен откат:

S16 rollback: удалить ingest_gfs.py, вернуть cron на forecast_morning.py / forecast_evening.py. Storage остаётся — старые скрипты его игнорируют, качают как раньше.

S17 rollback: симметрично.

S18 rollback: git revert commit'а с hard-cut'ом. Старые скрипты возвращаются, новый forecast_main.py остаётся как dead code — удаляется отдельным revert.

Архитектура X не несёт деструктивных миграций (не трогает существующие файлы в storage/, не меняет схему downloader'ов). Это сознательное проектное решение.

## 10. Open questions (решаются в S16–S20)

Вопросы, которые сознательно не фиксируются в ADR-001 и требуют отдельного решения на соответствующем этапе. Каждый помечен ответственной сессией.

### 10.1 Технические (S16–S19)

OQ-1: RESOLVED. Lock-файлы перенесены в DoD S16 (см. §9.2 шаг 0, prerequisite). Обоснование: при retry loop до 2 часов и cron интервале 6 часов перекрытие запусков реально при задержках NOAA >4h; concurrent archive rotation → потеря слота. Риск критичный, решение обязательное, не опциональное.

OQ-2 (S16). Как event_logger.py обрабатывает concurrent writes в ingest_events.jsonl из двух процессов?
— Предложение: O_APPEND + размер записи < 4KB (atomic POSIX append guarantee). Для Windows (Docker на non-Linux host) — явная file lock. Решить вместе с OQ-1.

OQ-3 (S17). Нужен ли CMEMS credentials refresh при 401? Текущий utils/cmems_downloader.py работает через Copernicus Marine Toolbox с долговременным токеном.
— Предложение: в ingest_cmems.py при result=auth_error — exit 3 (delivery_failure семантически не подходит; нужен отдельный код 4 = credentials_issue, или reuse 3). Решить до merge S17.

OQ-4 (S18). Как forecast_main.py выбирает GFS forecast hours из cycle'а для окна [start, start+24h]?
— Предложение: функция select_forecast_hours(cycle_issue_time, window_start, window_end) -> list[int]. Для start = cycle + 6h, window = 24h вернёт [6, 9, 12, ..., 30] с шагом 3h (стандартный GFS). Unit-тесты на границы. Спроектировать в начале S18.

OQ-5 (S18). Поведение при частичном покрытии CMEMS (есть snapshot сегодня, но не покрывает весь forecast window):
— CMEMS даёт analysis + forecast до +10 дней, так что window 24h всегда покрывается одним snapshot'ом. Вопрос снимается. Зафиксировано здесь для истории.

OQ-6 (S19). Что делать при одновременном hard-cut (forecast_morning.py удалён) и внешнем оркестраторе (забытый cron на хосте вне контейнера, CI job с hardcoded именем)?
— Предложение: в README.md + CHANGELOG.md в S18 чётко зафиксировать факт удаления. В S19 — grep -r forecast_morning / forecast_evening по всей инфраструктуре (CI, ansible, prod crontab хоста) и проверка на отсутствие.

### 10.2 Продуктовые (S20+)

OQ-7 (S20). HTTP API: REST или gRPC? Формат request: JSON body или query params?
— Обсуждение в ADR-004 (S20+).

OQ-8 (S20). Аутентификация пользователей для API: API keys, OAuth, internal-only?
— Обсуждение в ADR-004.

OQ-9 (S20+). Формат вывода помимо .docx: HTML, PDF, JSON-структурированный ответ?
— Обсуждение в ADR-005.

OQ-10 (S21+). Масштабирование на другие регионы помимо Каспия: параметризация bounding box, multiple regions per request?
— Обсуждение в ADR-006.

## 11. Roadmap S16 → S20

Общий план развёртывания архитектуры X:
gantt
    title Roadmap S16–S20 (ADR-001 implementation)
    dateFormat  YYYY-MM-DD
    section S16 Ingest GFS
    utils/manifest.py           :2026-04-23, 1d
    utils/event_logger.py       :2026-04-23, 1d
    utils/archive_rotation.py   :2026-04-23, 1d
    ingest_gfs.py CLI           :2026-04-24, 1d
    S16 tests + integration     :2026-04-24, 1d
    section S17 Ingest CMEMS
    ingest_cmems.py CLI         :2026-04-25, 1d
    S17 tests + integration     :2026-04-25, 1d
    section S18 Forecast + hard-cut
    forecast_main.py CLI        :2026-04-26, 1d
    resolve_start_time + tests  :2026-04-26, 1d
    Filename convention DT-14-T :2026-04-26, 1d
    Hard-cut old scripts        :2026-04-27, 1d
    DT-14-U email verify SMTP   :2026-04-27, 1d
    Bridge cron §8.1            :2026-04-27, 1d
    section S19 Stabilization
    DT-14-S empty slice         :2026-04-28, 1d
    DT-14-Y exit codes          :2026-04-28, 1d
    E2E test pipeline           :2026-04-29, 1d
    Final merge to master       :2026-04-29, 1d
    section S20+ Extensions
    HTTP API (ADR-004)          :2026-04-30, 3d
    AI-scheduler (ADR-002)      :2026-05-03, 5d
    Output rotation (ADR-003)   :2026-05-08, 2d

Критерии перехода между сессиями:

S16 → S17: ingest_gfs.py успешно отрабатывает на реальном NOMADS, manifest.json содержит валидный gfs блок, ingest_events.jsonl пишется, archive rotation проходит инвариант §3.2.

S17 → S18: Симметрично для CMEMS. После S17 manifest.json содержит оба блока (gfs, cmems) с валидными данными. Старые forecast_*.py ещё работают (не удалены).

S18 → S19: forecast_main.py генерит валидный .docx на данных из storage/ без прямой загрузки. Email-доставка на корпоративном SMTP подтверждена (DT-14-U закрыт). Hard-cut выполнен, bridge-cron §8.1 работает.

S19 → merge master: все DT-14-* закрыты, E2E зелёный, нет открытых P0/P1 багов.

## 12. Governance и процедурные правила

### 12.1 DT-15-ADR-GOV-1: pre-commit hook на sync canonical docs

Проблема (выявлена в S15): в S14 часть решений попала в conversation_history.md, но не попала в project_context.md и project_progress.md. Оператор обнаружил рассинхрон только утром следующего дня.

Решение: каждый commit, затрагивающий .py, .ini, Dockerfile, docker-compose.yml, crontab, entrypoint.sh, *.toml, *.yaml, *.json (кроме package-lock и подобных), обязан в том же commit'е содержать изменение в docs/conversation_history.md с записью вида:
### Session {N}.{letter} ({date}): {title}
- Commit: {hash} (заполняется после commit)
- Что изменено: {краткое описание}
- Почему: {обоснование}

Реализация (S16):

.git/hooks/pre-commit (через pre-commit framework или raw bash):
#!/bin/bash
STAGED_CODE=$(git diff --cached --name-only | grep -E '\\.(py|ini|yml|yaml|toml|json|sh)$|Dockerfile|crontab' | grep -v 'package-lock')
STAGED_HISTORY=$(git diff --cached --name-only | grep 'docs/conversation_history.md')
if [ -n "$STAGED_CODE" ] && [ -z "$STAGED_HISTORY" ]; then
    echo "ERROR: code changes require conversation_history.md update in the same commit"
    exit 1
fi
Установка hook'а в S16 — добавить в scripts/install_hooks.sh, вызывается из entrypoint.sh dev-контейнера и README.md для операторов.

Escape hatch: git commit --no-verify — разрешено только для docs-only / hot-fix коммитов с пометкой в сообщении [no-history].

### 12.2 Правило единого ADR на одно архитектурное решение

Один ADR = одно решение. Нельзя ретроактивно изменять Accepted ADR — вместо этого создаётся новый ADR со статусом Supersedes: ADR-XXX.

Статусы ADR: Proposed → Accepted / Rejected. После Accepted — только Superseded by ADR-YYY.

Нумерация: 001-, 002-, ... Без пропусков.

### 12.3 Правило фиксации Open questions

Каждый OQ-N должен иметь явную ответственную сессию (OQ-N (SXX)).

При закрытии OQ — запись в docs/conversation_history.md с пометкой [OQ-N resolved] и обоснованием.

При переносе OQ на более позднюю сессию — запись [OQ-N deferred S16 → S17] с причиной.

Неразрешённые OQ на момент финального merge в master — блокер merge'а. Либо закрываем, либо явно переводим в Superseded by ADR-YYY или WontFix с обоснованием.

### 12.4 Правило именования DT (deferred tasks)

Формат: DT-{session_opened}-{letter} или DT-{session_opened}-{subsystem}-{N}.

Примеры:

DT-14-V — открыт в S14, порядковая буква V.

DT-15-AI-1 — открыт в S15, подсистема AI, номер 1.

DT-15-ADR-GOV-1 — открыт в S15, подсистема ADR-GOV, номер 1.

DT переезжают между parking lot'ами сессий до закрытия или явного WontFix.

## 13. Appendix

### 13.1 Полная JSON-схема manifest.json (schema_version 1.0)

Формальная JSON Schema для валидации в utils/manifest.py:
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://hydromet_bulletin/schemas/manifest_v1.json",
  "title": "Hydromet Bulletin Storage Manifest",
  "type": "object",
  "required": ["schema_version", "updated_at", "gfs", "cmems"],
  "properties": {
    "schema_version": {
      "type": "string",
      "const": "1.0"
    },
    "updated_at": {
      "type": "string",
      "format": "date-time",
      "description": "ISO 8601 UTC, момент последней записи манифеста"
    },
    "gfs": {
      "oneOf": [
        { "type": "null" },
        {
          "type": "object",
          "required": [
            "latest_successful_cycle",
            "latest_successful_fetched_at",
            "latest_successful_source_timestamp",
            "storage_path",
            "archive_slots"
          ],
          "properties": {
            "latest_successful_cycle": {
              "type": "string",
              "pattern": "^\\d{4}-\\d{2}-\\d{2}T(00|06|12|18)Z$"
            },
            "latest_successful_fetched_at": {
              "type": "string",
              "format": "date-time"
            },
            "latest_successful_source_timestamp": {
              "type": "string",
              "format": "date-time"
            },
            "storage_path": {
              "type": "string",
              "pattern": "^storage/gfs/\\d{8}/(00z|06z|12z|18z)/$"
            },
            "archive_slots": {
              "type": "object",
              "properties": {
                "24h-back": {
                  "oneOf": [
                    { "type": "null" },
                    {
                      "type": "object",
                      "required": ["id", "path"],
                      "properties": {
                        "id": { "type": "string" },
                        "path": { "type": "string" }
                      }
                    }
                  ]
                },
                "48h-back": {
                  "oneOf": [
                    { "type": "null" },
                    {
                      "type": "object",
                      "required": ["id", "path"],
                      "properties": {
                        "id": { "type": "string" },
                        "path": { "type": "string" }
                      }
                    }
                  ]
                }
              }
            }
          }
        }
      ]
    },
    "cmems": {
      "oneOf": [
        { "type": "null" },
        {
          "type": "object",
          "required": [
            "latest_successful_snapshot",
            "latest_successful_fetched_at",
            "latest_successful_source_timestamp",
            "storage_path",
            "archive_slots"
          ],
          "properties": {
            "latest_successful_snapshot": {
              "type": "string",
              "format": "date"
            },
            "latest_successful_fetched_at": {
              "type": "string",
              "format": "date-time"
            },
            "latest_successful_source_timestamp": {
              "type": "string",
              "format": "date-time"
            },
            "storage_path": {
              "type": "string"
            },
            "archive_slots": {
              "type": "object",
              "properties": {
                "24h-back": {
                  "oneOf": [
                    { "type": "null" },
                    {
                      "type": "object",
                      "required": ["id", "path"],
                      "properties": {
                        "id": { "type": "string" },
                        "path": { "type": "string" }
                      }
                    }
                  ]
                },
                "48h-back": {
                  "oneOf": [
                    { "type": "null" },
                    {
                      "type": "object",
                      "required": ["id", "path"],
                      "properties": {
                        "id": { "type": "string" },
                        "path": { "type": "string" }
                      }
                    }
                  ]
                }
              }
            }
          }
        }
      ]
    }
  }
}

Схема сохраняется в schemas/manifest_v1.json в S16 (первая сессия после ADR-001).

### 13.2 Полная JSON-схема ingest_events.jsonl (schema_version 1.0)

Каждая строка файла должна валидироваться по схеме:
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://hydromet_bulletin/schemas/ingest_event_v1.json",
  "title": "Hydromet Bulletin Ingest Event",
  "type": "object",
  "required": [
    "ts", "source", "event", "result",
    "latency_ms", "duration_ms", "user_ip_region"
  ],
  "properties": {
    "ts": { "type": "string", "format": "date-time" },
    "source": { "type": "string", "enum": ["gfs", "cmems"] },
    "event": {
      "type": "string",
      "enum": [
        "poll_attempt",
        "ingest_started",
        "ingest_complete",
        "ingest_failed",
        "archive_rotation",
        "manifest_update"
      ]
    },
    "target_cycle": { "type": ["string", "null"] },
    "target_date": { "type": ["string", "null"] },
    "result": {
      "type": "string",
      "enum": [
        "success",
        "not_ready",
        "network_error",
        "parse_error",
        "auth_error",
        "timeout"
      ]
    },
    "http_status": { "type": ["integer", "null"] },
    "latency_ms": { "type": ["integer", "null"], "minimum": 0 },
    "source_timestamp": { "type": ["string", "null"], "format": "date-time" },
    "bytes_downloaded": { "type": ["integer", "null"], "minimum": 0 },
    "duration_ms": { "type": "integer", "minimum": 0 },
    "user_ip_region": { "type": ["string", "null"] },
    "error_message": { "type": "string" },
    "retry_number": { "type": "integer", "minimum": 0 },
    "storage_path_written": { "type": "string" }
  },
  "anyOf": [
    { "required": ["target_cycle"] },
    { "required": ["target_date"] }
  ]
}

Схема сохраняется в schemas/ingest_event_v1.json в S16.

### 13.3 Exit codes reference (consolidated, DT-14-Y)

Применяется к всем трём CLI (ingest_gfs.py, ingest_cmems.py, forecast_main.py):
| Code | Значение             | Пример ситуации                                                                               |
| ---- | -------------------- | --------------------------------------------------------------------------------------------- |
| 0    | success              | Всё OK, включая dry-run success                                                               |
| 1    | validation failure   | Невалидные аргументы CLI, нарушение guard-проверок данных                                     |
| 2    | data unavailable     | GFS/CMEMS не отвечает; manifest corrupted; storage path missing; freshness threshold violated |
| 3    | delivery failure     | SMTP недоступен, email не отправлен                                                           |
| 4    | credentials issue    | Copernicus auth_error, SMTP auth_error (см. OQ-3)                                             |
| 5    | polling timeout      | forecast_main не дождался готовности manifest за timeout_minutes (DT-17-1)                    |
| >=10 | internal / unhandled | Неожиданные исключения, баги                                                                  |

CI/cron-wrapper'ы должны различать 2 (ретраябельно) и >=10 (нужен разбор).

### 13.4 Глоссарий

Cycle (GFS): четырёхчасовой такт выпуска GFS. Четыре в сутки: 00z, 06z, 12z, 18z.

Snapshot (CMEMS): суточный пакет данных CMEMS, датированный по UTC-полуночи.

Actuality window: период, в течение которого текущий cycle/snapshot считается «актуальным» и не пересчитывается. GFS=6h, CMEMS=12h.

Freshness threshold: граница возраста данных, при превышении которой forecast_main.py отказывается генерировать бюллетень. Hard=24h, soft GFS=12h / CMEMS=18h.

Slot (archive): именованная позиция в archive (24h-back, 48h-back). Одновременно в archive максимум 2 слота на источник.

Request time: момент, в который пользователь запросил бюллетень. В MSK.

Start time: первый прогнозный час бюллетеня. = ceil(request_time, 1h) в MSK (если request_time на границе часа — +1h).

Forecast window: [start_time, start_time + 24h] — интервал, на который выпускается бюллетень.

Bridge cron: временное cron-расписание S16–S19, автоматизирующее 2×/сутки email-доставку до появления HTTP API (S20+).

Конец ADR-001.
