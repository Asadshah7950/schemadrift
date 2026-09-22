"""Data models for pg-schema-diff schema objects and diff results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class ColumnDef:
    """Represents a single column in a PostgreSQL table."""

    name: str
    data_type: str
    nullable: bool = True
    default: Optional[str] = None
    is_primary_key: bool = False


@dataclass
class IndexDef:
    """Represents a PostgreSQL index on a table."""

    name: str
    table: str
    columns: List[str]
    unique: bool = False
    method: str = "btree"


@dataclass
class TableDef:
    """Represents a PostgreSQL table with its columns and indexes."""

    name: str
    columns: List[ColumnDef] = field(default_factory=list)
    indexes: List[IndexDef] = field(default_factory=list)


@dataclass
class ForeignKeyDef:
    """Represents a foreign key constraint."""

    name: str
    table: str
    columns: List[str]
    ref_table: str
    ref_columns: List[str]
    on_delete: str = "NO ACTION"


@dataclass
class SchemaSnapshot:
    """A complete snapshot of a PostgreSQL schema."""

    tables: Dict[str, TableDef] = field(default_factory=dict)
    foreign_keys: List[ForeignKeyDef] = field(default_factory=list)
    enums: Dict[str, List[str]] = field(default_factory=dict)


@dataclass
class DiffResult:
    """The result of comparing two SchemaSnapshot objects."""

    tables_added: List[TableDef] = field(default_factory=list)
    tables_dropped: List[str] = field(default_factory=list)
    columns_added: List[tuple[str, ColumnDef]] = field(default_factory=list)
    columns_dropped: List[tuple[str, str]] = field(default_factory=list)
    columns_altered: List[tuple[str, ColumnDef, ColumnDef]] = field(default_factory=list)
    indexes_added: List[IndexDef] = field(default_factory=list)
    indexes_dropped: List[IndexDef] = field(default_factory=list)
    fks_added: List[ForeignKeyDef] = field(default_factory=list)
    fks_dropped: List[ForeignKeyDef] = field(default_factory=list)
    enums_added: List[tuple[str, List[str]]] = field(default_factory=list)
    enums_altered: List[tuple[str, List[str], List[str]]] = field(default_factory=list)

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
