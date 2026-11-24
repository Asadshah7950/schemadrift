"""Unit tests for schemadrift.reporter."""

from __future__ import annotations

import json
from unittest.mock import patch

from click.testing import CliRunner

from schemadrift.cli import main
from schemadrift.linter import LintIssue, LintResult
from schemadrift.models import (
    ColumnDef,
    DiffResult,
    ForeignKeyDef,
    IndexDef,
    SchemaSnapshot,
    TableDef,
)
from schemadrift.reporter import (
    render_html_report,
    render_json_report,
    render_lint_sarif,
    render_markdown_report,
    render_safety_markdown,
    render_safety_sarif,
    render_summary_report,
    write_github_step_summary,
)
from schemadrift.safety import MigrationHazard, SafetyReport


def _make_diff_result() -> DiffResult:
    col = ColumnDef(name="email", data_type="varchar(255)")
    col_old = ColumnDef(name="count", data_type="integer")
    col_new = ColumnDef(name="count", data_type="bigint")
    idx = IndexDef(name="idx_users_email", table="users", columns=["email"])
    fk = ForeignKeyDef(
        name="fk_posts_user",
        table="posts",
        columns=["user_id"],
        ref_table="users",
        ref_columns=["id"],
    )
    return DiffResult(
        tables_added=[TableDef(name="users", columns=[col])],
        tables_dropped=["legacy_logs"],
        columns_added=[("users", col)],
        columns_dropped=[("users", "deprecated_field")],
        columns_altered=[("users", col_old, col_new)],
        indexes_added=[idx],
        indexes_dropped=[IndexDef(name="idx_old", table="users", columns=["old_col"])],
        fks_added=[fk],
        fks_dropped=[
            ForeignKeyDef(
                name="fk_old",
                table="posts",
                columns=["old_id"],
                ref_table="users",
                ref_columns=["id"],
            )
        ],
        enums_added=[("user_role", ["admin", "user"])],
        enums_altered=[("order_status", ["pending"], ["delivered"])],
    )


def test_render_json_report_empty() -> None:
    res = DiffResult()
    out = render_json_report(res)
    data = json.loads(out)
    assert data["has_drift"] is False
    assert data["has_destructive_changes"] is False
    assert data["destructive_changes_count"] == 0
    assert data["tables_added"] == []


def test_render_json_report_with_drift() -> None:
    res = _make_diff_result()
    out = render_json_report(res)
    data = json.loads(out)
    assert data["has_drift"] is True
    assert data["has_destructive_changes"] is True
    assert data["destructive_changes_count"] == 2
    assert "users" in data["tables_added"]
    assert "legacy_logs" in data["tables_dropped"]
    assert data["enums_added"][0]["name"] == "user_role"


def test_render_summary_report_with_enums() -> None:
    res = _make_diff_result()
    summary = render_summary_report(res)
    assert "Tables added:    1" in summary
    assert "Tables dropped:  1" in summary
    assert "Enums added:     1" in summary
    assert "Enums altered:   1" in summary
    assert "Destructive:     2 drops" in summary


def test_render_markdown_report_empty() -> None:
    res = DiffResult()
    md = render_markdown_report(res)
    assert "No Changes Detected" in md


def test_render_markdown_report_with_drift() -> None:
    res = _make_diff_result()
    md = render_markdown_report(res)
    assert "### 🔍 PostgreSQL Schema Drift Report" in md
    assert "Tables Added" in md
    assert "`users`" in md
    assert "Enums Added" in md


def test_render_html_report_in_sync() -> None:
    res = DiffResult()
    html_out = render_html_report(res)
    assert "IN SYNC" in html_out
    assert "Schemas are in parity" in html_out
    assert "<!DOCTYPE html>" in html_out


def test_render_html_report_drift_with_sql() -> None:
    res = _make_diff_result()
    test_sql = "BEGIN;\nCREATE TABLE users (email varchar(255));\nCOMMIT;"
    html_out = render_html_report(res, sql=test_sql, title="Custom Test Title")
    assert "Custom Test Title" in html_out
    assert "DRIFT DETECTED" in html_out
    assert "Generated Migration SQL" in html_out
    assert "CREATE TABLE users" in html_out
    assert "copySql()" in html_out


