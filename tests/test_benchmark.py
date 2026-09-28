import time
import pytest
from schemadrift.models import ColumnDef, IndexDef, TableDef, ForeignKeyDef, SchemaSnapshot
from schemadrift.differ import SchemaDiffer
from schemadrift.generator import MigrationGenerator


def generate_mock_schema(table_count: int = 50) -> SchemaSnapshot:
    tables = {}
    fks = []
    for i in range(table_count):
        table_name = f"table_{i}"
        columns = [
            ColumnDef(name="id", data_type="integer", nullable=False, default=None, is_primary_key=True),
            ColumnDef(name=f"field_{i}", data_type="varchar(255)", nullable=True, default=None, is_primary_key=False),
            ColumnDef(name="created_at", data_type="timestamp", nullable=False, default="now()", is_primary_key=False),
        ]
        indexes = [
            IndexDef(name=f"idx_{table_name}_field", table=table_name, columns=[f"field_{i}"], unique=False)
        ]
        if i > 0:
            fks.append(
                ForeignKeyDef(
                    name=f"fk_{table_name}_parent",
                    table=table_name,
                    columns=["id"],
                    ref_table=f"table_{i-1}",
                    ref_columns=["id"],
                    on_delete="CASCADE"
                )
            )
        tables[table_name] = TableDef(name=table_name, columns=columns, indexes=indexes)
    return SchemaSnapshot(tables=tables, foreign_keys=fks, enums={})


def test_differ_benchmark_performance():
    """Verify that comparing 50 tables with indexes and foreign keys completes in under 100ms."""
    source = generate_mock_schema(50)
    target = generate_mock_schema(50)
    
    # Mutate target slightly
    target.tables["table_0"].columns.append(
        ColumnDef(name="extra_col", data_type="text", nullable=True, default=None, is_primary_key=False)
    )

    start = time.perf_counter()
    differ = SchemaDiffer(source, target)
    diff = differ.diff()
    elapsed = time.perf_counter() - start

    assert len(diff.columns_added) == 1
    assert elapsed < 0.100, f"Diffing took too long: {elapsed:.4f}s"


def test_generator_benchmark_performance():
    """Verify that generating migration SQL for 50 tables completes in under 100ms."""
    source = generate_mock_schema(25)
    target = generate_mock_schema(50)

    differ = SchemaDiffer(source, target)
    diff = differ.diff()

    start = time.perf_counter()
    gen = MigrationGenerator(diff)
    sql = gen.generate()
    elapsed = time.perf_counter() - start

    assert "BEGIN;" in sql
    assert "COMMIT;" in sql
    assert elapsed < 0.100, f"DDL Generation took too long: {elapsed:.4f}s"
