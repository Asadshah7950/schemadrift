"""Unit tests for schemadrift.linter and the CLI lint command."""

from __future__ import annotations

import json

from click.testing import CliRunner

from schemadrift.cli import main
from schemadrift.linter import LintIssue, LintResult, SchemaLinter
from schemadrift.models import ColumnDef, ForeignKeyDef, IndexDef, SchemaSnapshot, TableDef


class TestSchemaLinter:
    def test_healthy_schema_has_zero_issues(self) -> None:
        users = TableDef(
            name="users",
            columns=[
                ColumnDef("id", "bigint", is_primary_key=True),
                ColumnDef("email", "varchar(255)"),
            ],
            indexes=[IndexDef("idx_users_email", "users", ["email"], unique=True)],
        )
        orders = TableDef(
            name="orders",
            columns=[
                ColumnDef("id", "bigint", is_primary_key=True),
                ColumnDef("user_id", "bigint"),
            ],
            indexes=[IndexDef("idx_orders_user_id", "orders", ["user_id"])],
        )
        fk = ForeignKeyDef("fk_orders_user", "orders", ["user_id"], "users", ["id"])

        snap = SchemaSnapshot(tables={"users": users, "orders": orders}, foreign_keys=[fk])
        linter = SchemaLinter(snap)
        res = linter.lint()

        assert len(res.issues) == 0
        assert res.has_errors is False
        assert res.has_warnings is False
        assert res.error_count == 0
        assert res.warning_count == 0

    def test_detects_missing_primary_key(self) -> None:
        logs = TableDef(
            name="audit_logs",
            columns=[
                ColumnDef("action", "text"),
                ColumnDef("created_at", "timestamptz"),
            ],
        )
        snap = SchemaSnapshot(tables={"audit_logs": logs})
        linter = SchemaLinter(snap)
        res = linter.lint()

        assert res.has_errors is True
        assert res.error_count == 1
        issue = res.issues[0]
        assert issue.code == "E001"
        assert issue.rule == "missing-primary-key"
        assert issue.severity == "ERROR"
        assert issue.table == "audit_logs"
        assert "does not have a primary key" in issue.message

    def test_detects_unindexed_foreign_key(self) -> None:
        users = TableDef(
            name="users",
            columns=[ColumnDef("id", "int", is_primary_key=True)],
        )
        orders = TableDef(
            name="orders",
            columns=[
                ColumnDef("id", "int", is_primary_key=True),
                ColumnDef("customer_id", "int"),
            ],
            indexes=[],  # No index on customer_id!
        )
        fk = ForeignKeyDef("fk_orders_customer", "orders", ["customer_id"], "users", ["id"])

        snap = SchemaSnapshot(tables={"users": users, "orders": orders}, foreign_keys=[fk])
        linter = SchemaLinter(snap)
        res = linter.lint()

        assert res.has_warnings is True
        assert res.warning_count == 1
        issue = res.issues[0]
        assert issue.code == "W001"
        assert issue.rule == "unindexed-foreign-key"
        assert issue.table == "orders"
        assert "customer_id" in issue.columns
        assert "CREATE INDEX CONCURRENTLY" in issue.suggestion

    def test_covering_index_satisfies_composite_foreign_key(self) -> None:
        parent = TableDef(
            name="tenants",
            columns=[
                ColumnDef("org_id", "int", is_primary_key=True),
                ColumnDef("tenant_id", "int", is_primary_key=True),
            ],
        )
        child = TableDef(
            name="members",
            columns=[
                ColumnDef("id", "int", is_primary_key=True),
                ColumnDef("org_id", "int"),
                ColumnDef("tenant_id", "int"),
            ],
            # Left prefix covers the composite FK!
            indexes=[
                IndexDef("idx_members_tenant_composite", "members", ["org_id", "tenant_id", "id"])
            ],
        )
        fk = ForeignKeyDef(
            "fk_tenant_member",
            "members",
            ["org_id", "tenant_id"],
            "tenants",
            ["org_id", "tenant_id"],
        )

        snap = SchemaSnapshot(tables={"tenants": parent, "members": child}, foreign_keys=[fk])
        linter = SchemaLinter(snap)
        res = linter.lint()
        assert len(res.issues) == 0

    def test_detects_redundant_index(self) -> None:
        tbl = TableDef(
            name="accounts",
            columns=[
                ColumnDef("id", "int", is_primary_key=True),
                ColumnDef("email", "varchar(255)"),
                ColumnDef("created_at", "timestamptz"),
            ],
            indexes=[
                IndexDef("idx_acc_email", "accounts", ["email"]),
                IndexDef("idx_acc_email_created", "accounts", ["email", "created_at"]),
            ],
        )
        snap = SchemaSnapshot(tables={"accounts": tbl})
        linter = SchemaLinter(snap)
        res = linter.lint()

        assert res.has_warnings is True
        issue = [i for i in res.issues if i.code == "W002"][0]
        assert issue.rule == "redundant-index"
        assert "idx_acc_email" in issue.message
        assert "idx_acc_email_created" in issue.message

    def test_unique_index_not_flagged_redundant(self) -> None:
        tbl = TableDef(
            name="accounts",
            columns=[
                ColumnDef("id", "int", is_primary_key=True),
                ColumnDef("email", "varchar(255)"),
                ColumnDef("created_at", "timestamptz"),
            ],
            indexes=[
                # unique index enforces uniqueness, not redundant even if prefix of composite
                IndexDef("uniq_acc_email", "accounts", ["email"], unique=True),
                IndexDef("idx_acc_email_created", "accounts", ["email", "created_at"]),
            ],
        )
        snap = SchemaSnapshot(tables={"accounts": tbl})
        linter = SchemaLinter(snap)
        res = linter.lint()
        redundant = [i for i in res.issues if i.code == "W002"]
        assert len(redundant) == 0

    def test_exclude_tables(self) -> None:
        raw_logs = TableDef(
            name="raw_logs",
            columns=[ColumnDef("payload", "text")],  # No PK
        )
        snap = SchemaSnapshot(tables={"raw_logs": raw_logs})
        linter = SchemaLinter(snap, exclude_tables={"raw_logs"})
        res = linter.lint()
        assert len(res.issues) == 0

    def test_exclude_tables_with_foreign_key(self) -> None:
        fk = ForeignKeyDef("fk_ex", "excluded_child", ["p_id"], "parents", ["id"])
        snap = SchemaSnapshot(foreign_keys=[fk])
        linter = SchemaLinter(snap, exclude_tables={"excluded_child"})
        res = linter.lint()
        assert len(res.issues) == 0

    def test_foreign_key_missing_child_table(self) -> None:
        fk = ForeignKeyDef("fk_orphan", "nonexistent_table", ["p_id"], "parents", ["id"])
        snap = SchemaSnapshot(foreign_keys=[fk])
        linter = SchemaLinter(snap)
        res = linter.lint()
        assert len(res.issues) == 0

    def test_lint_result_to_dict(self) -> None:
        issue = LintIssue(
            code="E001",
            rule="missing-primary-key",
            severity="ERROR",
            table="logs",
            message="No PK",
            columns=[],
            suggestion="Add PK",
        )
        result = LintResult(issues=[issue])
        data = result.to_dict()

        assert data["total_issues"] == 1
        assert data["error_count"] == 1
        assert data["warning_count"] == 0
        assert data["issues"][0]["code"] == "E001"

    def test_filter_by_severity(self) -> None:
        e_issue = LintIssue("E001", "missing-primary-key", "ERROR", "t", "msg")
        w_issue = LintIssue("W001", "unindexed-foreign-key", "WARNING", "t", "msg")
        result = LintResult(issues=[e_issue, w_issue])
        assert result.filter_by_severity("ERROR") == [e_issue]
        assert result.filter_by_severity("WARNING") == [w_issue]

    def test_detects_varchar_without_length(self) -> None:
        tbl = TableDef(
            name="products",
            columns=[
                ColumnDef("id", "bigint", is_primary_key=True),
                # bare VARCHAR with no length → should trigger W003
                ColumnDef("name", "varchar"),
                ColumnDef("description", "character varying"),
                # VARCHAR(255) is fine — has explicit length, data_type includes length in name
                ColumnDef("sku", "varchar(255)"),
                ColumnDef("notes", "text"),  # TEXT is unbounded by design, not flagged
            ],
        )
        snap = SchemaSnapshot(tables={"products": tbl})
        linter = SchemaLinter(snap)
        res = linter.lint()

        w003_issues = [i for i in res.issues if i.code == "W003"]
        assert len(w003_issues) == 2, f"Expected 2 W003 issues, got {len(w003_issues)}"
        flagged_cols = {i.columns[0] for i in w003_issues}
        assert flagged_cols == {"name", "description"}
        assert all(i.rule == "varchar-without-length" for i in w003_issues)
        assert all(i.severity == "WARNING" for i in w003_issues)
        assert all("VARCHAR(n)" in i.suggestion for i in w003_issues)

    def test_varchar_with_length_not_flagged(self) -> None:
        tbl = TableDef(
            name="clean_table",
            columns=[
                ColumnDef("id", "bigint", is_primary_key=True),
                ColumnDef("label", "varchar(100)"),
                ColumnDef("code", "character varying(50)"),
                ColumnDef("body", "text"),
            ],
        )
        snap = SchemaSnapshot(tables={"clean_table": tbl})
        linter = SchemaLinter(snap)
        res = linter.lint()
        assert all(i.code != "W003" for i in res.issues)

    def test_varchar_excluded_table_not_flagged(self) -> None:
        tbl = TableDef(
            name="legacy",
            columns=[
                ColumnDef("id", "int", is_primary_key=True),
                ColumnDef("raw", "varchar"),
            ],
        )
        snap = SchemaSnapshot(tables={"legacy": tbl})
        linter = SchemaLinter(snap, exclude_tables={"legacy"})
        res = linter.lint()
        assert len(res.issues) == 0


