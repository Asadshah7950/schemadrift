"""Unit tests for schemadrift.cli using Click CliRunner."""

from __future__ import annotations

import json
from unittest.mock import patch

from click.testing import CliRunner

from schemadrift.cli import _diff_to_markdown, main
from schemadrift.models import (
    ColumnDef,
    DiffResult,
    ForeignKeyDef,
    IndexDef,
    SchemaSnapshot,
    TableDef,
)


def _make_sample_snapshot_with_drift() -> SchemaSnapshot:
    col_id = ColumnDef(name="id", data_type="integer", is_primary_key=True)
    col_name = ColumnDef(name="name", data_type="varchar(255)")
    idx = IndexDef(name="idx_users_name", table="users", columns=["name"])
    table = TableDef(name="users", columns=[col_id, col_name], indexes=[idx])
    fk = ForeignKeyDef(
        name="fk_orders_user",
        table="orders",
        columns=["user_id"],
        ref_table="users",
        ref_columns=["id"],
    )
    return SchemaSnapshot(
        tables={"users": table},
        foreign_keys=[fk],
        enums={"user_status": ["active", "inactive"]},
    )


class TestDiffCommand:
    def test_diff_no_changes(self) -> None:
        runner = CliRunner()
        snap = SchemaSnapshot()

        with patch("schemadrift.cli.SchemaInspector") as mock_insp:
            mock_insp.return_value.snapshot.return_value = snap
            res = runner.invoke(main, ["diff", "--source", "pg://src", "--target", "pg://tgt"])

            assert res.exit_code == 0
            assert "-- No schema differences detected." in res.output

    def test_diff_exclude_tables(self) -> None:
        runner = CliRunner()
        src = SchemaSnapshot()
        tgt = SchemaSnapshot(tables={"alembic_version": TableDef(name="alembic_version")})

        with patch("schemadrift.cli.SchemaInspector") as mock_insp:
            mock_insp.return_value.snapshot.side_effect = [src, tgt]
            res = runner.invoke(
                main,
                ["diff", "--source", "pg://src", "--target", "pg://tgt", "-e", "alembic_version"],
            )

            assert res.exit_code == 0
            assert "-- No schema differences detected." in res.output

    def test_diff_json_format(self) -> None:
        runner = CliRunner()
        src = SchemaSnapshot()
        tgt = _make_sample_snapshot_with_drift()

        with patch("schemadrift.cli.SchemaInspector") as mock_insp:
            mock_insp.return_value.snapshot.side_effect = [src, tgt]
            res = runner.invoke(
                main,
                ["diff", "--source", "pg://src", "--target", "pg://tgt", "--format", "json"],
            )

            assert res.exit_code == 0
            parsed = json.loads(res.output)
            assert "users" in parsed["tables_added"]
            assert len(parsed["fks_added"]) == 1

    def test_diff_summary_format(self) -> None:
        runner = CliRunner()
        src = SchemaSnapshot()
        tgt = _make_sample_snapshot_with_drift()

        with patch("schemadrift.cli.SchemaInspector") as mock_insp:
            mock_insp.return_value.snapshot.side_effect = [src, tgt]
            res = runner.invoke(
                main,
                ["diff", "--source", "pg://src", "--target", "pg://tgt", "--format", "summary"],
            )

            assert res.exit_code == 0
            assert "Tables added:    1" in res.output

    def test_diff_markdown_format(self) -> None:
        runner = CliRunner()
        src = SchemaSnapshot()
        tgt = _make_sample_snapshot_with_drift()

        with patch("schemadrift.cli.SchemaInspector") as mock_insp:
            mock_insp.return_value.snapshot.side_effect = [src, tgt]
            res = runner.invoke(
                main,
                ["diff", "--source", "pg://src", "--target", "pg://tgt", "--format", "markdown"],
            )

            assert res.exit_code == 0
            assert "### 🔍 PostgreSQL Schema Drift Report" in res.output
            assert "| **Tables Added** | 🟢 Added | `1` | `users` |" in res.output

    def test_fail_on_drift_fails_when_drift_present(self) -> None:
        runner = CliRunner()
        src = SchemaSnapshot()
        tgt = _make_sample_snapshot_with_drift()

        with patch("schemadrift.cli.SchemaInspector") as mock_insp:
            mock_insp.return_value.snapshot.side_effect = [src, tgt]
            res = runner.invoke(
                main,
                ["diff", "--source", "pg://src", "--target", "pg://tgt", "--fail-on-drift"],
            )

            assert res.exit_code == 1

    def test_fail_on_drift_passes_when_no_drift(self) -> None:
        runner = CliRunner()
        snap = SchemaSnapshot()

        with patch("schemadrift.cli.SchemaInspector") as mock_insp:
            mock_insp.return_value.snapshot.side_effect = [snap, snap]
            res = runner.invoke(
                main,
                ["diff", "--source", "pg://src", "--target", "pg://tgt", "--fail-on-drift"],
            )

            assert res.exit_code == 0

    def test_fail_on_destructive_fails_when_table_dropped(self) -> None:
        runner = CliRunner()
        src = _make_sample_snapshot_with_drift()
        tgt = SchemaSnapshot()

        with patch("schemadrift.cli.SchemaInspector") as mock_insp:
            mock_insp.return_value.snapshot.side_effect = [src, tgt]
            res = runner.invoke(
                main,
                ["diff", "--source", "pg://src", "--target", "pg://tgt", "--fail-on-destructive"],
            )

            assert res.exit_code == 2
            assert "Destructive changes detected" in res.output

    def test_fail_on_destructive_short_flag(self) -> None:
        runner = CliRunner()
        src = _make_sample_snapshot_with_drift()
        tgt = SchemaSnapshot()

        with patch("schemadrift.cli.SchemaInspector") as mock_insp:
            mock_insp.return_value.snapshot.side_effect = [src, tgt]
            res = runner.invoke(
                main,
                ["diff", "--source", "pg://src", "--target", "pg://tgt", "-w"],
            )

            assert res.exit_code == 2
            assert "Destructive changes detected" in res.output

    def test_fail_on_destructive_passes_when_only_additive(self) -> None:
        runner = CliRunner()
        src = SchemaSnapshot()
        tgt = _make_sample_snapshot_with_drift()

        with patch("schemadrift.cli.SchemaInspector") as mock_insp:
            mock_insp.return_value.snapshot.side_effect = [src, tgt]
            res = runner.invoke(
                main,
                ["diff", "--source", "pg://src", "--target", "pg://tgt", "--fail-on-destructive"],
            )

            assert res.exit_code == 0

    def test_fail_on_destructive_passes_when_no_drift(self) -> None:
        runner = CliRunner()
        snap = SchemaSnapshot()

        with patch("schemadrift.cli.SchemaInspector") as mock_insp:
            mock_insp.return_value.snapshot.side_effect = [snap, snap]
            res = runner.invoke(
                main,
                ["diff", "--source", "pg://src", "--target", "pg://tgt", "--fail-on-destructive"],
            )

            assert res.exit_code == 0

    def test_diff_output_to_file(self, tmp_path) -> None:
        runner = CliRunner()
        snap = SchemaSnapshot()
        out_file = str(tmp_path / "migration.sql")

        with patch("schemadrift.cli.SchemaInspector") as mock_insp:
            mock_insp.return_value.snapshot.return_value = snap
            res = runner.invoke(
                main,
                ["diff", "--source", "pg://src", "--target", "pg://tgt", "--output", out_file],
            )

            assert res.exit_code == 0
            with open(out_file, encoding="utf-8") as f:
                content = f.read()
            assert "-- No schema differences detected." in content

    def test_diff_source_connection_error(self) -> None:
        runner = CliRunner()
        with patch("schemadrift.cli.SchemaInspector") as mock_insp:
            mock_insp.return_value.snapshot.side_effect = ConnectionError("Could not connect")
            res = runner.invoke(main, ["diff", "--source", "pg://invalid", "--target", "pg://tgt"])
            assert res.exit_code == 1
            assert "Error connecting to source database" in res.output

    def test_diff_target_connection_error(self) -> None:
        runner = CliRunner()
        with patch("schemadrift.cli.SchemaInspector") as mock_insp:
            mock_insp.return_value.snapshot.side_effect = [
                SchemaSnapshot(),
                ConnectionError("Target down"),
            ]
            res = runner.invoke(main, ["diff", "--source", "pg://src", "--target", "pg://invalid"])
            assert res.exit_code == 1
            assert "Error connecting to target database" in res.output

    def test_diff_direction_down(self) -> None:
        runner = CliRunner()
        src = SchemaSnapshot()
        tgt = _make_sample_snapshot_with_drift()

        with patch("schemadrift.cli.SchemaInspector") as mock_insp:
            mock_insp.return_value.snapshot.side_effect = [src, tgt]
            res = runner.invoke(
                main,
                ["diff", "--source", "pg://src", "--target", "pg://tgt", "--direction", "down"],
            )
            assert res.exit_code == 0
            # Target has 'users' and source doesn't, so down migration (tgt -> src)
            # should generate DROP TABLE users
            assert "DROP TABLE" in res.output
            assert '"users"' in res.output

    def test_diff_no_transaction(self) -> None:
        runner = CliRunner()
        snap = SchemaSnapshot()

        with patch("schemadrift.cli.SchemaInspector") as mock_insp:
            mock_insp.return_value.snapshot.return_value = snap
            res = runner.invoke(
                main,
                ["diff", "--source", "pg://src", "--target", "pg://tgt", "--no-transaction"],
            )
            assert res.exit_code == 0
            assert "BEGIN;" not in res.output
            assert "COMMIT;" not in res.output
            assert "-- No schema differences detected." in res.output

    def test_diff_concurrently(self) -> None:
        runner = CliRunner()
        col_id = ColumnDef(name="id", data_type="integer", is_primary_key=True)
        col_name = ColumnDef(name="name", data_type="varchar(255)")
        src_table = TableDef(name="users", columns=[col_id, col_name], indexes=[])
        src = SchemaSnapshot(tables={"users": src_table})
        tgt = _make_sample_snapshot_with_drift()

        with patch("schemadrift.cli.SchemaInspector") as mock_insp:
            mock_insp.return_value.snapshot.side_effect = [src, tgt]
            res = runner.invoke(
                main,
                ["diff", "--source", "pg://src", "--target", "pg://tgt", "--concurrently"],
            )
            assert res.exit_code == 0
            assert "CREATE INDEX CONCURRENTLY" in res.output
            assert "BEGIN;" not in res.output
            assert "COMMIT;" not in res.output


