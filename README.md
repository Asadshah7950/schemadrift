# schemadrift

> **Detect schema drift between PostgreSQL databases and generate safe, ordered migration SQL — from the command line.**

[![CI](https://github.com/Asadshah7950/schemadrift/actions/workflows/ci.yml/badge.svg)](https://github.com/Asadshah7950/schemadrift/actions/workflows/ci.yml)
[![PyPI version](https://img.shields.io/pypi/v/schemadrift.svg)](https://pypi.org/project/schemadrift/)
[![Python versions](https://img.shields.io/pypi/pyversions/schemadrift.svg)](https://pypi.org/project/schemadrift/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## Features

- 🔍 **Schema inspection** — Introspects live PostgreSQL databases via `psycopg2` (tables, columns, indexes, foreign keys, enums)
- 🔄 **Drift detection** — Pure-Python diff engine with zero database dependency for the comparison step
- 📝 **Safe SQL generation** — Produces `BEGIN`/`COMMIT`-wrapped migration scripts in the correct dependency order (drop FKs first, create tables before adding columns, etc.)
- 🖥️ **Rich CLI** — Beautiful terminal output powered by [Rich](https://github.com/Textualize/rich)
- 📦 **Multiple output formats** — SQL, JSON, or human-readable summary
- ✅ **95%+ unit test coverage** — All core logic tested without a live database

---

## Installation

```bash
pip install schemadrift
```

Or install from source:

```bash
git clone https://github.com/Asadshah7950/schemadrift.git
cd schemadrift
pip install -e '.[dev]'
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
```

### `inspect` — Print a schema overview

```bash
schemadrift inspect --dsn "postgres://user:pass@host/db"
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

---

## Architecture

| Module | Description |
|---|---|
| [`schemadrift/models.py`](schemadrift/models.py) | Dataclasses for all schema objects (`ColumnDef`, `TableDef`, `IndexDef`, `ForeignKeyDef`, `SchemaSnapshot`, `DiffResult`) |
| [`schemadrift/inspector.py`](schemadrift/inspector.py) | `SchemaInspector` — connects to PostgreSQL and builds a `SchemaSnapshot` using `information_schema` and `pg_catalog` queries |
| [`schemadrift/differ.py`](schemadrift/differ.py) | `SchemaDiffer` — pure-Python comparison engine; no DB connection required |
| [`schemadrift/generator.py`](schemadrift/generator.py) | `MigrationGenerator` — converts a `DiffResult` into safe, ordered SQL wrapped in a transaction |
| [`schemadrift/cli.py`](schemadrift/cli.py) | Click CLI exposing `diff` and `inspect` commands with Rich terminal output |

---

## Contributing

Contributions, bug reports, and feature requests are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup instructions.

---

## License

[MIT](LICENSE) © 2024 Asad Shah
