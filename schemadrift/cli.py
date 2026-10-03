"""CLI entry point for pg-schema-diff / schemadrift."""

from __future__ import annotations

import os
import sys

import click
from rich.console import Console
from rich.table import Table

from schemadrift.differ import SchemaDiffer
from schemadrift.generator import MigrationGenerator
from schemadrift.inspector import SchemaInspector
from schemadrift.linter import SchemaLinter
from schemadrift.models import SchemaSnapshot
from schemadrift.reporter import (
    render_html_report,
    render_json_report,
    render_markdown_report,
    render_summary_report,
    write_github_step_summary,
)

console = Console()

# Backward-compatible exports for existing imports/tests
_diff_to_json = render_json_report
_diff_summary = render_summary_report
_diff_to_markdown = render_markdown_report


def _is_json_file(path_or_dsn: str) -> bool:
    """Return True if the given string represents a local JSON snapshot file."""
    return path_or_dsn.endswith(".json") or os.path.isfile(path_or_dsn)


def _load_snapshot(path_or_dsn: str, label: str = "source") -> SchemaSnapshot:
    """Load a SchemaSnapshot from either a local JSON file or a database connection DSN."""
    if _is_json_file(path_or_dsn):
        try:
            return SchemaSnapshot.from_file(path_or_dsn)
        except Exception as exc:  # noqa: BLE001
            click.echo(f"Error reading {label} snapshot file '{path_or_dsn}': {exc}", err=True)
            sys.exit(1)
    try:
        return SchemaInspector(path_or_dsn).snapshot()
    except Exception as exc:  # noqa: BLE001
        click.echo(f"Error connecting to {label} database: {exc}", err=True)
        sys.exit(1)


@click.group()
@click.version_option()
def main() -> None:
    """pg-schema-diff: Detect schema drift between PostgreSQL databases."""


# ---------------------------------------------------------------------------
# diff command
# ---------------------------------------------------------------------------


@main.command()
@click.option(
    "--source",
    required=True,
    help="Source database DSN (e.g. postgres://...) or path to a JSON schema snapshot.",
)
@click.option(
    "--target",
    required=True,
    help="Target database DSN or path to a JSON schema snapshot.",
)
@click.option(
    "--output", "-o", default=None, help="Write migration SQL or audit report to this file path."
)
@click.option(
    "--format",
    "fmt",
    default="sql",
    type=click.Choice(["sql", "json", "summary", "markdown", "html"]),
    show_default=True,
    help="Output format.",
)
@click.option(
    "--direction",
    "-d",
    type=click.Choice(["up", "down"]),
    default="up",
    show_default=True,
    help="Migration direction (up=forward source->target, down=rollback target->source).",
)
@click.option(
    "--transaction/--no-transaction",
    default=True,
    show_default=True,
    help="Wrap migration SQL in a BEGIN/COMMIT transaction block.",
)
@click.option(
    "--concurrently",
    is_flag=True,
    default=False,
    help="Create/drop indexes concurrently (disables transaction blocks).",
)
@click.option(
    "--fail-on-drift",
    is_flag=True,
    default=False,
    help="Exit with status code 1 if schema drift is detected (useful for CI/CD checks).",
)
@click.option(
    "--fail-on-destructive",
    "-w",
    is_flag=True,
    default=False,
    help="Exit with status code 2 if destructive changes (dropped tables/columns) are detected.",
)
@click.option(
    "--step-summary/--no-step-summary",
    default=True,
    show_default=True,
    help="Write markdown drift summary to $GITHUB_STEP_SUMMARY when running in GitHub Actions.",
)
@click.option(
    "--exclude",
    "-e",
    "exclude_tables",
    multiple=True,
    help="Exclude specific tables from diff (e.g. -e alembic_version -e _prisma_migrations).",
)
def diff(
    source: str,
    target: str,
    output: str | None,
    fmt: str,
    direction: str,
    transaction: bool,
    concurrently: bool,
    fail_on_drift: bool,
    fail_on_destructive: bool,
    step_summary: bool,
    exclude_tables: tuple[str, ...],
) -> None:
    """Compare SOURCE and TARGET schemas and generate a migration script."""
    if output or fmt == "summary":
        src_label = (
            f"Loading source snapshot from '{source}'…"
            if _is_json_file(source)
            else "Inspecting source schema…"
        )
        console.print(f"[bold blue]{src_label}[/bold blue]")
    src_snapshot = _load_snapshot(source, label="source")

    if output or fmt == "summary":
        tgt_label = (
            f"Loading target snapshot from '{target}'…"
            if _is_json_file(target)
            else "Inspecting target schema…"
        )
        console.print(f"[bold blue]{tgt_label}[/bold blue]")
    tgt_snapshot = _load_snapshot(target, label="target")

    excluded_set = set(exclude_tables)
    if direction == "down":
        diff_result = SchemaDiffer(tgt_snapshot, src_snapshot, exclude_tables=excluded_set).diff()
    else:
        diff_result = SchemaDiffer(src_snapshot, tgt_snapshot, exclude_tables=excluded_set).diff()

    if fmt == "sql":
        use_transaction = False if concurrently else transaction
        content = MigrationGenerator(
            diff_result,
            transaction=use_transaction,
            concurrent_indexes=concurrently,
        ).generate()
    elif fmt == "json":
        content = render_json_report(diff_result)
    elif fmt == "markdown":
        content = render_markdown_report(diff_result)
    elif fmt == "html":
        use_transaction = False if concurrently else transaction
        sql_script = MigrationGenerator(
            diff_result,
            transaction=use_transaction,
            concurrent_indexes=concurrently,
        ).generate()
        content = render_html_report(diff_result, sql=sql_script)
    else:  # summary
        content = render_summary_report(diff_result)

    if step_summary:
        write_github_step_summary(render_markdown_report(diff_result))

    if output:
        with open(output, "w", encoding="utf-8") as fh:
            fh.write(content)
        file_desc = "Audit report" if fmt == "html" else "Migration" if fmt == "sql" else "Output"
        console.print(f"[green]{file_desc} written to {output}[/green]")
    else:
        click.echo(content)

    if fail_on_destructive and diff_result.has_destructive_changes:
        click.echo(
            f"Destructive changes detected ({diff_result.destructive_changes_count} drops). "
            f"Failing build as requested by --fail-on-destructive.",
            err=True,
        )
        sys.exit(2)

    if fail_on_drift and diff_result.has_drift:
        sys.exit(1)


