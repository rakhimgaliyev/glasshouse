.PHONY: install test lint demo serve

install:
	uv venv && uv pip install -e ".[dev,server]"

test:
	.venv/bin/pytest -q

lint:
	.venv/bin/ruff check src tests examples

demo:
	.venv/bin/python examples/demo.py

serve:
	.venv/bin/uvicorn glasshouse.server:app --reload
