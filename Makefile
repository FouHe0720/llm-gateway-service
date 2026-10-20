.PHONY: install run test lint format demo smoke docker-check
PYTHON := .venv/bin/python
PORT ?= 8000

install:
	bash scripts/install.sh

run:
	$(PYTHON) -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port $(PORT) --workers 1 --no-access-log

test:
	$(PYTHON) -m pytest -q

lint:
	.venv/bin/ruff check .
	.venv/bin/ruff format --check .

format:
	.venv/bin/ruff check --fix .
	.venv/bin/ruff format .

demo:
	bash scripts/demo_mock.sh

smoke:
	bash scripts/smoke_test.sh

docker-check:
	docker compose config --quiet
	docker build --check .
