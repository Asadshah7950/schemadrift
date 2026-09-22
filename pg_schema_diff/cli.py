"""CLI entry point for pg-schema-diff."""

from __future__ import annotations

import json
import sys

import click
from rich.console import Console
from rich.table import Table

from pg_schema_diff.differ import SchemaDiffer
from pg_schema_diff.generator import MigrationGenerator
from pg_schema_diff.inspector import SchemaInspector

console = Console()


@click.group()
@click.version_option()
def main() -> None:
    """pg-schema-diff: Detect schema drift between PostgreSQL databases."""


# ---------------------------------------------------------------------------
# diff command
# ---------------------------------------------------------------------------


@main.command()
@click.option("--source", required=True, help="Source database DSN (e.g. postgres://user:pass@host/db).")
@click.option("--target", required=True, help="Target database DSN.")
@click.option("--output", "-o", default=None, help="Write migration SQL to this file path.")
@click.option(
    "--format",
    "fmt",
    default="sql",
    type=click.Choice(["sql", "json", "summary"]),
    show_default=True,
    help="Output format.",
)
def diff(source: str, target: str, output: str | None, fmt: str) -> None:
    """Compare SOURCE and TARGET schemas and generate a migration script."""
    try:
        console.print("[bold blue]Inspecting source schema…[/bold blue]")
        src_snapshot = SchemaInspector(source).snapshot()
    except Exception as exc:  # noqa: BLE001
        click.echo(f"Error connecting to source database: {exc}", err=True)
        sys.exit(1)

    try:
        console.print("[bold blue]Inspecting target schema…[/bold blue]")
        tgt_snapshot = SchemaInspector(target).snapshot()
    except Exception as exc:  # noqa: BLE001
        click.echo(f"Error connecting to target database: {exc}", err=True)
        sys.exit(1)

    diff_result = SchemaDiffer(src_snapshot, tgt_snapshot).diff()

    if fmt == "sql":
        content = MigrationGenerator(diff_result).generate()
    elif fmt == "json":
        content = _diff_to_json(diff_result)
    else:  # summary
        content = _diff_summary(diff_result)

    if output:
        with open(output, "w", encoding="utf-8") as fh:
            fh.write(content)
        console.print(f"[green]Migration written to {output}[/green]")
    else:
        click.echo(content)


# ---------------------------------------------------------------------------
# inspect command
# ---------------------------------------------------------------------------


@main.command()
@click.option("--dsn", required=True, help="Database DSN to inspect.")
def inspect(dsn: str) -> None:
    """Inspect a PostgreSQL schema and print a summary table."""
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
# Formatters
# ---------------------------------------------------------------------------


def _diff_to_json(diff_result: "pg_schema_diff.models.DiffResult") -> str:  # type: ignore[name-defined]
    """Serialize the diff result to a JSON string."""
    data = {
        "tables_added": [t.name for t in diff_result.tables_added],
        "tables_dropped": list(diff_result.tables_dropped),
        "columns_added": [
            {"table": t, "column": c.name, "type": c.data_type}
            for t, c in diff_result.columns_added
        ],
        "columns_dropped": [
            {"table": t, "column": c} for t, c in diff_result.columns_dropped
        ],
        "columns_altered": [
            {"table": t, "column": s.name, "from_type": s.data_type, "to_type": g.data_type}
            for t, s, g in diff_result.columns_altered
        ],
        "indexes_added": [i.name for i in diff_result.indexes_added],
        "indexes_dropped": [i.name for i in diff_result.indexes_dropped],
        "fks_added": [fk.name for fk in diff_result.fks_added],
        "fks_dropped": [fk.name for fk in diff_result.fks_dropped],
    }
    return json.dumps(data, indent=2)


def _diff_summary(diff_result: "pg_schema_diff.models.DiffResult") -> str:  # type: ignore[name-defined]
    """Return a human-readable plain-text summary of the diff."""
    lines = ["Schema Diff Summary", "=" * 40]
    lines.append(f"Tables added:    {len(diff_result.tables_added)}")
    lines.append(f"Tables dropped:  {len(diff_result.tables_dropped)}")
    lines.append(f"Columns added:   {len(diff_result.columns_added)}")
    lines.append(f"Columns dropped: {len(diff_result.columns_dropped)}")
    lines.append(f"Columns altered: {len(diff_result.columns_altered)}")
    lines.append(f"Indexes added:   {len(diff_result.indexes_added)}")
    lines.append(f"Indexes dropped: {len(diff_result.indexes_dropped)}")
    lines.append(f"FKs added:       {len(diff_result.fks_added)}")
    lines.append(f"FKs dropped:     {len(diff_result.fks_dropped)}")
    return "\n".join(lines)
