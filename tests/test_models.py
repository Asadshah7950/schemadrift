"""Unit tests for schemadrift.models dataclasses."""

from __future__ import annotations

from schemadrift.models import (
    ColumnDef,
    DiffResult,
    ForeignKeyDef,
    IndexDef,
    SchemaSnapshot,
    TableDef,
)


class TestColumnDef:
    def test_required_fields(self) -> None:
        col = ColumnDef(name="id", data_type="integer")
        assert col.name == "id"
        assert col.data_type == "integer"

    def test_default_nullable_true(self) -> None:
        col = ColumnDef(name="x", data_type="text")
        assert col.nullable is True

    def test_default_no_default_value(self) -> None:
        col = ColumnDef(name="x", data_type="text")
        assert col.default is None

    def test_default_not_primary_key(self) -> None:
        col = ColumnDef(name="x", data_type="text")
        assert col.is_primary_key is False

    def test_explicit_primary_key(self) -> None:
        col = ColumnDef(name="id", data_type="integer", is_primary_key=True)
        assert col.is_primary_key is True

    def test_explicit_not_nullable(self) -> None:
        col = ColumnDef(name="email", data_type="text", nullable=False)
        assert col.nullable is False

    def test_explicit_default(self) -> None:
        col = ColumnDef(name="active", data_type="boolean", default="true")
        assert col.default == "true"


class TestIndexDef:
    def test_defaults(self) -> None:
        idx = IndexDef(name="idx_users_email", table="users", columns=["email"])
        assert idx.unique is False
        assert idx.method == "btree"

    def test_unique_index(self) -> None:
        idx = IndexDef(name="idx_users_email", table="users", columns=["email"], unique=True)
        assert idx.unique is True


class TestTableDef:
    def test_empty_table(self) -> None:
        t = TableDef(name="users")
        assert t.name == "users"
        assert t.columns == []
        assert t.indexes == []

    def test_table_with_columns(self) -> None:
        col = ColumnDef(name="id", data_type="integer")
        t = TableDef(name="users", columns=[col])
        assert len(t.columns) == 1


class TestForeignKeyDef:
    def test_default_on_delete(self) -> None:
        fk = ForeignKeyDef(
            name="fk_orders_user",
            table="orders",
            columns=["user_id"],
            ref_table="users",
            ref_columns=["id"],
        )
        assert fk.on_delete == "NO ACTION"

    def test_cascade_on_delete(self) -> None:
        fk = ForeignKeyDef(
            name="fk_orders_user",
            table="orders",
            columns=["user_id"],
            ref_table="users",
            ref_columns=["id"],
            on_delete="CASCADE",
        )
        assert fk.on_delete == "CASCADE"


class TestSchemaSnapshot:
    def test_empty_snapshot(self) -> None:
        snap = SchemaSnapshot()
        assert snap.tables == {}
        assert snap.foreign_keys == []
        assert snap.enums == {}

    def test_snapshot_with_data(self) -> None:
        t = TableDef(name="users")
        snap = SchemaSnapshot(tables={"users": t})
        assert "users" in snap.tables


class TestDiffResult:
    def test_initially_all_empty_lists(self) -> None:
        dr = DiffResult()
        assert dr.tables_added == []
        assert dr.tables_dropped == []
        assert dr.columns_added == []
        assert dr.columns_dropped == []
        assert dr.columns_altered == []
        assert dr.indexes_added == []
        assert dr.indexes_dropped == []
        assert dr.fks_added == []
        assert dr.fks_dropped == []
        assert dr.enums_added == []
        assert dr.enums_altered == []

    def test_is_empty_when_no_diffs(self) -> None:
        dr = DiffResult()
        assert dr.is_empty() is True

    def test_is_not_empty_when_has_diff(self) -> None:
        dr = DiffResult()
        dr.tables_dropped.append("users")
        assert dr.is_empty() is False
