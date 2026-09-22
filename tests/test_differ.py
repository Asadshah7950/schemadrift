"""Unit tests for SchemaDiffer (no database required)."""

from __future__ import annotations

from pg_schema_diff.differ import SchemaDiffer
from pg_schema_diff.models import ColumnDef, IndexDef, SchemaSnapshot, TableDef


def _make_table(
    name: str,
    columns: list[ColumnDef] | None = None,
    indexes: list[IndexDef] | None = None,
) -> TableDef:
    return TableDef(name=name, columns=columns or [], indexes=indexes or [])


def _make_snapshot(*tables: TableDef) -> SchemaSnapshot:
    return SchemaSnapshot(tables={t.name: t for t in tables})


class TestTableDiff:
    def test_detects_added_table(self) -> None:
        source = _make_snapshot()
        new_table = _make_table("users")
        target = _make_snapshot(new_table)

        result = SchemaDiffer(source, target).diff()

        assert len(result.tables_added) == 1
        assert result.tables_added[0].name == "users"
        assert result.tables_dropped == []

    def test_detects_dropped_table(self) -> None:
        existing = _make_table("orders")
        source = _make_snapshot(existing)
        target = _make_snapshot()

        result = SchemaDiffer(source, target).diff()

        assert "orders" in result.tables_dropped
        assert result.tables_added == []

    def test_no_diff_identical_schemas(self) -> None:
        col = ColumnDef(name="id", data_type="integer")
        table = _make_table("users", columns=[col])
        source = _make_snapshot(table)
        # Build a fresh copy so they're not the same object
        col2 = ColumnDef(name="id", data_type="integer")
        table2 = _make_table("users", columns=[col2])
        target = _make_snapshot(table2)

        result = SchemaDiffer(source, target).diff()

        assert result.is_empty()

    def test_multiple_tables_added_and_dropped(self) -> None:
        t1 = _make_table("users")
        t2 = _make_table("orders")
        source = _make_snapshot(t1)
        target = _make_snapshot(t2)

        result = SchemaDiffer(source, target).diff()

        assert len(result.tables_added) == 1
        assert result.tables_added[0].name == "orders"
        assert "users" in result.tables_dropped


class TestColumnDiff:
    def test_detects_added_column(self) -> None:
        id_col = ColumnDef(name="id", data_type="integer")
        src_table = _make_table("users", columns=[id_col])
        source = _make_snapshot(src_table)

        email_col = ColumnDef(name="email", data_type="text")
        tgt_table = _make_table("users", columns=[id_col, email_col])
        target = _make_snapshot(tgt_table)

        result = SchemaDiffer(source, target).diff()

        assert len(result.columns_added) == 1
        table_name, col = result.columns_added[0]
        assert table_name == "users"
        assert col.name == "email"

    def test_detects_dropped_column(self) -> None:
        id_col = ColumnDef(name="id", data_type="integer")
        email_col = ColumnDef(name="email", data_type="text")
        src_table = _make_table("users", columns=[id_col, email_col])
        source = _make_snapshot(src_table)

        tgt_table = _make_table("users", columns=[id_col])
        target = _make_snapshot(tgt_table)

        result = SchemaDiffer(source, target).diff()

        assert len(result.columns_dropped) == 1
        table_name, col_name = result.columns_dropped[0]
        assert table_name == "users"
        assert col_name == "email"

    def test_detects_altered_column_type(self) -> None:
        src_col = ColumnDef(name="age", data_type="integer")
        src_table = _make_table("users", columns=[src_col])
        source = _make_snapshot(src_table)

        tgt_col = ColumnDef(name="age", data_type="bigint")
        tgt_table = _make_table("users", columns=[tgt_col])
        target = _make_snapshot(tgt_table)

        result = SchemaDiffer(source, target).diff()

        assert len(result.columns_altered) == 1
        table_name, old_col, new_col = result.columns_altered[0]
        assert table_name == "users"
        assert old_col.data_type == "integer"
        assert new_col.data_type == "bigint"

    def test_detects_altered_column_nullable(self) -> None:
        src_col = ColumnDef(name="email", data_type="text", nullable=True)
        src_table = _make_table("users", columns=[src_col])
        source = _make_snapshot(src_table)

        tgt_col = ColumnDef(name="email", data_type="text", nullable=False)
        tgt_table = _make_table("users", columns=[tgt_col])
        target = _make_snapshot(tgt_table)

        result = SchemaDiffer(source, target).diff()

        assert len(result.columns_altered) == 1

    def test_no_false_positive_on_identical_columns(self) -> None:
        col = ColumnDef(name="id", data_type="integer", nullable=False, default=None)
        src_table = _make_table("users", columns=[col])
        tgt_col = ColumnDef(name="id", data_type="integer", nullable=False, default=None)
        tgt_table = _make_table("users", columns=[tgt_col])

        result = SchemaDiffer(_make_snapshot(src_table), _make_snapshot(tgt_table)).diff()

        assert result.columns_altered == []


class TestIndexDiff:
    def test_detects_added_index(self) -> None:
        col = ColumnDef(name="email", data_type="text")
        src_table = _make_table("users", columns=[col])
        source = _make_snapshot(src_table)

        idx = IndexDef(name="idx_users_email", table="users", columns=["email"])
        tgt_table = _make_table("users", columns=[col], indexes=[idx])
        target = _make_snapshot(tgt_table)

        result = SchemaDiffer(source, target).diff()

        assert len(result.indexes_added) == 1
        assert result.indexes_added[0].name == "idx_users_email"

    def test_detects_dropped_index(self) -> None:
        col = ColumnDef(name="email", data_type="text")
        idx = IndexDef(name="idx_users_email", table="users", columns=["email"])
        src_table = _make_table("users", columns=[col], indexes=[idx])
        source = _make_snapshot(src_table)

        tgt_table = _make_table("users", columns=[col])
        target = _make_snapshot(tgt_table)

        result = SchemaDiffer(source, target).diff()

        assert len(result.indexes_dropped) == 1
        assert result.indexes_dropped[0].name == "idx_users_email"

    def test_no_index_diff_when_identical(self) -> None:
        col = ColumnDef(name="email", data_type="text")
        idx = IndexDef(name="idx_users_email", table="users", columns=["email"])
        src_table = _make_table("users", columns=[col], indexes=[idx])
        tgt_idx = IndexDef(name="idx_users_email", table="users", columns=["email"])
        tgt_table = _make_table("users", columns=[col], indexes=[tgt_idx])

        result = SchemaDiffer(_make_snapshot(src_table), _make_snapshot(tgt_table)).diff()

        assert result.indexes_added == []
        assert result.indexes_dropped == []
