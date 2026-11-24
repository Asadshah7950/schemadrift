"""Migration lock-hazard and zero-downtime deployment safety analyzer."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from schemadrift.models import ColumnDef, DiffResult

_SEVERITY_RANK: dict[str, int] = {
    "SAFE": 0,
    "LOW": 1,
    "MEDIUM": 2,
    "HIGH": 3,
    "CRITICAL": 4,
}

_VARCHAR_LEN_RE = re.compile(r"^(?:character varying|varchar)\s*\(\s*(\d+)\s*\)$", re.IGNORECASE)


@dataclass
class MigrationHazard:
    """Represents a PostgreSQL deployment lock hazard or zero-downtime risk."""

    code: str
    rule: str
    severity: str  # "CRITICAL", "HIGH", "MEDIUM", or "LOW"
    lock_mode: str
    table: str
    message: str
    remediation: str
    target_object: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize hazard to a JSON-compatible dictionary."""
        return {
            "code": self.code,
            "rule": self.rule,
            "severity": self.severity,
            "lock_mode": self.lock_mode,
            "table": self.table,
            "target_object": self.target_object,
            "message": self.message,
            "remediation": self.remediation,
        }


@dataclass
class SafetyReport:
    """Aggregated lock-hazard and safety audit report for a schema migration."""

    hazards: list[MigrationHazard] = field(default_factory=list)

    @property
    def is_safe(self) -> bool:
        """Return True if no deployment hazards were detected."""
        return not self.hazards

    @property
    def risk_level(self) -> str:
        """Return the highest hazard severity present ('SAFE' when empty)."""
        if not self.hazards:
            return "SAFE"
        return max(self.hazards, key=lambda h: _SEVERITY_RANK.get(h.severity, 0)).severity

    @property
    def critical_count(self) -> int:
        """Total count of CRITICAL hazards."""
        return sum(1 for h in self.hazards if h.severity == "CRITICAL")

    @property
    def high_count(self) -> int:
        """Total count of HIGH hazards."""
        return sum(1 for h in self.hazards if h.severity == "HIGH")

    @property
    def medium_count(self) -> int:
        """Total count of MEDIUM hazards."""
        return sum(1 for h in self.hazards if h.severity == "MEDIUM")

    def meets_threshold(self, threshold: str) -> bool:
        """Return True if any hazard meets or exceeds the given severity threshold."""
        target_rank = _SEVERITY_RANK.get(threshold.upper(), 0)
        if target_rank == 0:
            return False
        return any(_SEVERITY_RANK.get(h.severity, 0) >= target_rank for h in self.hazards)

    def to_dict(self) -> dict[str, Any]:
        """Serialize safety report to a JSON-compatible dictionary."""
        return {
            "risk_level": self.risk_level,
            "is_safe": self.is_safe,
            "total_hazards": len(self.hazards),
            "critical_count": self.critical_count,
            "high_count": self.high_count,
            "medium_count": self.medium_count,
            "hazards": [h.to_dict() for h in self.hazards],
        }


def _is_safe_varchar_widening(src_type: str, tgt_type: str) -> bool:
    """Return True when altering varchar(m) -> varchar(n) with n >= m or -> text.

    PostgreSQL treats unbounded text and widened varchar bounds as binary-coercible
    catalog-only updates that avoid full-table heap rewrites.
    """
    src_norm = src_type.strip().lower()
    tgt_norm = tgt_type.strip().lower()
    src_match = _VARCHAR_LEN_RE.match(src_norm)
    if not src_match:
        return False
    if tgt_norm == "text":
        return True
    tgt_match = _VARCHAR_LEN_RE.match(tgt_norm)
    if tgt_match:
        return int(tgt_match.group(1)) >= int(src_match.group(1))
    return False


