"""Unit tests for schemadrift.safety (Migration Lock-Hazard Analyzer)."""

from __future__ import annotations

from schemadrift.models import ColumnDef, DiffResult, ForeignKeyDef, IndexDef, TableDef
from schemadrift.safety import MigrationSafetyAnalyzer


class TestMigrationSafetyAnalyzer:
    def test_empty_diff_is_safe(self) -> None:
        report = MigrationSafetyAnalyzer(DiffResult()).analyze()
        assert report.is_safe is True
        assert report.risk_level == "SAFE"
        assert report.critical_count == 0
        assert report.high_count == 0
        assert report.medium_count == 0
        assert report.meets_threshold("medium") is False
        assert report.meets_threshold("none") is False

    def test_haz001_table_drop_is_critical(self) -> None:
        diff = DiffResult(tables_dropped=["audit_logs"])
        report = MigrationSafetyAnalyzer(diff, lock_timeout="2s").analyze()
        assert report.risk_level == "CRITICAL"
        assert report.critical_count == 1
        assert report.hazards[0].code == "HAZ001"
        assert report.hazards[0].lock_mode == "ACCESS EXCLUSIVE"
        assert report.meets_threshold("critical") is True

    def test_haz002_column_drop_is_critical(self) -> None:
        diff = DiffResult(columns_dropped=[("users", "legacy_token")])
        report = MigrationSafetyAnalyzer(diff, lock_timeout="2s").analyze()
        assert report.risk_level == "CRITICAL"
        assert report.hazards[0].code == "HAZ002"
        assert report.hazards[0].target_object == "users.legacy_token"

    def test_haz003_blocking_index_without_and_with_concurrently(self) -> None:
        idx_add = IndexDef(name="idx_orders_email", table="orders", columns=["email"])
        idx_drop = IndexDef(name="idx_orders_old", table="orders", columns=["old"])
        diff = DiffResult(indexes_added=[idx_add], indexes_dropped=[idx_drop])

        unsafe = MigrationSafetyAnalyzer(diff, lock_timeout="2s").analyze()
        assert [h.code for h in unsafe.hazards] == ["HAZ003", "HAZ003"]
        assert unsafe.hazards[0].lock_mode == "SHARE"
        assert unsafe.hazards[1].lock_mode == "ACCESS EXCLUSIVE"

        safe = MigrationSafetyAnalyzer(diff, concurrent_indexes=True, lock_timeout="2s").analyze()
        assert safe.is_safe is True

    def test_haz004_fk_validation_with_and_without_safe_mode(self) -> None:
        fk = ForeignKeyDef(
            name="fk_orders_user",
            table="orders",
            columns=["user_id"],
            ref_table="users",
            ref_columns=["id"],
        )
        diff = DiffResult(fks_added=[fk])

        unsafe = MigrationSafetyAnalyzer(diff, lock_timeout="2s").analyze()
        assert len(unsafe.hazards) == 1
        assert unsafe.hazards[0].code == "HAZ004"
        assert unsafe.hazards[0].lock_mode == "SHARE ROW EXCLUSIVE"

        two_phase = MigrationSafetyAnalyzer(diff, two_phase_fk=True, lock_timeout="2s").analyze()
        assert two_phase.is_safe is True

        safe_mode = MigrationSafetyAnalyzer(diff, safe_mode=True).analyze()
        assert safe_mode.is_safe is True

    def test_haz005_varchar_widening_vs_table_rewrite(self) -> None:
        widen_diff = DiffResult(
            columns_altered=[
                (
                    "users",
                    ColumnDef(name="bio", data_type="varchar(100)"),
                    ColumnDef(name="bio", data_type="varchar(255)"),
                ),
                (
                    "users",
                    ColumnDef(name="notes", data_type="varchar(50)"),
                    ColumnDef(name="notes", data_type="text"),
                ),
            ]
        )
        widen_report = MigrationSafetyAnalyzer(widen_diff, lock_timeout="2s").analyze()
        assert widen_report.risk_level == "MEDIUM"
        assert all(h.code == "HAZ005" and h.severity == "MEDIUM" for h in widen_report.hazards)

        rewrite_diff = DiffResult(
            columns_altered=[
                (
                    "orders",
                    ColumnDef(name="amount", data_type="integer"),
                    ColumnDef(name="amount", data_type="bigint"),
                ),
                (
                    "orders",
                    ColumnDef(name="code", data_type="varchar(50)"),
                    ColumnDef(name="code", data_type="varchar(20)"),
                ),
            ]
        )
        rewrite_report = MigrationSafetyAnalyzer(rewrite_diff, lock_timeout="2s").analyze()
        assert rewrite_report.risk_level == "HIGH"
        assert rewrite_report.high_count == 2
        assert "heap rewrite" in rewrite_report.hazards[0].message

    def test_haz006_not_null_column_without_default(self) -> None:
        diff = DiffResult(
            columns_added=[
                ("users", ColumnDef(name="org_id", data_type="bigint", nullable=False)),
                (
                    "users",
                    ColumnDef(name="status", data_type="text", nullable=False, default="'active'"),
                ),
            ]
        )
        report = MigrationSafetyAnalyzer(diff, lock_timeout="2s").analyze()
        assert len(report.hazards) == 1
        assert report.hazards[0].code == "HAZ006"
        assert report.hazards[0].target_object == "users.org_id"

    def test_haz007_missing_lock_timeout_guard(self) -> None:
        diff = DiffResult(columns_added=[("users", ColumnDef(name="nick", data_type="text"))])
        no_guard = MigrationSafetyAnalyzer(diff).analyze()
        assert no_guard.risk_level == "MEDIUM"
        assert [h.code for h in no_guard.hazards] == ["HAZ007"]

        guarded = MigrationSafetyAnalyzer(diff, lock_timeout="2s").analyze()
        assert guarded.is_safe is True

        # New table creation alone only creates a new object, no existing table lock hazard
        create_only = DiffResult(tables_added=[TableDef(name="brand_new")])
        assert MigrationSafetyAnalyzer(create_only).analyze().is_safe is True

    def test_haz008_set_not_null_scan(self) -> None:
        diff = DiffResult(
            columns_altered=[
                (
                    "users",
                    ColumnDef(name="email", data_type="text", nullable=True),
                    ColumnDef(name="email", data_type="text", nullable=False),
                )
            ]
        )
        report = MigrationSafetyAnalyzer(diff, lock_timeout="2s").analyze()
        assert len(report.hazards) == 1
        assert report.hazards[0].code == "HAZ008"
        assert report.hazards[0].severity == "HIGH"
        payload = report.to_dict()
        assert payload["risk_level"] == "HIGH"
        assert payload["total_hazards"] == 1
        assert payload["hazards"][0]["code"] == "HAZ008"
