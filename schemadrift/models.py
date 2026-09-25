"""Data models for pg-schema-diff schema objects and diff results."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ColumnDef:
    """Represents a single column in a PostgreSQL table."""

    name: str
    data_type: str
    nullable: bool = True
    default: str | None = None
    is_primary_key: bool = False


@dataclass
class IndexDef:
    """Represents a PostgreSQL index on a table."""

    name: str
    table: str
    columns: list[str]
    unique: bool = False
    method: str = "btree"


@dataclass
class TableDef:
    """Represents a PostgreSQL table with its columns and indexes."""

    name: str
    columns: list[ColumnDef] = field(default_factory=list)
    indexes: list[IndexDef] = field(default_factory=list)


@dataclass
class ForeignKeyDef:
    """Represents a foreign key constraint."""

    name: str
    table: str
    columns: list[str]
    ref_table: str
    ref_columns: list[str]
    on_delete: str = "NO ACTION"


@dataclass
class SchemaSnapshot:
    """A complete snapshot of a PostgreSQL schema."""

    tables: dict[str, TableDef] = field(default_factory=dict)
    foreign_keys: list[ForeignKeyDef] = field(default_factory=list)
    enums: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class DiffResult:
    """The result of comparing two SchemaSnapshot objects."""

    tables_added: list[TableDef] = field(default_factory=list)
    tables_dropped: list[str] = field(default_factory=list)
    columns_added: list[tuple[str, ColumnDef]] = field(default_factory=list)
    columns_dropped: list[tuple[str, str]] = field(default_factory=list)
    columns_altered: list[tuple[str, ColumnDef, ColumnDef]] = field(default_factory=list)
    indexes_added: list[IndexDef] = field(default_factory=list)
    indexes_dropped: list[IndexDef] = field(default_factory=list)
    fks_added: list[ForeignKeyDef] = field(default_factory=list)
    fks_dropped: list[ForeignKeyDef] = field(default_factory=list)
    enums_added: list[tuple[str, list[str]]] = field(default_factory=list)
    enums_altered: list[tuple[str, list[str], list[str]]] = field(default_factory=list)

    def is_empty(self) -> bool:
        """Return True if there are no detected differences."""
        return (
            not self.tables_added
            and not self.tables_dropped
            and not self.columns_added
            and not self.columns_dropped
            and not self.columns_altered
            and not self.indexes_added
            and not self.indexes_dropped
            and not self.fks_added
            and not self.fks_dropped
            and not self.enums_added
            and not self.enums_altered
        )

    @property
    def has_drift(self) -> bool:
        """Return True if schema drift is detected."""
        return not self.is_empty()

