"""Data models for pg-schema-diff schema objects and diff results."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ColumnDef:
    """Represents a single column in a PostgreSQL table."""

    name: str
    data_type: str
    nullable: bool = True
    default: str | None = None
    is_primary_key: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert column definition to dictionary."""
        return {
            "name": self.name,
            "data_type": self.data_type,
            "nullable": self.nullable,
            "default": self.default,
            "is_primary_key": self.is_primary_key,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ColumnDef:
        """Construct ColumnDef from dictionary."""
        return cls(
            name=data["name"],
            data_type=data["data_type"],
            nullable=data.get("nullable", True),
            default=data.get("default"),
            is_primary_key=data.get("is_primary_key", False),
        )


@dataclass
class IndexDef:
    """Represents a PostgreSQL index on a table."""

    name: str
    table: str
    columns: list[str]
    unique: bool = False
    method: str = "btree"

    def to_dict(self) -> dict[str, Any]:
        """Convert index definition to dictionary."""
        return {
            "name": self.name,
            "table": self.table,
            "columns": list(self.columns),
            "unique": self.unique,
            "method": self.method,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IndexDef:
        """Construct IndexDef from dictionary."""
        return cls(
            name=data["name"],
            table=data["table"],
            columns=list(data.get("columns", [])),
            unique=data.get("unique", False),
            method=data.get("method", "btree"),
        )


@dataclass
class TableDef:
    """Represents a PostgreSQL table with its columns and indexes."""

    name: str
    columns: list[ColumnDef] = field(default_factory=list)
    indexes: list[IndexDef] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert table definition to dictionary."""
        return {
            "name": self.name,
            "columns": [col.to_dict() for col in self.columns],
            "indexes": [idx.to_dict() for idx in self.indexes],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TableDef:
        """Construct TableDef from dictionary."""
        return cls(
            name=data["name"],
            columns=[ColumnDef.from_dict(c) for c in data.get("columns", [])],
            indexes=[IndexDef.from_dict(i) for i in data.get("indexes", [])],
        )


@dataclass
class ForeignKeyDef:
    """Represents a foreign key constraint."""

    name: str
    table: str
    columns: list[str]
    ref_table: str
    ref_columns: list[str]
    on_delete: str = "NO ACTION"

    def to_dict(self) -> dict[str, Any]:
        """Convert foreign key definition to dictionary."""
        return {
            "name": self.name,
            "table": self.table,
            "columns": list(self.columns),
            "ref_table": self.ref_table,
            "ref_columns": list(self.ref_columns),
            "on_delete": self.on_delete,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ForeignKeyDef:
        """Construct ForeignKeyDef from dictionary."""
        return cls(
            name=data["name"],
            table=data["table"],
            columns=list(data.get("columns", [])),
            ref_table=data["ref_table"],
            ref_columns=list(data.get("ref_columns", [])),
            on_delete=data.get("on_delete", "NO ACTION"),
        )


@dataclass
class SchemaSnapshot:
    """A complete snapshot of a PostgreSQL schema."""

    tables: dict[str, TableDef] = field(default_factory=dict)
    foreign_keys: list[ForeignKeyDef] = field(default_factory=list)
    enums: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize schema snapshot to a JSON-compatible dictionary."""
        return {
            "version": "1.0",
            "tables": {name: tbl.to_dict() for name, tbl in sorted(self.tables.items())},
            "foreign_keys": [fk.to_dict() for fk in self.foreign_keys],
            "enums": {name: list(vals) for name, vals in sorted(self.enums.items())},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SchemaSnapshot:
        """Construct SchemaSnapshot from dictionary."""
        tables = {
            name: TableDef.from_dict(tbl_data)
            for name, tbl_data in data.get("tables", {}).items()
        }
        foreign_keys = [
            ForeignKeyDef.from_dict(fk_data)
            for fk_data in data.get("foreign_keys", [])
        ]
        enums = {
            name: list(vals)
            for name, vals in data.get("enums", {}).items()
        }
        return cls(tables=tables, foreign_keys=foreign_keys, enums=enums)

    def to_json(self, indent: int | None = 2) -> str:
        """Serialize schema snapshot to formatted JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_json(cls, json_str: str) -> SchemaSnapshot:
        """Deserialize schema snapshot from JSON string."""
        return cls.from_dict(json.loads(json_str))

    def to_file(self, filepath: str, indent: int | None = 2) -> None:
        """Save schema snapshot to a JSON file."""
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(self.to_json(indent=indent))

    @classmethod
    def from_file(cls, filepath: str) -> SchemaSnapshot:
        """Load schema snapshot from a JSON file."""
        with open(filepath, encoding="utf-8") as f:
            return cls.from_json(f.read())


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

    @property
    def has_destructive_changes(self) -> bool:
        """Return True if the diff contains destructive changes (dropped tables or columns)."""
        return bool(self.tables_dropped or self.columns_dropped)

    @property
    def destructive_changes_count(self) -> int:
        """Return total count of destructive changes."""
        return len(self.tables_dropped) + len(self.columns_dropped)
