"""Migration SQL generator: turns a DiffResult into a safe, ordered SQL script."""

from __future__ import annotations

from pg_schema_diff.models import ColumnDef, DiffResult


class MigrationGenerator:
    """Generates an ordered SQL migration script from a DiffResult."""

    def __init__(self, diff: DiffResult) -> None:
        self.diff = diff

    def generate(self) -> str:
        """
        Return a full SQL migration script.

        Order of operations (safe for FK/index dependencies):
        1. DROP foreign keys
        2. DROP indexes
        3. ALTER / DROP columns
        4. DROP tables
        5. CREATE tables
        6. ADD columns
        7. CREATE indexes
        8. ADD foreign keys
        """
        if self.diff.is_empty():
            return "BEGIN;\n-- No schema differences detected.\nCOMMIT;\n"

        statements: list[str] = []

        # 1. DROP foreign keys
        for fk in self.diff.fks_dropped:
            statements.append(
                f"-- Drop foreign key: {fk.name}\n"
                f"ALTER TABLE {_q(fk.table)} DROP CONSTRAINT {_q(fk.name)};"
            )

        # 2. DROP indexes
        for idx in self.diff.indexes_dropped:
            statements.append(f"-- Drop index: {idx.name}\nDROP INDEX IF EXISTS {_q(idx.name)};")

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

        # 5. CREATE tables
        for table in self.diff.tables_added:
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
            cols = ", ".join(_q(c) for c in idx.columns)
            statements.append(
                f"-- Add index: {idx.name}\n"
                f"CREATE {unique_kw}INDEX {_q(idx.name)} ON {_q(idx.table)} "
                f"USING {idx.method} ({cols});"
            )

        # 8. ADD foreign keys
        for fk in self.diff.fks_added:
            src_cols = ", ".join(_q(c) for c in fk.columns)
            ref_cols = ", ".join(_q(c) for c in fk.ref_columns)
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

        body = "\n\n".join(statements)
        return f"BEGIN;\n\n{body}\n\nCOMMIT;\n"


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


def _create_table_statement(table: "pg_schema_diff.models.TableDef") -> str:  # type: ignore[name-defined]
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
