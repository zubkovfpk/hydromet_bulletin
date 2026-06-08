# ADR-003: On-demand ingest orchestration in forecast_main

Status: Accepted (Session 17, 2026-06-05)
Deciders: Оператор проекта, Comet
Related: ADR-001 §2 (Scenario X), ADR-001 §13.3, DT-17-1

## Context

forecast_main.py имел параметры timeout_minutes и polling_minutes,
но не реализовывал polling loop и не запускал ingestion при
отсутствии данных. При устаревшем manifest pipeline падал с ошибкой,
требуя ручного запуска ingest_gfs.py.

## Decision

forecast_main.py выступает локальным оркестратором ingestion
(ADR-001 §2, Scenario X):

1. По умолчанию (без флагов) при отсутствии или устаревшем manifest
   forecast_main запускает ingest_gfs.py как subprocess с нужным
   --cycle, затем выполняет polling manifest до готовности данных
   с интервалом polling_minutes и таймаутом timeout_minutes.

2. Критерий готовности — только manifest: latest_successful_cycle
   совпадает с effective_gfs_cycle. Код завершения ingest не
   является критерием готовности.

3. Флаг --no-ingest отключает автозапуск ingest (operator mode):
   forecast_main только ждёт обновления manifest или завершается
   с exit 5 по таймауту.

4. Если ingest subprocess завершился с ненулевым кодом и manifest
   не обновился — exit 2 (ingestion error).

5. Lock contention (ingest exit 0 при занятом ProcessLock) не
   считается успехом — polling продолжается.

## Coupling mitigation

forecast_main знает только команду:
  python ingest_gfs.py --cycle YYYY-MM-DDTHHZ
Критерий готовности — исключительно manifest. Это позволяет
в будущем заменить subprocess на внешний оркестратор без
изменения пользовательского контракта.

## Exit codes

Полная таблица exit codes — ADR-001 §13.3 (единственный
источник правды). ADR-003 использует:
- 2: ingest failed или manifest не обновился после subprocess
- 5: polling timeout (EXIT_TIMEOUT, DT-17-1)

Остальные коды (0, 1, 3, 4, >=10) — по ADR-001 §13.3.