class TestInspectCommand:
    def test_inspect_prints_table(self) -> None:
        runner = CliRunner()
        snap = _make_sample_snapshot_with_drift()

        with patch("schemadrift.cli.SchemaInspector") as mock_insp:
            mock_insp.return_value.snapshot.return_value = snap
            res = runner.invoke(main, ["inspect", "--dsn", "pg://db"])

            assert res.exit_code == 0
            assert "users" in res.output
            assert "Enums (1)" in res.output

    def test_inspect_connection_error(self) -> None:
        runner = CliRunner()
        with patch("schemadrift.cli.SchemaInspector") as mock_insp:
            mock_insp.return_value.snapshot.side_effect = ConnectionError("Refused")
            res = runner.invoke(main, ["inspect", "--dsn", "pg://invalid"])

            assert res.exit_code == 1
            assert "Error connecting to database" in res.output

    def test_inspect_missing_options(self) -> None:
        runner = CliRunner()
        res = runner.invoke(main, ["inspect"])
        assert res.exit_code == 1
        assert "Error: Must provide either --dsn or --file." in res.output

    def test_inspect_from_json_file(self, tmp_path) -> None:
        runner = CliRunner()
        snap = SchemaSnapshot(
            tables={"products": TableDef(name="products", columns=[ColumnDef("id", "int")])},
            enums={"status": ["active"]},
            foreign_keys=[ForeignKeyDef("fk1", "products", ["cat_id"], "categories", ["id"])],
        )
        file_path = tmp_path / "schema.json"
        snap.to_file(str(file_path))

        res = runner.invoke(main, ["inspect", "--file", str(file_path)])
        assert res.exit_code == 0
        assert "products" in res.output
        assert "Enums (1): status" in res.output
        assert "Foreign keys: 1" in res.output

    def test_inspect_from_invalid_file(self) -> None:
        runner = CliRunner()
        res = runner.invoke(main, ["inspect", "--file", "nonexistent_file_12345.json"])
        assert res.exit_code == 1
        assert "Error reading snapshot file" in res.output


