"""Migration SQL generator: turns a DiffResult into a safe, ordered SQL script."""

from __future__ import annotations

import collections

from schemadrift.models import ColumnDef, DiffResult, ForeignKeyDef, TableDef


def topological_sort_tables(
    tables: list[TableDef],
    foreign_keys: list[ForeignKeyDef] | None = None,
) -> list[TableDef]:
    """Sort TableDef objects in topological dependency order (referenced tables before dependents).

    Uses Kahn's algorithm for directed acyclic graph (DAG) topological sorting.
    If circular dependencies exist between newly added tables, remaining tables in the cycle
    are resolved deterministically by table name, allowing deferred foreign key creation.
    """
    if len(tables) <= 1:
        return list(tables)

    tbl_map = {t.name: t for t in tables}
    table_names = set(tbl_map.keys())

    graph: dict[str, set[str]] = {name: set() for name in table_names}
    in_degree: dict[str, int] = dict.fromkeys(table_names, 0)

    if foreign_keys:
        for fk in foreign_keys:
            if (
                fk.table in table_names
                and fk.ref_table in table_names
                and fk.table != fk.ref_table
            ):
                parent = fk.ref_table
                child = fk.table
                if child not in graph[parent]:
                    graph[parent].add(child)
                    in_degree[child] += 1

    queue = collections.deque(
        sorted([name for name, deg in in_degree.items() if deg == 0])
    )
    sorted_names: list[str] = []

    while queue:
        node = queue.popleft()
        sorted_names.append(node)
        for neighbor in sorted(graph[node]):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if len(sorted_names) < len(table_names):
        remaining = sorted([name for name in table_names if name not in sorted_names])
        sorted_names.extend(remaining)

    return [tbl_map[name] for name in sorted_names]


class MigrationGenerator:
    """Generates an ordered SQL migration script from a DiffResult."""

    def __init__(
        self,
        diff: DiffResult,
        transaction: bool | None = None,
        concurrent_indexes: bool = False,
        two_phase_fk: bool = False,
        lock_timeout: str | None = None,
        statement_timeout: str | None = None,
        safe_mode: bool = False,
    ) -> None:
        self.diff = diff
        self.concurrent_indexes = concurrent_indexes
        self.two_phase_fk = two_phase_fk or safe_mode
        self.lock_timeout = lock_timeout or ("2s" if safe_mode else None)
        self.statement_timeout = statement_timeout or ("30s" if safe_mode else None)
        self.safe_mode = safe_mode

        if transaction is None:
            self.transaction = not concurrent_indexes
        else:
            self.transaction = transaction

    def generate(self) -> str:
        """
        Return a full SQL migration script.

        Order of operations (safe for FK/index dependencies):
        1. DROP foreign keys
        2. DROP indexes
        3. ALTER / DROP columns
        4. DROP tables
        5. CREATE tables (topologically ordered by FK dependencies)
        6. ADD columns
        7. CREATE indexes
        8. ADD foreign keys (with optional NOT VALID two-phase safety)
        9. ADD enum values
        10. VALIDATE constraints (for two-phase foreign keys)
        """
        timeout_headers: list[str] = []
        if self.lock_timeout:
            timeout_headers.append(f"SET lock_timeout = '{self.lock_timeout}';")
        if self.statement_timeout:
            timeout_headers.append(f"SET statement_timeout = '{self.statement_timeout}';")
        timeout_str = ("\n".join(timeout_headers) + "\n\n") if timeout_headers else ""

        if self.diff.is_empty():
            if self.transaction:
                return f"BEGIN;\n{timeout_str}-- No schema differences detected.\nCOMMIT;\n"
            if timeout_str:
                return f"{timeout_str}-- No schema differences detected.\n"
            return "-- No schema differences detected.\n"

        statements: list[str] = []

        # 1. DROP foreign keys
        for fk in self.diff.fks_dropped:
            statements.append(
                f"-- Drop foreign key: {fk.name}\n"
                f"ALTER TABLE {_q(fk.table)} DROP CONSTRAINT {_q(fk.name)};"
            )

        # 2. DROP indexes
        for idx in self.diff.indexes_dropped:
            concurrent_kw = "CONCURRENTLY " if self.concurrent_indexes else ""
            statements.append(
                f"-- Drop index: {idx.name}\nDROP INDEX {concurrent_kw}IF EXISTS {_q(idx.name)};"
            )

        # 3. ALTER columns (type changes), DROP columns
        for table_name, src_col, tgt_col in self.diff.columns_altered:
            statements.extend(_alter_column_statements(table_name, src_col, tgt_col))

        for table_name, col_name in self.diff.columns_dropped:
            statements.append(
                f"-- Drop column: {table_name}.{col_name}\n"
                f"ALTER TABLE {_q(table_name)} DROP COLUMN IF EXISTS {_q(col_name)};"
            )

        # 4. DROP tables
        for table_name in self.diff.tables_dropped:
            statements.append(
                f"-- Drop table: {table_name}\nDROP TABLE IF EXISTS {_q(table_name)};"
            )

        # 5. CREATE tables (ordered topologically by FK dependencies)
        ordered_tables = topological_sort_tables(self.diff.tables_added, self.diff.fks_added)
        for table in ordered_tables:
            statements.append(_create_table_statement(table))

        # 6. ADD columns
        for table_name, col in self.diff.columns_added:
            statements.append(
                f"-- Add column: {table_name}.{col.name}\n"
                f"ALTER TABLE {_q(table_name)} ADD COLUMN {_column_def_sql(col)};"
            )

        # 7. CREATE indexes
        for idx in self.diff.indexes_added:
            unique_kw = "UNIQUE " if idx.unique else ""
            concurrent_kw = "CONCURRENTLY " if self.concurrent_indexes else ""
            cols = ", ".join(_q(c) for c in idx.columns)
            statements.append(
                f"-- Add index: {idx.name}\n"
                f"CREATE {unique_kw}INDEX {concurrent_kw}{_q(idx.name)} ON {_q(idx.table)} "
                f"USING {idx.method} ({cols});"
            )

        # 8. ADD foreign keys (with optional two-phase zero-downtime NOT VALID)
        validation_statements: list[str] = []
        for fk in self.diff.fks_added:
            src_cols = ", ".join(_q(c) for c in fk.columns)
            ref_cols = ", ".join(_q(c) for c in fk.ref_columns)
            if self.two_phase_fk:
                statements.append(
                    f"-- Add foreign key (not valid for zero-downtime): {fk.name}\n"
                    f"ALTER TABLE {_q(fk.table)} ADD CONSTRAINT {_q(fk.name)} "
                    f"FOREIGN KEY ({src_cols}) REFERENCES {_q(fk.ref_table)} ({ref_cols}) "
                    f"ON DELETE {fk.on_delete} NOT VALID;"
                )
                validation_statements.append(
                    f"-- Validate foreign key: {fk.name}\n"
                    f"ALTER TABLE {_q(fk.table)} VALIDATE CONSTRAINT {_q(fk.name)};"
                )
            else:
                statements.append(
                    f"-- Add foreign key: {fk.name}\n"
                    f"ALTER TABLE {_q(fk.table)} ADD CONSTRAINT {_q(fk.name)} "
                    f"FOREIGN KEY ({src_cols}) REFERENCES {_q(fk.ref_table)} ({ref_cols}) "
                    f"ON DELETE {fk.on_delete};"
                )

        # 9. Enum additions (informational – add values)
        for enum_name, labels in self.diff.enums_added:
            for label in labels:
                statements.append(
                    f"-- Add enum value to {enum_name}\n"
                    f"ALTER TYPE {_q(enum_name)} ADD VALUE IF NOT EXISTS '{label}';"
                )

        # 10. Constraint validations (phase 2 of zero-downtime foreign keys)
        if validation_statements:
            statements.extend(validation_statements)

        body = "\n\n".join(statements)
        if self.transaction:
            return f"BEGIN;\n\n{timeout_str}{body}\n\nCOMMIT;\n"
        if timeout_str:
            return f"{timeout_str}{body}\n"
        return f"{body}\n"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _q(name: str) -> str:
    """Quote a PostgreSQL identifier."""
    return f'"{name}"'


