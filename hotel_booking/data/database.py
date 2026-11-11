"""Connection handling and transactions.

Two rules matter for REQ-018 and REQ-020:

1. Every write runs inside ``BEGIN IMMEDIATE`` so that SQLite takes the
   write lock up front; a second writer blocks instead of reading stale
   stock and then failing halfway through.
2. The service layer passes the same connection to every repository, so
   booking row, inventory rows and the log row commit or roll back
   together.
"""

import contextlib
import sqlite3
from collections.abc import Iterator
from pathlib import Path

from hotel_booking.data import schema


class Database:
    """Thin wrapper around a SQLite file with per-call connections."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        """Open (or create) the database file and ensure the schema."""
        self._path = str(path)
        self._shared: sqlite3.Connection | None = None
        if self._path == ":memory:":
            # An in-memory database lives inside one connection, so all
            # callers share it; file databases get one connection each.
            self._shared = self._new_connection()
        self.init_schema()

    def _new_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self._path,
            timeout=30.0,
            check_same_thread=False,
            isolation_level=None,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    @contextlib.contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Yield a connection and close it when the block ends."""
        if self._shared is not None:
            yield self._shared
            return
        conn = self._new_connection()
        try:
            yield conn
        finally:
            conn.close()

    @contextlib.contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Run a write transaction that is atomic across repositories."""
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except Exception:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")

    @contextlib.contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        """Run read-only statements without taking the write lock."""
        with self.connect() as conn:
            yield conn

    def init_schema(self) -> None:
        """Create all tables and indexes if they do not exist."""
        with self.connect() as conn:
            for statement in schema.SCHEMA_STATEMENTS:
                conn.execute(statement)
            conn.execute("PRAGMA user_version = 1")

    def close(self) -> None:
        """Close the shared in-memory connection, if any."""
        if self._shared is not None:
            self._shared.close()
            self._shared = None
