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