def _column_def_sql(col: ColumnDef) -> str:
    """Return the SQL fragment for a column definition (name type [NOT NULL] [DEFAULT ...])."""
    parts = [_q(col.name), col.data_type]
    if not col.nullable:
        parts.append("NOT NULL")
    if col.default is not None:
        parts.append(f"DEFAULT {col.default}")
    return " ".join(parts)


def _create_table_statement(table: TableDef) -> str:
    """Return a CREATE TABLE SQL statement for the given TableDef."""
    col_lines = []
    pk_cols = [c.name for c in table.columns if c.is_primary_key]

    for col in table.columns:
        col_lines.append(f"    {_column_def_sql(col)}")

    if pk_cols:
        pk_list = ", ".join(_q(c) for c in pk_cols)
        col_lines.append(f"    PRIMARY KEY ({pk_list})")

    cols_sql = ",\n".join(col_lines)
    return f"-- Add table: {table.name}\nCREATE TABLE {_q(table.name)} (\n{cols_sql}\n);"


def _alter_column_statements(table_name: str, src: ColumnDef, tgt: ColumnDef) -> list[str]:
    """Return ALTER TABLE statements needed to transition src column to tgt column."""
    stmts = []
    if src.data_type != tgt.data_type:
        stmts.append(
            f"-- Alter column type: {table_name}.{tgt.name}\n"
            f"ALTER TABLE {_q(table_name)} ALTER COLUMN {_q(tgt.name)} "
            f"TYPE {tgt.data_type};"
        )
    if src.nullable != tgt.nullable:
        if tgt.nullable:
            stmts.append(
                f"-- Allow NULL: {table_name}.{tgt.name}\n"
                f"ALTER TABLE {_q(table_name)} ALTER COLUMN {_q(tgt.name)} DROP NOT NULL;"
            )
        else:
            stmts.append(
                f"-- Set NOT NULL: {table_name}.{tgt.name}\n"
                f"ALTER TABLE {_q(table_name)} ALTER COLUMN {_q(tgt.name)} SET NOT NULL;"
            )
    if src.default != tgt.default:
        if tgt.default is None:
            stmts.append(
                f"-- Drop default: {table_name}.{tgt.name}\n"
                f"ALTER TABLE {_q(table_name)} ALTER COLUMN {_q(tgt.name)} DROP DEFAULT;"
            )
        else:
            stmts.append(
                f"-- Set default: {table_name}.{tgt.name}\n"
                f"ALTER TABLE {_q(table_name)} ALTER COLUMN {_q(tgt.name)} "
                f"SET DEFAULT {tgt.default};"
            )
    return stmts
