# Contributing to schemadrift

Thank you for your interest in contributing! Here's how to get set up quickly.

## Dev Setup

Clone the repo and install in editable mode with all dev dependencies:

```bash
git clone https://github.com/Asadshah7950/schemadrift.git
cd schemadrift
pip install -e '.[dev]'
```

## Running Tests

```bash
pytest
```

To skip tests that require a live PostgreSQL connection:

```bash
pytest --ignore=tests/test_inspector.py
```

To view coverage:

```bash
pytest --cov=pg_schema_diff --cov-report=html
```

## Linting

We use [Ruff](https://github.com/astral-sh/ruff) for linting and formatting:

```bash
ruff check .
ruff format .
```

## Type Checking

```bash
mypy pg_schema_diff
```

## Pull Requests

1. Fork the repo and create a feature branch: `git checkout -b feat/my-feature`
2. Make your changes, add tests, and ensure all checks pass.
3. Open a pull request against `main` with a clear description of what you changed and why.

## Code Style

- Follow PEP 8 (enforced by Ruff).
- Add docstrings to all public functions and classes.
- Keep functions small and focused.