class TestLintCLICommand:
    def test_lint_missing_arguments(self) -> None:
        runner = CliRunner()
        res = runner.invoke(main, ["lint"])
        assert res.exit_code == 1
        assert "Error: Must provide a schema source" in res.output

    def test_lint_healthy_snapshot(self, tmp_path) -> None:
        snap = SchemaSnapshot(
            tables={
                "users": TableDef(
                    name="users",
                    columns=[ColumnDef("id", "bigint", is_primary_key=True)],
                )
            }
        )
        file_path = tmp_path / "healthy.json"
        snap.to_file(str(file_path))

        runner = CliRunner()
        res = runner.invoke(main, ["lint", "--file", str(file_path)])
        assert res.exit_code == 0
        assert "Schema is healthy!" in res.output

    def test_lint_unhealthy_fails_on_error_by_default(self, tmp_path) -> None:
        snap = SchemaSnapshot(
            tables={
                "broken": TableDef(
                    name="broken",
                    columns=[ColumnDef("info", "text")],  # No PK!
                )
            }
        )
        file_path = tmp_path / "unhealthy.json"
        snap.to_file(str(file_path))

        runner = CliRunner()
        res = runner.invoke(main, ["lint", "--source", str(file_path)])
        assert res.exit_code == 1
        assert "E001" in res.output
        assert "missing-primary-key" in res.output
        assert "1 error(s)" in res.output

    def test_lint_no_fail_on_error(self, tmp_path) -> None:
        snap = SchemaSnapshot(
            tables={"broken": TableDef(name="broken", columns=[ColumnDef("info", "text")])}
        )
        file_path = tmp_path / "unhealthy.json"
        snap.to_file(str(file_path))

        runner = CliRunner()
        res = runner.invoke(main, ["lint", "-f", str(file_path), "--no-fail-on-error"])
        assert res.exit_code == 0
        assert "E001" in res.output

    def test_lint_fails_on_warning_flag(self, tmp_path) -> None:
        # Schema with PK (no error), but unindexed FK (warning)
        users = TableDef("users", [ColumnDef("id", "int", is_primary_key=True)])
        orders = TableDef(
            "orders",
            [ColumnDef("id", "int", is_primary_key=True), ColumnDef("user_id", "int")],
        )
        fk = ForeignKeyDef("fk_o_u", "orders", ["user_id"], "users", ["id"])
        snap = SchemaSnapshot(tables={"users": users, "orders": orders}, foreign_keys=[fk])
        file_path = tmp_path / "warn.json"
        snap.to_file(str(file_path))

        runner = CliRunner()
        # Default behavior: warnings do not fail build
        res_default = runner.invoke(main, ["lint", "-s", str(file_path)])
        assert res_default.exit_code == 0
        assert "W001" in res_default.output

        # With -W / --fail-on-warning: fails build with exit code 1
        res_warn = runner.invoke(main, ["lint", "-s", str(file_path), "-W"])
        assert res_warn.exit_code == 1

    def test_lint_json_output(self, tmp_path) -> None:
        snap = SchemaSnapshot(
            tables={"broken": TableDef(name="broken", columns=[ColumnDef("val", "text")])}
        )
        file_path = tmp_path / "broken.json"
        snap.to_file(str(file_path))

        runner = CliRunner()
        res = runner.invoke(
            main, ["lint", "-s", str(file_path), "--format", "json", "--no-fail-on-error"]
        )
        assert res.exit_code == 0
        data = json.loads(res.output)
        assert data["error_count"] == 1
        assert data["issues"][0]["code"] == "E001"

    def test_lint_exclude_tables(self, tmp_path) -> None:
        snap = SchemaSnapshot(
            tables={
                "ignored_table": TableDef(
                    name="ignored_table", columns=[ColumnDef("val", "text")]
                )
            }
        )
        file_path = tmp_path / "test.json"
        snap.to_file(str(file_path))

        runner = CliRunner()
        res = runner.invoke(main, ["lint", "-s", str(file_path), "-e", "ignored_table"])
        assert res.exit_code == 0
        assert "Schema is healthy!" in res.output
