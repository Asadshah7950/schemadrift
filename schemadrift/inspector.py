"""Schema inspector: connects to PostgreSQL and produces a SchemaSnapshot."""

from __future__ import annotations

import re

import psycopg2
import psycopg2.extras

from schemadrift.models import (
    ColumnDef,
    ForeignKeyDef,
    IndexDef,
    SchemaSnapshot,
    TableDef,
)

_SQL_TABLES = """
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_type = 'BASE TABLE'
ORDER BY table_name;
"""

_SQL_COLUMNS = """
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = %s
ORDER BY ordinal_position;
"""

_SQL_PRIMARY_KEYS = """
SELECT kcu.column_name
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
  ON tc.constraint_name = kcu.constraint_name
  AND tc.table_schema = kcu.table_schema
WHERE tc.constraint_type = 'PRIMARY KEY'
  AND tc.table_schema = 'public'
  AND tc.table_name = %s;
"""

_SQL_INDEXES = """
SELECT indexname, indexdef
FROM pg_indexes
WHERE schemaname = 'public'
  AND tablename = %s;
"""

_SQL_FOREIGN_KEYS = """
SELECT
    rc.constraint_name,
    kcu.table_name,
    kcu.column_name,
    ccu.table_name  AS ref_table,
    ccu.column_name AS ref_column,
    rc.delete_rule
FROM information_schema.referential_constraints rc
JOIN information_schema.key_column_usage kcu
  ON rc.constraint_name = kcu.constraint_name
  AND rc.constraint_schema = kcu.constraint_schema
JOIN information_schema.constraint_column_usage ccu
  ON rc.unique_constraint_name = ccu.constraint_name
  AND rc.unique_constraint_schema = ccu.constraint_schema
WHERE rc.constraint_schema = 'public'
ORDER BY rc.constraint_name, kcu.ordinal_position;
"""

_SQL_ENUMS = """
SELECT t.typname, e.enumlabel
FROM pg_type t
JOIN pg_enum e ON t.oid = e.enumtypid
JOIN pg_catalog.pg_namespace n ON n.oid = t.typnamespace
WHERE n.nspname = 'public'
ORDER BY t.typname, e.enumsortorder;
"""


def _parse_index_columns(indexdef: str) -> list[str]:
    """Extract column names from an index definition string."""
    match = re.search(r"\((.+)\)$", indexdef)
    if not match:
        return []
    raw = match.group(1)
    return [col.strip().split()[0] for col in raw.split(",")]


class SchemaInspector:
    """Inspects a live PostgreSQL schema and returns a SchemaSnapshot."""

    def __init__(self, dsn: str) -> None:
        """Store DSN; no connection is made until snapshot() is called."""
        self.dsn = dsn

    def snapshot(self) -> SchemaSnapshot:
        """Connect to the database and return a full SchemaSnapshot."""
        conn = psycopg2.connect(self.dsn)
        try:
            return self._build_snapshot(conn)
        finally:
            conn.close()

    def _build_snapshot(self, conn: psycopg2.connection) -> SchemaSnapshot:
        with conn.cursor() as cur:
            tables = self._fetch_tables(cur)
            foreign_keys = self._fetch_foreign_keys(cur)
            enums = self._fetch_enums(cur)
        return SchemaSnapshot(tables=tables, foreign_keys=foreign_keys, enums=enums)

    def _fetch_tables(self, cur: psycopg2.cursor) -> dict[str, TableDef]:
        cur.execute(_SQL_TABLES)
        table_names = [row[0] for row in cur.fetchall()]
        tables: dict[str, TableDef] = {}
        for name in table_names:
            columns = self._fetch_columns(cur, name)
            indexes = self._fetch_indexes(cur, name)
            tables[name] = TableDef(name=name, columns=columns, indexes=indexes)
        return tables

    def _fetch_columns(self, cur: psycopg2.cursor, table: str) -> list[ColumnDef]:
        cur.execute(_SQL_COLUMNS, (table,))
        rows = cur.fetchall()

        cur.execute(_SQL_PRIMARY_KEYS, (table,))
        pk_cols = {row[0] for row in cur.fetchall()}

        columns = []
        for col_name, data_type, is_nullable, col_default in rows:
            columns.append(
                ColumnDef(
                    name=col_name,
                    data_type=data_type,
                    nullable=(is_nullable == "YES"),
                    default=col_default,
                    is_primary_key=(col_name in pk_cols),
                )
            )
        return columns

    def _fetch_indexes(self, cur: psycopg2.cursor, table: str) -> list[IndexDef]:
        cur.execute(_SQL_INDEXES, (table,))
        indexes = []
        for indexname, indexdef in cur.fetchall():
            unique = "UNIQUE" in indexdef.upper()
            method_match = re.search(r"USING\s+(\w+)", indexdef, re.IGNORECASE)
            method = method_match.group(1).lower() if method_match else "btree"
            columns = _parse_index_columns(indexdef)
            indexes.append(
                IndexDef(
                    name=indexname,
                    table=table,
                    columns=columns,
                    unique=unique,
                    method=method,
                )
            )
        return indexes

    def _fetch_foreign_keys(self, cur: psycopg2.cursor) -> list[ForeignKeyDef]:
        cur.execute(_SQL_FOREIGN_KEYS)
        rows = cur.fetchall()

        fks: dict[str, ForeignKeyDef] = {}
        for constraint_name, table, column, ref_table, ref_col, delete_rule in rows:
            if constraint_name not in fks:
                fks[constraint_name] = ForeignKeyDef(
                    name=constraint_name,
                    table=table,
                    columns=[],
                    ref_table=ref_table,
                    ref_columns=[],
                    on_delete=delete_rule,
                )
            fks[constraint_name].columns.append(column)
            fks[constraint_name].ref_columns.append(ref_col)
        return list(fks.values())

    def _fetch_enums(self, cur: psycopg2.cursor) -> dict[str, list[str]]:
        cur.execute(_SQL_ENUMS)
        enums: dict[str, list[str]] = {}
        for typname, enumlabel in cur.fetchall():
            enums.setdefault(typname, []).append(enumlabel)
        return enums
