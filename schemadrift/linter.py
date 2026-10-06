"""Schema linter and static analyzer for PostgreSQL databases and snapshots."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from schemadrift.models import SchemaSnapshot


@dataclass
class LintIssue:
    """Represents a detected schema health violation or anti-pattern."""

    code: str
    rule: str
    severity: str  # "ERROR" or "WARNING"
    table: str
    message: str
    columns: list[str] = field(default_factory=list)
    suggestion: str = ""


@dataclass
class LintResult:
    """The result of linting a PostgreSQL schema."""

    issues: list[LintIssue] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        """Return True if any ERROR-level issues were detected."""
        return any(issue.severity == "ERROR" for issue in self.issues)

    @property
    def has_warnings(self) -> bool:
        """Return True if any WARNING-level issues were detected."""
        return any(issue.severity == "WARNING" for issue in self.issues)

    @property
    def error_count(self) -> int:
        """Total number of errors."""
        return sum(1 for issue in self.issues if issue.severity == "ERROR")

    @property
    def warning_count(self) -> int:
        """Total number of warnings."""
        return sum(1 for issue in self.issues if issue.severity == "WARNING")

    def filter_by_severity(self, severity: str) -> list[LintIssue]:
        """Return issues filtered by severity (e.g. 'ERROR' or 'WARNING')."""
        return [i for i in self.issues if i.severity == severity]

    def to_dict(self) -> dict[str, Any]:
        """Convert lint result to dictionary for JSON output."""
        return {
            "total_issues": len(self.issues),
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "issues": [
                {
                    "code": issue.code,
                    "rule": issue.rule,
                    "severity": issue.severity,
                    "table": issue.table,
                    "message": issue.message,
                    "columns": issue.columns,
                    "suggestion": issue.suggestion,
                }
                for issue in self.issues
            ],
        }


class SchemaLinter:
    """Static analyzer for PostgreSQL schema health, performance, and best practices."""

    def __init__(
        self,
        snapshot: SchemaSnapshot,
        exclude_tables: set[str] | None = None,
    ) -> None:
        self.snapshot = snapshot
        self.exclude_tables = exclude_tables or set()

    def lint(self) -> LintResult:
        """Analyze schema snapshot and return all detected issues."""
        issues: list[LintIssue] = []

        # 1. Table-level checks (missing primary keys, redundant indexes)
        for tbl_name, tbl in sorted(self.snapshot.tables.items()):
            if tbl_name in self.exclude_tables:
                continue

            # Rule E001: Missing primary key
            # Tables without primary keys break logical replication (e.g. Debezium, pglogical)
            # and complicate concurrent ORM lookups and identity mapping.
            has_pk = any(col.is_primary_key for col in tbl.columns)
            if not has_pk:
                issues.append(
                    LintIssue(
                        code="E001",
                        rule="missing-primary-key",
                        severity="ERROR",
                        table=tbl_name,
                        message=f"Table '{tbl_name}' does not have a primary key.",
                        suggestion=(
                            f"Add a primary key constraint to '{tbl_name}' "
                            f"(e.g. id BIGSERIAL PRIMARY KEY or UUID PRIMARY KEY)."
                        ),
                    )
                )

            # Rule W002: Redundant / Left-prefix duplicate indexes
            # In PostgreSQL B-tree indexes, index (A) is redundant if index (A, B) exists,
            # unless the index is unique or uses a specialized access method/partial predicate.
            btree_indexes = [idx for idx in tbl.indexes if idx.method == "btree"]
            for i, idx1 in enumerate(btree_indexes):
                for j, idx2 in enumerate(btree_indexes):
                    if i == j:
                        continue
                    # Unique indexes enforce unique business constraints; don't flag as redundant
                    if idx1.unique or idx2.unique:
                        continue

                    cols1 = idx1.columns
                    cols2 = idx2.columns
                    # If idx1 is a strict left prefix of idx2
                    if len(cols1) < len(cols2) and cols2[: len(cols1)] == cols1:
                        issues.append(
                            LintIssue(
                                code="W002",
                                rule="redundant-index",
                                severity="WARNING",
                                table=tbl_name,
                                message=(
                                    f"Index '{idx1.name}' on {cols1} is a redundant prefix of "
                                    f"composite index '{idx2.name}' on {cols2}."
                                ),
                                columns=cols1,
                                suggestion=(
                                    f"Consider dropping redundant index '{idx1.name}' to save "
                                    f"disk space and write IOPS."
                                ),
                            )
                        )

            # Rule W003: VARCHAR column without explicit length
            # Using VARCHAR (or CHARACTER VARYING) without a length limit is functionally
            # identical to TEXT in PostgreSQL, but omits the intent-clarifying constraint.
            # Unbounded strings bypass application-layer size validation and can surprise
            # engineers porting schemas to databases that enforce VARCHAR length strictly.
            _UNBOUNDED_VARCHAR = {"character varying", "varchar"}
            for col in tbl.columns:
                if col.data_type.lower().strip() in _UNBOUNDED_VARCHAR:
                    issues.append(
                        LintIssue(
                            code="W003",
                            rule="varchar-without-length",
                            severity="WARNING",
                            table=tbl_name,
                            message=(
                                f"Column '{col.name}' on table '{tbl_name}' uses VARCHAR "
                                f"without an explicit length limit."
                            ),
                            columns=[col.name],
                            suggestion=(
                                "Use TEXT if truly unbounded, or VARCHAR(n) with an"
                                " explicit max length (e.g. VARCHAR(255)) to document"
                                " the intended constraint."
                            ),
                        )
                    )

        # 2. Foreign-key checks (unindexed foreign keys)
        # Foreign keys in PostgreSQL do not automatically create indexes on referencing columns.
        # Deletes/updates on parent tables cause full sequential scans on child tables,
        # leading to lock contention and severe latency bottlenecks.
        for fk in self.snapshot.foreign_keys:
            if fk.table in self.exclude_tables:
                continue
            child_tbl = self.snapshot.tables.get(fk.table)
            if not child_tbl:
                continue

            fk_cols = fk.columns
            # An index covers this FK if its columns begin with the FK columns
            has_covering_index = False
            for idx in child_tbl.indexes:
                if len(idx.columns) >= len(fk_cols) and idx.columns[: len(fk_cols)] == fk_cols:
                    has_covering_index = True
                    break

            if not has_covering_index:
                col_names_sql = ", ".join(f'"{col}"' for col in fk_cols)
                idx_name_hint = f"idx_{fk.table}_{'_'.join(fk_cols)}"
                issues.append(
                    LintIssue(
                        code="W001",
                        rule="unindexed-foreign-key",
                        severity="WARNING",
                        table=fk.table,
                        message=(
                            f"Foreign key '{fk.name}' on {fk_cols} referencing "
                            f"'{fk.ref_table}' has no covering index."
                        ),
                        columns=fk_cols,
                        suggestion=(
                            f"CREATE INDEX CONCURRENTLY {idx_name_hint} "
                            f'ON "{fk.table}" ({col_names_sql});'
                        ),
                    )
                )

        return LintResult(issues=issues)
