# hydromet_bulletin — Makefile
# Требует: make, docker-compose, python
# Использование: make <target>

.PHONY: help run ingest-gfs ingest-cmems ingest-all test

help:
	@echo "hydromet_bulletin — доступные команды:"
	@echo "  make run                    — сформировать бюллетень сейчас"
	@echo "  make run DATE=2026-06-08 TIME=14:00  — бюллетень на дату/время"
	@echo "  make ingest-gfs             — скачать GFS данные"
	@echo "  make ingest-cmems           — скачать CMEMS данные"
	@echo "  make ingest-all             — скачать GFS + CMEMS"
	@echo "  make test                   — запустить тесты"

DATE ?= $(shell date '+%Y-%m-%d')
TIME ?= $(shell date '+%H:%M')
TZ   ?= MSK

run:
	FORECAST_DATE=$(DATE) FORECAST_TIME=$(TIME) FORECAST_TZ=$(TZ) \
	  docker-compose run --rm bulletin

ingest-gfs:
	HYDROMET_INGEST_EVENTS_PATH=ingest_events/ingest_events.jsonl \
	  python ingest_gfs.py

ingest-cmems:
	HYDROMET_INGEST_EVENTS_PATH=ingest_events/ingest_events.jsonl \
	  python ingest_cmems.py

ingest-all: ingest-gfs ingest-cmems

test:
	python -m pytest -q