# ---------------------------------------------------------------------------
# inspect command
# ---------------------------------------------------------------------------


@main.command()
@click.option("--dsn", default=None, help="Database DSN to inspect.")
@click.option(
    "--file",
    "-f",
    "snapshot_file",
    default=None,
    help="Path to a JSON schema snapshot file to inspect.",
)
def inspect(dsn: str | None, snapshot_file: str | None) -> None:
    """Inspect a PostgreSQL schema or saved JSON snapshot and print a summary table."""
    if not dsn and not snapshot_file:
        click.echo("Error: Must provide either --dsn or --file.", err=True)
        sys.exit(1)

    if snapshot_file:
        try:
            snapshot = SchemaSnapshot.from_file(snapshot_file)
        except Exception as exc:  # noqa: BLE001
            click.echo(f"Error reading snapshot file '{snapshot_file}': {exc}", err=True)
            sys.exit(1)
    else:
        assert dsn is not None
        try:
            snapshot = SchemaInspector(dsn).snapshot()
        except Exception as exc:  # noqa: BLE001
            click.echo(f"Error connecting to database: {exc}", err=True)
            sys.exit(1)

    table = Table(title="Schema Summary", show_header=True, header_style="bold magenta")
    table.add_column("Table", style="cyan", no_wrap=True)
    table.add_column("Columns", justify="right")
    table.add_column("Indexes", justify="right")

    for tbl_name, tbl in sorted(snapshot.tables.items()):
        table.add_row(tbl_name, str(len(tbl.columns)), str(len(tbl.indexes)))

    console.print(table)

    if snapshot.enums:
        console.print(f"\n[bold]Enums ({len(snapshot.enums)}):[/bold] " + ", ".join(snapshot.enums))

    if snapshot.foreign_keys:
        console.print(f"[bold]Foreign keys:[/bold] {len(snapshot.foreign_keys)}")


# ---------------------------------------------------------------------------
# snapshot command
# ---------------------------------------------------------------------------