def test_write_github_step_summary_no_env(monkeypatch: object) -> None:
    with patch.dict("os.environ", {}, clear=True):
        assert write_github_step_summary("test content") is False


def test_write_github_step_summary_success(tmp_path: object) -> None:
    summary_file = tmp_path / "step_summary.md"  # type: ignore[operator]
    with patch.dict("os.environ", {"GITHUB_STEP_SUMMARY": str(summary_file)}):
        result = write_github_step_summary("### Test Summary")
        assert result is True
        assert "### Test Summary" in summary_file.read_text(encoding="utf-8")


def test_cli_diff_html_format(tmp_path: object) -> None:
    runner = CliRunner()
    src = SchemaSnapshot()
    tgt = SchemaSnapshot(tables={"users": TableDef(name="users")})
    out_file = tmp_path / "audit.html"  # type: ignore[operator]

    with patch("schemadrift.cli.SchemaInspector") as mock_insp:
        mock_insp.return_value.snapshot.side_effect = [src, tgt]
        res = runner.invoke(
            main,
            [
                "diff",
                "--source",
                "pg://src",
                "--target",
                "pg://tgt",
                "--format",
                "html",
                "--output",
                str(out_file),
            ],
        )

        assert res.exit_code == 0
        assert "Audit report written to" in res.output
        assert out_file.exists()
        assert "<!DOCTYPE html>" in out_file.read_text(encoding="utf-8")


def test_render_lint_sarif() -> None:
    lint_result = LintResult(
        issues=[
            LintIssue(
                code="E001",
                rule="missing-primary-key",
                severity="ERROR",
                table="events",
                message="Table lacks a PK.",
                suggestion="Add id PRIMARY KEY.",
            ),
            LintIssue(
                code="W001",
                rule="unindexed-foreign-key",
                severity="WARNING",
                table="orders",
                columns=["user_id"],
                message="FK column is unindexed.",
                suggestion="Create index.",
            ),
        ]
    )
    sarif = json.loads(render_lint_sarif(lint_result, schema_uri="prod.json", tool_version="0.3.0"))
    assert sarif["version"] == "2.1.0"
    run = sarif["runs"][0]
    assert run["tool"]["driver"]["name"] == "schemadrift-lint"
    assert run["tool"]["driver"]["version"] == "0.3.0"
    assert len(run["tool"]["driver"]["rules"]) == 2
    assert run["results"][0]["level"] == "error"
    assert run["results"][1]["level"] == "warning"
    assert (
        run["results"][1]["locations"][0]["logicalLocations"][0]["fullyQualifiedName"]
        == "orders.user_id"
    )


def test_render_safety_sarif_and_markdown() -> None:
    safe = SafetyReport()
    assert "Safety Check: Passed" in render_safety_markdown(safe)

    risky = SafetyReport(
        hazards=[
            MigrationHazard(
                code="HAZ001",
                rule="destructive-table-drop",
                severity="CRITICAL",
                lock_mode="ACCESS EXCLUSIVE",
                table="temp_users",
                target_object="temp_users",
                message="Dropping table drops data.",
                remediation="Drop in next release.",
            ),
            MigrationHazard(
                code="HAZ007",
                rule="missing-lock-timeout-guard",
                severity="MEDIUM",
                lock_mode="ACCESS EXCLUSIVE",
                table="*",
                target_object="session.lock_timeout",
                message="Missing lock_timeout.",
                remediation="Pass --lock-timeout 2s.",
            ),
        ]
    )
    sarif = json.loads(render_safety_sarif(risky))
    assert sarif["version"] == "2.1.0"
    assert sarif["runs"][0]["results"][0]["level"] == "error"
    assert sarif["runs"][0]["results"][1]["level"] == "warning"
    md = render_safety_markdown(risky)
    assert "Risk: **CRITICAL**" in md
    assert "`HAZ001`" in md
