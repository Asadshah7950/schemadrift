"""Schema differ: compares two SchemaSnapshot objects and produces a DiffResult."""

from __future__ import annotations

from pg_schema_diff.models import (
    ColumnDef,
    DiffResult,
    IndexDef,
    SchemaSnapshot,
    TableDef,
)


class SchemaDiffer:
    """Compares a source and target SchemaSnapshot and returns a DiffResult."""

    def __init__(self, source: SchemaSnapshot, target: SchemaSnapshot) -> None:
        self.source = source
        self.target = target

    def diff(self) -> DiffResult:
        """Compare source vs target and return all detected differences."""
        result = DiffResult()

        self._diff_tables(result)
        self._diff_foreign_keys(result)
        self._diff_enums(result)

        return result

    def _diff_tables(self, result: DiffResult) -> None:
        src_tables = self.source.tables
        tgt_tables = self.target.tables

        src_names = set(src_tables.keys())
        tgt_names = set(tgt_tables.keys())

        # Tables in target that don't exist in source → added
        for name in tgt_names - src_names:
            result.tables_added.append(tgt_tables[name])

        # Tables in source that don't exist in target → dropped
        for name in src_names - tgt_names:
            result.tables_dropped.append(name)

        # Tables in both → compare columns and indexes
        for name in src_names & tgt_names:
            self._diff_columns(result, name, src_tables[name], tgt_tables[name])
            self._diff_indexes(result, src_tables[name], tgt_tables[name])

    def _diff_columns(
        self,
        result: DiffResult,
        table_name: str,
        src_table: TableDef,
        tgt_table: TableDef,
    ) -> None:
        src_cols = {c.name: c for c in src_table.columns}
        tgt_cols = {c.name: c for c in tgt_table.columns}

        src_col_names = set(src_cols.keys())
        tgt_col_names = set(tgt_cols.keys())

        # Columns in target not in source → added
        for col_name in tgt_col_names - src_col_names:
            result.columns_added.append((table_name, tgt_cols[col_name]))

        # Columns in source not in target → dropped
        for col_name in src_col_names - tgt_col_names:
            result.columns_dropped.append((table_name, col_name))

        # Columns in both → check for alterations
        for col_name in src_col_names & tgt_col_names:
            src_col = src_cols[col_name]
            tgt_col = tgt_cols[col_name]
            if self._column_changed(src_col, tgt_col):
                result.columns_altered.append((table_name, src_col, tgt_col))

    @staticmethod
    def _column_changed(src: ColumnDef, tgt: ColumnDef) -> bool:
        """Return True if anything meaningful changed on a column."""
        return (
            src.data_type != tgt.data_type
            or src.nullable != tgt.nullable
            or src.default != tgt.default
        )

    def _diff_indexes(
        self,
        result: DiffResult,
        src_table: TableDef,
        tgt_table: TableDef,
    ) -> None:
        src_idx = {i.name: i for i in src_table.indexes}
        tgt_idx = {i.name: i for i in tgt_table.indexes}

        src_names = set(src_idx.keys())
        tgt_names = set(tgt_idx.keys())

        for name in tgt_names - src_names:
            result.indexes_added.append(tgt_idx[name])

        for name in src_names - tgt_names:
            result.indexes_dropped.append(src_idx[name])

    def _diff_foreign_keys(self, result: DiffResult) -> None:
        src_fks = {fk.name: fk for fk in self.source.foreign_keys}
        tgt_fks = {fk.name: fk for fk in self.target.foreign_keys}

        src_names = set(src_fks.keys())
        tgt_names = set(tgt_fks.keys())

        for name in tgt_names - src_names:
            result.fks_added.append(tgt_fks[name])

        for name in src_names - tgt_names:
            result.fks_dropped.append(src_fks[name])

    def _diff_enums(self, result: DiffResult) -> None:
        src_enums = self.source.enums
        tgt_enums = self.target.enums

        src_names = set(src_enums.keys())
        tgt_names = set(tgt_enums.keys())

        for name in tgt_names - src_names:
            result.enums_added.append((name, tgt_enums[name]))

        for name in src_names & tgt_names:
            if src_enums[name] != tgt_enums[name]:
                result.enums_altered.append((name, src_enums[name], tgt_enums[name]))
