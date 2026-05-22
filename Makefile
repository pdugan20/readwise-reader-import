.PHONY: dev lint format test build clean check

dev:
	pip install -e '.[dev]'
	pre-commit install --hook-type pre-commit --hook-type commit-msg

lint:
	ruff check .
	ruff format --check .

format:
	ruff check --fix .
	ruff format .

test:
	python -m pytest tests/ -v

build: clean
	python -m build

clean:
	rm -rf dist/ build/ ./*.egg-info

check: lint test