class MigrationSafetyAnalyzer:
    """Evaluates a DiffResult and migration flags for PostgreSQL lock hazards."""

    def __init__(
        self,
        diff: DiffResult,
        concurrent_indexes: bool = False,
        two_phase_fk: bool = False,
        lock_timeout: str | None = None,
        safe_mode: bool = False,
    ) -> None:
        self.diff = diff
        self.concurrent_indexes = concurrent_indexes
        self.two_phase_fk = two_phase_fk or safe_mode
        self.lock_timeout = lock_timeout or ("2s" if safe_mode else None)

    def analyze(self) -> SafetyReport:
        """Analyze diff operations and migration execution options for safety hazards."""
        hazards: list[MigrationHazard] = []

        # HAZ001: Destructive table drops
        for table_name in sorted(self.diff.tables_dropped):
            hazards.append(
                MigrationHazard(
                    code="HAZ001",
                    rule="destructive-table-drop",
                    severity="CRITICAL",
                    lock_mode="ACCESS EXCLUSIVE",
                    table=table_name,
                    target_object=table_name,
                    message=(
                        f"Dropping table '{table_name}' permanently deletes data and breaks "
                        "active application queries or replicas during rolling deployments."
                    ),
                    remediation=(
                        "Deploy application code that removes all reads/writes to "
                        f"'{table_name}' first, snapshot backups, then drop in a follow-up release."
                    ),
                )
            )

        # HAZ002: Destructive column drops
        for table_name, col_name in sorted(self.diff.columns_dropped):
            hazards.append(
                MigrationHazard(
                    code="HAZ002",
                    rule="destructive-column-drop",
                    severity="CRITICAL",
                    lock_mode="ACCESS EXCLUSIVE",
                    table=table_name,
                    target_object=f"{table_name}.{col_name}",
                    message=(
                        f"Dropping column '{table_name}.{col_name}' causes runtime SQL failures "
                        "for running application instances still querying the previous schema."
                    ),
                    remediation=(
                        f"Ignore/stop referencing '{col_name}' in application ORM queries first, "
                        "roll out all pods, and drop the column in a separate cleanup migration."
                    ),
                )
            )

        # HAZ003: Blocking CREATE / DROP INDEX without CONCURRENTLY
        if not self.concurrent_indexes:
            for idx in self.diff.indexes_added:
                hazards.append(
                    MigrationHazard(
                        code="HAZ003",
                        rule="blocking-index-operation",
                        severity="HIGH",
                        lock_mode="SHARE",
                        table=idx.table,
                        target_object=idx.name,
                        message=(
                            f"Creating index '{idx.name}' on '{idx.table}' without CONCURRENTLY "
                            "acquires a SHARE lock that blocks concurrent INSERT/UPDATE/DELETE."
                        ),
                        remediation=(
                            "Re-run migration generation with '--concurrently' to emit "
                            "'CREATE INDEX CONCURRENTLY' outside a transaction block."
                        ),
                    )
                )

            for idx in self.diff.indexes_dropped:
                hazards.append(
                    MigrationHazard(
                        code="HAZ003",
                        rule="blocking-index-operation",
                        severity="HIGH",
                        lock_mode="ACCESS EXCLUSIVE",
                        table=idx.table,
                        target_object=idx.name,
                        message=(
                            f"Dropping index '{idx.name}' on '{idx.table}' without CONCURRENTLY "
                            "acquires an ACCESS EXCLUSIVE lock, blocking all reads and writes."
                        ),
                        remediation=(
                            "Re-run migration generation with '--concurrently' to emit "
                            "'DROP INDEX CONCURRENTLY'."
                        ),
                    )
                )

        # HAZ004: Blocking FK constraint creation without NOT VALID + VALIDATE
        if not self.two_phase_fk:
            for fk in self.diff.fks_added:
                hazards.append(
                    MigrationHazard(
                        code="HAZ004",
                        rule="blocking-foreign-key-validation",
                        severity="HIGH",
                        lock_mode="SHARE ROW EXCLUSIVE",
                        table=fk.table,
                        target_object=fk.name,
                        message=(
                            f"Adding foreign key '{fk.name}' ({fk.table} -> {fk.ref_table}) "
                            "validates all rows immediately while holding SHARE ROW EXCLUSIVE "
                            "locks on both tables."
                        ),
                        remediation=(
                            "Use '--two-phase-fk' (or '--safe-mode') to add the constraint "
                            "with NOT VALID first and VALIDATE CONSTRAINT in phase 2."
                        ),
                    )
                )

        # HAZ005 & HAZ008: Column type alterations and SET NOT NULL table scans
        for table_name, src_col, tgt_col in self.diff.columns_altered:
            self._check_altered_column(hazards, table_name, src_col, tgt_col)

        # HAZ006: Adding NOT NULL column without DEFAULT on existing table
        for table_name, col in self.diff.columns_added:
            if not col.nullable and col.default is None:
                hazards.append(
                    MigrationHazard(
                        code="HAZ006",
                        rule="not-null-column-without-default",
                        severity="HIGH",
                        lock_mode="ACCESS EXCLUSIVE",
                        table=table_name,
                        target_object=f"{table_name}.{col.name}",
                        message=(
                            f"Adding non-nullable column '{table_name}.{col.name}' without a "
                            f"DEFAULT fails immediately if '{table_name}' contains existing rows."
                        ),
                        remediation=(
                            "Add the column as nullable first (or supply a constant DEFAULT), "
                            "backfill in batches, and enforce NOT NULL via CHECK ... NOT VALID."
                        ),
                    )
                )

        # HAZ007: Lock-acquiring DDL executed without lock_timeout guard
        if not self.lock_timeout and self._has_table_lock_operations():
            hazards.append(
                MigrationHazard(
                    code="HAZ007",
                    rule="missing-lock-timeout-guard",
                    severity="MEDIUM",
                    lock_mode="ACCESS EXCLUSIVE",
                    table="*",
                    target_object="session.lock_timeout",
                    message=(
                        "Migration acquires restrictive table locks without a 'lock_timeout' "
                        "guard; waiting behind a long-running query stalls all incoming traffic."
                    ),
                    remediation=(
                        "Pass '--lock-timeout 2s' (or '--safe-mode') so blocked lock acquisition "
                        "fails fast and retries safely without starving concurrent queries."
                    ),
                )
            )

        return SafetyReport(hazards=hazards)

    def _check_altered_column(
        self,
        hazards: list[MigrationHazard],
        table_name: str,
        src_col: ColumnDef,
        tgt_col: ColumnDef,
    ) -> None:
        if src_col.data_type != tgt_col.data_type:
            is_catalog_only = _is_safe_varchar_widening(src_col.data_type, tgt_col.data_type)
            hazards.append(
                MigrationHazard(
                    code="HAZ005",
                    rule="column-type-rewrite",
                    severity="MEDIUM" if is_catalog_only else "HIGH",
                    lock_mode="ACCESS EXCLUSIVE",
                    table=table_name,
                    target_object=f"{table_name}.{tgt_col.name}",
                    message=(
                        f"Altering '{table_name}.{tgt_col.name}' from '{src_col.data_type}' to "
                        f"'{tgt_col.data_type}' requires an ACCESS EXCLUSIVE lock"
                        + (
                            "."
                            if is_catalog_only
                            else " and triggers a blocking full-table heap rewrite."
                        )
                    ),
                    remediation=(
                        "Ensure short lock_timeout and run off-peak."
                        if is_catalog_only
                        else (
                            f"Use expand-and-contract: add a new '{tgt_col.data_type}' column, "
                            "dual-write, backfill in batches, and swap columns."
                        )
                    ),
                )
            )

        if src_col.nullable and not tgt_col.nullable:
            hazards.append(
                MigrationHazard(
                    code="HAZ008",
                    rule="set-not-null-full-table-scan",
                    severity="HIGH",
                    lock_mode="ACCESS EXCLUSIVE",
                    table=table_name,
                    target_object=f"{table_name}.{tgt_col.name}",
                    message=(
                        f"Setting NOT NULL directly on '{table_name}.{tgt_col.name}' performs a "
                        "full table scan under ACCESS EXCLUSIVE lock to verify no NULLs remain."
                    ),
                    remediation=(
                        f"Add CHECK ({tgt_col.name} IS NOT NULL) NOT VALID, run VALIDATE "
                        "CONSTRAINT concurrently (SHARE UPDATE EXCLUSIVE), then SET NOT NULL."
                    ),
                )
            )

    def _has_table_lock_operations(self) -> bool:
        return bool(
            self.diff.tables_dropped
            or self.diff.columns_dropped
            or self.diff.columns_added
            or self.diff.columns_altered
            or self.diff.fks_added
            or (
                not self.concurrent_indexes
                and (self.diff.indexes_added or self.diff.indexes_dropped)
            )
        )
