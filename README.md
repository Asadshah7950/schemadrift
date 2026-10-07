# schemadrift

> **Detect schema drift between PostgreSQL databases and generate safe, ordered migration SQL — from the command line.**

[![CI](https://github.com/Asadshah7950/schemadrift/actions/workflows/ci.yml/badge.svg)](https://github.com/Asadshah7950/schemadrift/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/badge/coverage-96%25-brightgreen.svg)](https://github.com/Asadshah7950/schemadrift)
[![PyPI version](https://img.shields.io/pypi/v/pg-schema-diff.svg)](https://pypi.org/project/pg-schema-diff/)
[![Python versions](https://img.shields.io/pypi/pyversions/pg-schema-diff.svg)](https://pypi.org/project/pg-schema-diff/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![GitHub Marketplace](https://img.shields.io/badge/Marketplace-schemadrift-blue.svg?colorA=24292e&colorB=0366d6&style=flat&logo=github)](https://github.com/marketplace/actions/postgresql-schema-drift-detector)

<p align="center">
  <img src="docs/assets/demo.svg" alt="schemadrift terminal demo" width="100%">
</p>

---

## Features

- 🔍 **Schema inspection** — Introspects live PostgreSQL databases via `psycopg2` (tables, columns, indexes, foreign keys, enums)
- 💾 **Portable JSON snapshots** — Capture schema snapshots with `snapshot --dsn ... -o schema.json` for Git versioning and offline audits
- 🔄 **Offline & live drift detection** — Pure-Python diff engine comparing live databases, saved JSON snapshots, or mixed environments
- 📝 **Safe SQL generation** — Produces `BEGIN`/`COMMIT`-wrapped migration scripts in the correct dependency order (drop FKs first, create tables before adding columns, etc.)
- ⚡ **Zero-downtime migrations** — Native `--concurrently` support for `CREATE INDEX CONCURRENTLY` and `DROP INDEX CONCURRENTLY`
- 🛑 **Destructive change protection** — Safeguard production with `--fail-on-destructive` (`-w`) to exit with code 2 if dropped tables or columns are detected
- ⏪ **Rollback generator** — Generate reverse / down migrations with `--direction down`
- 🖥️ **Rich CLI** — Beautiful terminal output powered by [Rich](https://github.com/Textualize/rich)
- 📦 **Multiple output formats** — SQL, JSON, Markdown, human-readable summary, or interactive dark-mode HTML reports
- 🛡️ **Schema Anti-Pattern Linter** — Static analysis detecting missing primary keys (E001), unindexed foreign keys (W001), and redundant prefix indexes (W002) with strict CI gates (`-W`)
- 📊 **CI/CD Step Summary** — Automatically writes GitHub-flavored Markdown drift tables to `$GITHUB_STEP_SUMMARY`
- ✅ **95%+ unit test coverage** — All core logic tested without a live database

---

## Installation

```bash
pip install pg-schema-diff
```

Or install from source:

```bash
git clone https://github.com/Asadshah7950/schemadrift.git
cd schemadrift
pip install -e '.[dev]'
```

### Docker

```bash
docker build -t schemadrift .
docker run --rm schemadrift diff --source "postgres://..." --target "postgres://..."
```

---

## GitHub Actions CI/CD Integration

Detect unintentional schema drift directly in your pull requests and block breaking DDL deployments:

```yaml
- name: Check PostgreSQL Schema Drift
  uses: Asadshah7950/schemadrift@main
  with:
    source: ${{ secrets.PROD_DATABASE_URL }}
    target: ${{ secrets.STAGING_DATABASE_URL }}
    format: 'summary'
    fail-on-drift: 'true'
    fail-on-destructive: 'true'
```

---

## Quick Start

### Python API

```python
from schemadrift.inspector import SchemaInspector
from schemadrift.differ import SchemaDiffer
from schemadrift.generator import MigrationGenerator

# Introspect both databases
source = SchemaInspector("postgres://user:pass@source-host/mydb").snapshot()
target = SchemaInspector("postgres://user:pass@target-host/mydb").snapshot()

# Compute the diff
diff = SchemaDiffer(source, target).diff()

# Generate migration SQL
sql = MigrationGenerator(diff).generate()
print(sql)
```

### Output example

```sql
BEGIN;

-- Drop foreign key: fk_orders_user
ALTER TABLE "orders" DROP CONSTRAINT "fk_orders_user";

-- Add table: payments
CREATE TABLE "payments" (
    "id" integer NOT NULL,
    "amount" numeric NOT NULL,
    PRIMARY KEY ("id")
);

-- Add column: users.phone
ALTER TABLE "users" ADD COLUMN "phone" text;

-- Add foreign key: fk_orders_user
ALTER TABLE "orders" ADD CONSTRAINT "fk_orders_user"
  FOREIGN KEY ("user_id") REFERENCES "users" ("id") ON DELETE NO ACTION;

COMMIT;
```

---

## CLI Usage

### `diff` — Compare two schemas

```bash
# Print migration SQL to stdout
schemadrift diff \
  --source "postgres://user:pass@source-host/db" \
  --target "postgres://user:pass@target-host/db"

# Save to a file
schemadrift diff \
  --source "postgres://user:pass@source-host/db" \
  --target "postgres://user:pass@target-host/db" \
  --output migration.sql

# JSON output
schemadrift diff \
  --source "postgres://user:pass@source-host/db" \
  --target "postgres://user:pass@target-host/db" \
  --format json

# Human-readable summary
schemadrift diff \
  --source "postgres://user:pass@source-host/db" \
  --target "postgres://user:pass@target-host/db" \
  --format summary

# Interactive dark-mode HTML audit report with 1-click SQL copy
schemadrift diff \
  --source "postgres://user:pass@source-host/db" \
  --target "postgres://user:pass@target-host/db" \
  --format html \
  --output drift-audit.html

# GitHub Actions / PR Markdown report (auto-writes to $GITHUB_STEP_SUMMARY in CI)
schemadrift diff \
  --source "postgres://user:pass@source-host/db" \
  --target "postgres://user:pass@target-host/db" \
  --format markdown

# CI/CD Gate: Fail pipeline (exit code 1) if schema drift is detected
schemadrift diff \
  --source "postgres://user:pass@source-host/db" \
  --target "postgres://user:pass@target-host/db" \
  --fail-on-drift

# Destructive Change Gate: Fail pipeline (exit code 2) if tables/columns are dropped
schemadrift diff \
  --source "postgres://user:pass@source-host/db" \
  --target "postgres://user:pass@target-host/db" \
  --fail-on-destructive

# Exclude internal tables (e.g. alembic_version, _prisma_migrations, spatial_ref_sys)
schemadrift diff \
  --source "postgres://user:pass@source-host/db" \
  --target "postgres://user:pass@target-host/db" \
  --exclude alembic_version \
  --exclude _prisma_migrations

# Rollback / down migration (revert target back to source)
schemadrift diff \
  --source "postgres://user:pass@source-host/db" \
  --target "postgres://user:pass@target-host/db" \
  --direction down \
  --output rollback.sql

# Non-transactional execution (omit BEGIN / COMMIT)
schemadrift diff \
  --source "postgres://user:pass@source-host/db" \
  --target "postgres://user:pass@target-host/db" \
  --no-transaction

# Zero-downtime index management (CREATE / DROP INDEX CONCURRENTLY)
schemadrift diff \
  --source "postgres://user:pass@source-host/db" \
  --target "postgres://user:pass@target-host/db" \
  --concurrently

# Offline diff: compare a saved JSON snapshot against a live database or another snapshot
schemadrift diff \
  --source schema-prod.json \
  --target "postgres://user:pass@staging-host/db"

schemadrift diff \
  --source schema-v1.json \
  --target schema-v2.json
```

### `snapshot` — Capture a portable JSON schema snapshot

Export a complete, self-contained schema definition (tables, columns, types, indexes, FKs, enums) to a JSON document for Git versioning, compliance audit logs, or offline CI verification:

```bash
# Save formatted snapshot to disk
schemadrift snapshot --dsn "postgres://user:pass@host/db" -o schema.json

# Emit minified JSON to stdout
schemadrift snapshot --dsn "postgres://user:pass@host/db" --compact
```

### `inspect` — Print a schema overview

Inspect a live database connection or an offline JSON snapshot file:

```bash
# Inspect a live database
schemadrift inspect --dsn "postgres://user:pass@host/db"

# Inspect a saved schema snapshot file
schemadrift inspect --file schema.json
```

Output:

```
              Schema Summary
┌──────────────┬─────────┬─────────┐
│ Table        │ Columns │ Indexes │
├──────────────┼─────────┼─────────┤
│ orders       │       6 │       3 │
│ payments     │       4 │       1 │
│ users        │       8 │       4 │
└──────────────┴─────────┴─────────┘
Foreign keys: 2
```

### `lint` — Static schema linter & anti-pattern detector

Audit a live database or saved schema snapshot for structural anti-patterns, replication bottlenecks, and redundant indexes:

```bash
# Lint a live PostgreSQL database
schemadrift lint --dsn "postgres://user:pass@host/db"

# Lint an offline schema snapshot file
schemadrift lint --file schema.json

# Fail CI/CD gate on any warnings or errors (exit code 1)
schemadrift lint --file schema.json --fail-on-warning

# Machine-readable JSON output for automated reporting
schemadrift lint --file schema.json --format json

# Exclude legacy or third-party tables from lint checks
schemadrift lint --file schema.json --exclude legacy_logs --exclude spatial_ref_sys
```

#### Lint Rules

| Rule | Severity | Name | Description |
|---|---|---|---|
| **E001** | `ERROR` | `missing-primary-key` | Table lacks a primary key. Causes full table rewrites during logical replication and risks duplicate rows. |
| **W001** | `WARNING` | `unindexed-foreign-key` | Foreign key referencing columns lack a supporting prefix index. Causes sequential scans and table locks on parent table deletes/updates. |
| **W002** | `WARNING` | `redundant-index` | Table has an index whose columns are a left-prefix of another index on the same table. Wastes disk space and write IOPS. |
| **W003** | `WARNING` | `varchar-without-length` | Unbounded `VARCHAR` with no length limit. Bypasses constraints and behaves identically to `TEXT` without clarifying design intent. |
| **W004** | `WARNING` | `nullable-boolean` | Nullable `BOOLEAN` column. Introduces SQL three-valued logic (`NULL`/`TRUE`/`FALSE`) leading to silent query filtering bugs. |
| **W005** | `WARNING` | `timestamp-without-timezone` | `TIMESTAMP` without time zone. Omits UTC offset context, risking daylight saving and cross-region time conversion anomalies. |

---

## Architecture

For complete system design diagrams, DAG topological ordering specifications, and concurrency safety models, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

| Module | Description |
|---|---|
| [`schemadrift/models.py`](schemadrift/models.py) | Dataclasses for all schema objects (`ColumnDef`, `TableDef`, `IndexDef`, `ForeignKeyDef`, `SchemaSnapshot`, `DiffResult`) |
| [`schemadrift/inspector.py`](schemadrift/inspector.py) | `SchemaInspector` — connects to PostgreSQL and builds a `SchemaSnapshot` using `information_schema` and `pg_catalog` queries |
| [`schemadrift/differ.py`](schemadrift/differ.py) | `SchemaDiffer` — pure-Python comparison engine; no DB connection required |
| [`schemadrift/linter.py`](schemadrift/linter.py) | `SchemaLinter` — static schema analysis engine detecting missing PKs, unindexed FKs, redundant indexes, and column type anti-patterns |
| [`schemadrift/generator.py`](schemadrift/generator.py) | `MigrationGenerator` — converts a `DiffResult` into safe, ordered SQL wrapped in a transaction |
| [`schemadrift/cli.py`](schemadrift/cli.py) | Click CLI exposing `diff`, `snapshot`, `inspect`, and `lint` commands with Rich terminal output |

---

## Benchmarks & Performance

Automated benchmarks verify performance under large schema loads:

```bash
python -m pytest tests/test_benchmark.py
```

| Workload | Metric | Threshold | Observed |
|---|---|---|---|
| **50 Tables / 150 Columns** | Differ Execution Latency | `< 100ms` | `~3.2ms` |
| **50 Interdependent Tables** | DDL Generation (DAG Sort) | `< 100ms` | `~4.1ms` |
| **100+ Tables Snapshot** | Memory Allocation (RSS) | `< 25MB` | `~14MB` |

---

## Contributing

Contributions, bug reports, and feature requests are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup instructions.

---

## License

[MIT](LICENSE) © 2024 Asad Shah
