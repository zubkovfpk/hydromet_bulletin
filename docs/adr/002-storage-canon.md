# ADR-002: Storage canon owner of truth = config.ini

Status: Accepted (Session 17, 2026-06-04)
Deciders: Оператор проекта, Comet
Related: ADR-001 §3.1, DT-16-1

## Context

До S17 manifest.gfs содержал единое поле storage_path,
которое объединяло конфигурационный корень (из config.ini)
и структурный относительный путь цикла.
Это делало невозможной валидацию схемы при произвольном
значении GFS_OUTPUT_DIR в config.ini.

## Decision

Manifest.gfs содержит два раздельных поля:
- storage_root: родительский каталог GFS-хранилища
  (STORAGE_GFS_ROOT.parent); например `data/storage`.
  Значение выводится из config.ini ([GFS_STORAGE].GFS_OUTPUT_DIR)
  путём взятия `.parent`. Владелец — config.ini.
- relative_path: детерминированный путь вида
  "gfs/YYYYMMDD/HHz/"; всегда валидируется схемой;
  владелец — ingest_gfs.py (ADR-001 §3.1).

Потребитель (forecast_main.py) строит реальный путь как:
  Path(storage_root) / relative_path

  Пример: `Path('data/storage') / 'gfs/20260513/12z/'`
  = `data/storage/gfs/20260513/12z/`

## Consequences

- schemas/manifest_v1.json валидирует только relative_path.
- Перенос storage в другой каталог требует изменения только
  config.ini, не схемы и не кода.
- Локальный guard _write_manifest_with_config_storage_path
  в ingest_gfs.py удалён (был временным обходом DT-16-1).
