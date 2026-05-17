# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Status

This is a freshly scaffolded project with no committed history yet. Treat existing code as a starting point, not an established architecture. The intended product (per `pyproject.toml`) is a **self-service accounting application with MCP and web interfaces** — but none of that has been built. When implementing features, expect to establish conventions rather than follow them.

## Tooling

- Python **3.13+** required (`.python-version` pins 3.13).
- Managed with **uv** using the `uv_build` build backend (not setuptools/poetry).

## Commands

```bash
uv sync              # install/resolve dependencies into the project venv
uv run books         # run the app (entry point: books:main in src/books/__init__.py)
uv run python -m ...  # run arbitrary modules within the project env
```

No test runner, linter, or formatter is configured yet. If you add tests, prefer `pytest` invoked as `uv run pytest` and add it to `pyproject.toml` dev dependencies; wire single-test runs as `uv run pytest path::test_name`.

## Layout

`src/` layout: package code lives in `src/books/`. The console script `books` maps to `books:main`. Add new modules under `src/books/`; the build backend discovers them automatically.
