"""Unit tests for SchemaInspector using mocked psycopg2."""

from __future__ import annotations

from typing import Any

import psycopg2
import pytest

from schemadrift.inspector import SchemaInspector
from schemadrift.models import SchemaSnapshot


class TestSchemaInspectorSnapshot:
    def test_snapshot_returns_schema_snapshot(self, mocker: Any) -> None:  # type: ignore[name-defined]
        """Snapshot builds a SchemaSnapshot correctly from mocked cursor results."""
        mock_conn = mocker.MagicMock()
        mock_cursor = mocker.MagicMock()

        # Context manager support for `with conn.cursor() as cur:`
        mock_conn.cursor.return_value.__enter__ = mocker.Mock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = mocker.Mock(return_value=False)

        # Side effects for sequential cursor.execute() / fetchall() calls:
        # 1. Tables query → returns one table "users"
        # 2. Columns for "users" → returns one column
        # 3. Primary keys for "users" → returns "id" as PK
        # 4. Indexes for "users" → empty
        # 5. Foreign keys → empty
        # 6. Enums → empty
        mock_cursor.fetchall.side_effect = [
            [("users",)],                                        # tables
            [("id", "integer", "NO", None)],                     # columns for users
            [("id",)],                                           # primary keys for users
            [],                                                   # indexes for users
            [],                                                   # foreign keys
            [],                                                   # enums
        ]

        mocker.patch("psycopg2.connect", return_value=mock_conn)

        inspector = SchemaInspector(dsn="postgres://fake/db")
        snapshot = inspector.snapshot()

        assert isinstance(snapshot, SchemaSnapshot)
        assert "users" in snapshot.tables
        users_table = snapshot.tables["users"]
        assert len(users_table.columns) == 1
        assert users_table.columns[0].name == "id"
        assert users_table.columns[0].data_type == "integer"
        assert users_table.columns[0].is_primary_key is True
        assert users_table.columns[0].nullable is False  # "NO" → False

    def test_snapshot_with_no_tables(self, mocker: Any) -> None:  # type: ignore[name-defined]
        """Empty database returns an empty SchemaSnapshot."""
        mock_conn = mocker.MagicMock()
        mock_cursor = mocker.MagicMock()
        mock_conn.cursor.return_value.__enter__ = mocker.Mock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = mocker.Mock(return_value=False)

        mock_cursor.fetchall.side_effect = [
            [],  # tables → none
            [],  # foreign keys
            [],  # enums
        ]

        mocker.patch("psycopg2.connect", return_value=mock_conn)

        snapshot = SchemaInspector("postgres://fake/db").snapshot()

        assert snapshot.tables == {}
        assert snapshot.foreign_keys == []
        assert snapshot.enums == {}

    def test_connection_error_raises(self, mocker: Any) -> None:  # type: ignore[name-defined]
        """OperationalError from psycopg2.connect should propagate to the caller."""
        mocker.patch(
            "psycopg2.connect",
            side_effect=psycopg2.OperationalError("could not connect"),
        )

        inspector = SchemaInspector(dsn="postgres://bad-host/db")

        with pytest.raises(psycopg2.OperationalError):
            inspector.snapshot()

    def test_connection_is_closed_after_snapshot(self, mocker: Any) -> None:  # type: ignore[name-defined]
        """The DB connection must be closed even on success."""
        mock_conn = mocker.MagicMock()
        mock_cursor = mocker.MagicMock()
        mock_conn.cursor.return_value.__enter__ = mocker.Mock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = mocker.Mock(return_value=False)

        mock_cursor.fetchall.side_effect = [[], [], []]

        mocker.patch("psycopg2.connect", return_value=mock_conn)

        SchemaInspector("postgres://fake/db").snapshot()

        mock_conn.close.assert_called_once()