class TestSnapshotCommand:
    def test_snapshot_stdout(self) -> None:
        runner = CliRunner()
        snap = SchemaSnapshot(
            tables={"users": TableDef(name="users")},
            enums={"role": ["admin", "member"]},
        )
        with patch("schemadrift.cli.SchemaInspector") as mock_insp:
            mock_insp.return_value.snapshot.return_value = snap
            res = runner.invoke(main, ["snapshot", "--dsn", "pg://db"])

            assert res.exit_code == 0
            data = json.loads(res.output)
            assert data["version"] == "1.0"
            assert "users" in data["tables"]
            assert data["enums"]["role"] == ["admin", "member"]

    def test_snapshot_to_output_file(self, tmp_path) -> None:
        runner = CliRunner()
        snap = SchemaSnapshot(tables={"orders": TableDef(name="orders")})
        out_file = tmp_path / "dump.json"

        with patch("schemadrift.cli.SchemaInspector") as mock_insp:
            mock_insp.return_value.snapshot.return_value = snap
            res = runner.invoke(main, ["snapshot", "--dsn", "pg://db", "-o", str(out_file)])

            assert res.exit_code == 0
            assert "written to" in res.output
            assert out_file.exists()
            restored = SchemaSnapshot.from_file(str(out_file))
            assert "orders" in restored.tables

    def test_snapshot_compact(self) -> None:
        runner = CliRunner()
        snap = SchemaSnapshot()
        with patch("schemadrift.cli.SchemaInspector") as mock_insp:
            mock_insp.return_value.snapshot.return_value = snap
            res = runner.invoke(main, ["snapshot", "--dsn", "pg://db", "--compact"])

            assert res.exit_code == 0
            # Compact json shouldn't have indent spaces
            assert '{\n  "version"' not in res.output

    def test_snapshot_connection_error(self) -> None:
        runner = CliRunner()
        with patch("schemadrift.cli.SchemaInspector") as mock_insp:
            mock_insp.return_value.snapshot.side_effect = ConnectionError("Connection refused")
            res = runner.invoke(main, ["snapshot", "--dsn", "pg://fail"])

            assert res.exit_code == 1
            assert "Error connecting to database" in res.output