@main.command()
@click.option("--dsn", required=True, help="Database DSN to snapshot.")
@click.option(
    "--output", "-o", default=None, help="Write JSON snapshot to this file path."
)
@click.option(
    "--compact",
    is_flag=True,
    default=False,
    help="Emit minified JSON without indentation.",
)
def snapshot(dsn: str, output: str | None, compact: bool) -> None:
    """Capture a complete schema snapshot as a portable JSON document."""
    try:
        snap = SchemaInspector(dsn).snapshot()
    except Exception as exc:  # noqa: BLE001
        click.echo(f"Error connecting to database: {exc}", err=True)
        sys.exit(1)

    indent = None if compact else 2
    json_content = snap.to_json(indent=indent)

    if output:
        try:
            with open(output, "w", encoding="utf-8") as fh:
                fh.write(json_content)
            console.print(
                f"[green]Schema snapshot ({len(snap.tables)} tables, {len(snap.enums)} enums, "
                f"{len(snap.foreign_keys)} FKs) written to {output}[/green]"
            )
        except Exception as exc:  # noqa: BLE001
            click.echo(f"Error writing snapshot file '{output}': {exc}", err=True)
            sys.exit(1)
    else:
        click.echo(json_content)


# ---------------------------------------------------------------------------
# lint command
# ---------------------------------------------------------------------------


@main.command()
@click.option(
    "--source",
    "-s",
    "target_source",
    default=None,
    help="Database DSN or path to a JSON schema snapshot to lint.",
)
@click.option(
    "--dsn",
    default=None,
    help="Database DSN to lint (alias for --source).",
)
@click.option(
    "--file",
    "-f",
    "snapshot_file",
    default=None,
    help="Path to a JSON schema snapshot to lint (alias for --source).",
)
@click.option(
    "--format",
    "fmt",
    default="summary",
    type=click.Choice(["summary", "json"]),
    show_default=True,
    help="Output format.",
)
@click.option(
    "--fail-on-warning",
    "-W",
    is_flag=True,
    default=False,
    help="Exit with status code 1 if any warnings are detected.",
)
@click.option(
    "--fail-on-error/--no-fail-on-error",
    default=True,
    show_default=True,
    help="Exit with status code 1 if errors (e.g. missing primary keys) are detected.",
)
@click.option(
    "--exclude",
    "-e",
    "exclude_tables",
    multiple=True,
    help="Exclude specific tables from lint checks.",
)
def lint(
    target_source: str | None,
    dsn: str | None,
    snapshot_file: str | None,
    fmt: str,
    fail_on_warning: bool,
    fail_on_error: bool,
    exclude_tables: tuple[str, ...],
) -> None:
    """Analyze a schema for anti-patterns, unindexed foreign keys, and missing keys."""
    resolved_source = target_source or snapshot_file or dsn
    if not resolved_source:
        click.echo("Error: Must provide a schema source via --source, --dsn, or --file.", err=True)
        sys.exit(1)

    snap = _load_snapshot(resolved_source, label="lint target")
    excluded_set = set(exclude_tables)
    linter = SchemaLinter(snap, exclude_tables=excluded_set)
    result = linter.lint()

    if fmt == "json":
        import json

        click.echo(json.dumps(result.to_dict(), indent=2))
    else:
        if not result.issues:
            console.print(
                "[bold green]✓ Schema is healthy! Zero anti-patterns detected.[/bold green]"
            )
        else:
            table = Table(
                title=f"Schema Lint Report ({len(result.issues)} issues found)",
                show_header=True,
                header_style="bold magenta",
            )
            table.add_column("Severity", justify="center", no_wrap=True)
            table.add_column("Code", style="dim", no_wrap=True)
            table.add_column("Table", style="cyan", no_wrap=True)
            table.add_column("Message")
            table.add_column("Recommendation", style="green")

            for issue in result.issues:
                sev_style = "bold red" if issue.severity == "ERROR" else "bold yellow"
                table.add_row(
                    f"[{sev_style}]{issue.severity}[/{sev_style}]",
                    f"{issue.code} ({issue.rule})",
                    issue.table,
                    issue.message,
                    issue.suggestion,
                )

            console.print(table)
            summary_parts = []
            if result.error_count:
                summary_parts.append(f"[bold red]{result.error_count} error(s)[/bold red]")
            if result.warning_count:
                summary_parts.append(
                    f"[bold yellow]{result.warning_count} warning(s)[/bold yellow]"
                )
            console.print(f"Summary: {', '.join(summary_parts)}")

    if fail_on_error and result.has_errors:
        sys.exit(1)

    if fail_on_warning and result.has_warnings:
        sys.exit(1)
