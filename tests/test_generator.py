"""Unit tests for MigrationGenerator (no database required)."""

from __future__ import annotations

from schemadrift.generator import MigrationGenerator
from schemadrift.models import (
    ColumnDef,
    DiffResult,
    ForeignKeyDef,
    IndexDef,
    TableDef,
)


def _empty_diff() -> DiffResult:
    return DiffResult()


class TestTransactionWrapping:
    def test_wraps_in_transaction(self) -> None:
        diff = DiffResult()
        col = ColumnDef(name="id", data_type="integer")
        diff.tables_added.append(TableDef(name="users", columns=[col]))
        sql = MigrationGenerator(diff).generate()
        assert sql.strip().startswith("BEGIN;")
        assert sql.strip().endswith("COMMIT;")

    def test_empty_diff_returns_no_op_comment(self) -> None:
        sql = MigrationGenerator(_empty_diff()).generate()
        assert "-- No schema differences" in sql

    def test_empty_diff_still_wrapped_in_transaction(self) -> None:
        sql = MigrationGenerator(_empty_diff()).generate()
        assert "BEGIN;" in sql
        assert "COMMIT;" in sql


class TestCreateTableSQL:
    def test_generates_create_table_sql(self) -> None:
        diff = DiffResult()
        diff.tables_added.append(
            TableDef(name="users", columns=[ColumnDef(name="id", data_type="integer")])
        )
        sql = MigrationGenerator(diff).generate()
        assert "CREATE TABLE" in sql
        assert '"users"' in sql

    def test_create_table_includes_all_columns(self) -> None:
        diff = DiffResult()
        diff.tables_added.append(
            TableDef(
                name="users",
                columns=[
                    ColumnDef(name="id", data_type="integer", is_primary_key=True),
                    ColumnDef(name="email", data_type="text", nullable=False),
                ],
            )
        )
        sql = MigrationGenerator(diff).generate()
        assert '"id"' in sql
        assert '"email"' in sql
        assert "NOT NULL" in sql
        assert "PRIMARY KEY" in sql

    def test_create_table_has_comment(self) -> None:
        diff = DiffResult()
        diff.tables_added.append(TableDef(name="orders", columns=[]))
        sql = MigrationGenerator(diff).generate()
        assert "-- Add table: orders" in sql


class TestDropTableSQL:
    def test_generates_drop_table_sql(self) -> None:
        diff = DiffResult()
        diff.tables_dropped.append("old_table")
        sql = MigrationGenerator(diff).generate()
        assert "DROP TABLE" in sql
        assert '"old_table"' in sql

    def test_drop_table_uses_if_exists(self) -> None:
        diff = DiffResult()
        diff.tables_dropped.append("stale")
        sql = MigrationGenerator(diff).generate()
        assert "IF EXISTS" in sql


class TestAddColumnSQL:
    def test_generates_add_column_sql(self) -> None:
        diff = DiffResult()
        diff.columns_added.append(("users", ColumnDef(name="phone", data_type="text")))
        sql = MigrationGenerator(diff).generate()
        assert "ALTER TABLE" in sql
        assert "ADD COLUMN" in sql
        assert '"phone"' in sql

    def test_add_column_includes_table_name(self) -> None:
        diff = DiffResult()
        diff.columns_added.append(("accounts", ColumnDef(name="bio", data_type="text")))
        sql = MigrationGenerator(diff).generate()
        assert '"accounts"' in sql


class TestDropColumnSQL:
    def test_generates_drop_column_sql(self) -> None:
        diff = DiffResult()
        diff.columns_dropped.append(("users", "old_column"))
        sql = MigrationGenerator(diff).generate()
        assert "ALTER TABLE" in sql
        assert "DROP COLUMN" in sql
        assert '"old_column"' in sql


class TestAlterColumnSQL:
    def test_generates_alter_type_sql(self) -> None:
        diff = DiffResult()
        diff.columns_altered.append((
            "users",
            ColumnDef(name="age", data_type="integer"),
            ColumnDef(name="age", data_type="bigint"),
        ))
        sql = MigrationGenerator(diff).generate()
        assert "ALTER COLUMN" in sql
        assert "TYPE bigint" in sql


class TestIndexSQL:
    def test_generates_create_index_sql(self) -> None:
        diff = DiffResult()
        diff.indexes_added.append(
            IndexDef(name="idx_users_email", table="users", columns=["email"])
        )
        sql = MigrationGenerator(diff).generate()
        assert "CREATE" in sql
        assert "INDEX" in sql
        assert '"idx_users_email"' in sql

    def test_generates_unique_index_sql(self) -> None:
        diff = DiffResult()
        diff.indexes_added.append(
            IndexDef(name="idx_users_email", table="users", columns=["email"], unique=True)
        )
        sql = MigrationGenerator(diff).generate()
        assert "UNIQUE" in sql

    def test_generates_drop_index_sql(self) -> None:
        diff = DiffResult()
        diff.indexes_dropped.append(IndexDef(name="old_idx", table="users", columns=["col"]))
        sql = MigrationGenerator(diff).generate()
        assert "DROP INDEX" in sql
        assert '"old_idx"' in sql


class TestForeignKeySQL:
    def test_generates_add_fk_sql(self) -> None:
        diff = DiffResult()
        diff.fks_added.append(
            ForeignKeyDef(
                name="fk_orders_user",
                table="orders",
                columns=["user_id"],
                ref_table="users",
                ref_columns=["id"],
            )
        )
        sql = MigrationGenerator(diff).generate()
        assert "FOREIGN KEY" in sql
        assert "REFERENCES" in sql

    def test_generates_drop_fk_sql(self) -> None:
        diff = DiffResult()
        diff.fks_dropped.append(
            ForeignKeyDef(
                name="fk_orders_user",
                table="orders",
                columns=["user_id"],
                ref_table="users",
                ref_columns=["id"],
            )
        )
        sql = MigrationGenerator(diff).generate()
        assert "DROP CONSTRAINT" in sql
        assert '"fk_orders_user"' in sql


class TestStatementOrdering:
    def test_drop_fk_before_drop_table(self) -> None:
        """DROP FK must appear before DROP TABLE in the output."""
        diff = DiffResult()
        diff.fks_dropped.append(
            ForeignKeyDef(
                name="fk_orders_user",
                table="orders",
                columns=["user_id"],
                ref_table="users",
                ref_columns=["id"],
            )
        )
        diff.tables_dropped.append("orders")
        sql = MigrationGenerator(diff).generate()
        fk_pos = sql.index("DROP CONSTRAINT")
        tbl_pos = sql.index("DROP TABLE")
        assert fk_pos < tbl_pos

    def test_create_table_before_add_column(self) -> None:
        diff = DiffResult()
        diff.tables_added.append(TableDef(name="users", columns=[]))
        diff.columns_added.append(("users", ColumnDef(name="email", data_type="text")))
        sql = MigrationGenerator(diff).generate()
        create_pos = sql.index("CREATE TABLE")
        add_pos = sql.index("ADD COLUMN")
        assert create_pos < add_pos