class TestDiffWithJsonFiles:
    def test_diff_two_json_files(self, tmp_path) -> None:
        runner = CliRunner()
        src_snap = SchemaSnapshot(tables={"users": TableDef(name="users")})
        tgt_snap = SchemaSnapshot(
            tables={
                "users": TableDef(name="users"),
                "orders": TableDef(name="orders", columns=[ColumnDef("id", "int")]),
            }
        )
        src_file = tmp_path / "src.json"
        tgt_file = tmp_path / "tgt.json"
        src_snap.to_file(str(src_file))
        tgt_snap.to_file(str(tgt_file))

        # Diffing without database connection!
        res = runner.invoke(main, ["diff", "--source", str(src_file), "--target", str(tgt_file)])
        assert res.exit_code == 0
        assert 'CREATE TABLE "orders"' in res.output

    def test_diff_source_file_error(self) -> None:
        runner = CliRunner()
        res = runner.invoke(main, ["diff", "--source", "nonexistent_src.json", "--target", "pg://tgt"])
        assert res.exit_code == 1
        assert "Error reading source snapshot file" in res.output


class TestMarkdownFormatter:
    def test_markdown_no_drift(self) -> None:
        dr = DiffResult()
        out = _diff_to_markdown(dr)
        assert "No Changes Detected" in out

    def test_markdown_all_components(self) -> None:
        col_old = ColumnDef(name="age", data_type="integer")
        col_new = ColumnDef(name="age", data_type="bigint")
        dr = DiffResult(
            tables_added=[TableDef(name="orders")],
            tables_dropped=["old_table"],
            columns_added=[("users", ColumnDef(name="bio", data_type="text"))],
            columns_dropped=[("users", "deprecated_field")],
            columns_altered=[("users", col_old, col_new)],
            indexes_added=[IndexDef(name="idx_a", table="orders", columns=["id"])],
            indexes_dropped=[IndexDef(name="idx_b", table="users", columns=["id"])],
            fks_added=[
                ForeignKeyDef(
                    name="fk1",
                    table="t1",
                    columns=["a"],
                    ref_table="t2",
                    ref_columns=["b"],
                )
            ],
            fks_dropped=[
                ForeignKeyDef(
                    name="fk2",
                    table="t1",
                    columns=["a"],
                    ref_table="t2",
                    ref_columns=["b"],
                )
            ],
        )
        md = _diff_to_markdown(dr)
        assert "| **Tables Added** |" in md
        assert "| **Tables Dropped** |" in md
        assert "| **Columns Added** |" in md
        assert "| **Columns Dropped** |" in md
        assert "| **Columns Altered** |" in md
        assert "| **Indexes Added** |" in md
        assert "| **Indexes Dropped** |" in md
        assert "| **Foreign Keys Added** |" in md
        assert "| **Foreign Keys Dropped** |" in md
