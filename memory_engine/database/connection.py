"""
Database connection factory and serialized writer management for Diva Memory Engine v3.0.
Enforces SQLite 3.45+ in WAL mode with strict PRAGMA configurations.
Ensures single-writer serialization with concurrent multi-reader access.
"""

import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

from memory_engine.database.schema import CREATE_TABLES_SQL, SCHEMA_PRAGMAS


class DatabaseConnectionFactory:
    """
    Manages SQLite connections for Diva Memory Engine v3.0.
    Enforces the Serialized Writer Constraint:
      - All write operations route through a single write connection protected by a mutex lock.
      - Read operations use independent connections benefiting from WAL non-blocking concurrency.
    """

    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self._is_memory = db_path == ":memory:"
        self._write_lock = threading.RLock()
        self._write_conn: Optional[sqlite3.Connection] = None
        self._local = threading.local()

        if not self._is_memory:
            # Ensure parent directory exists
            parent = Path(db_path).parent
            parent.mkdir(parents=True, exist_ok=True)

        # Initialize the persistent write connection
        self._init_write_connection()

    def _apply_pragmas(self, conn: sqlite3.Connection) -> None:
        """Apply all mandatory PRAGMA invariants defined in v3.0 specification."""
        cursor = conn.cursor()
        if not self._is_memory:
            cursor.execute("PRAGMA journal_mode = WAL;")
            cursor.execute("PRAGMA synchronous = NORMAL;")
        cursor.execute("PRAGMA foreign_keys = ON;")
        cursor.execute("PRAGMA busy_timeout = 30000;")
        cursor.execute("PRAGMA cache_size = -65536;")
        cursor.execute("PRAGMA temp_store = MEMORY;")
        cursor.execute("PRAGMA mmap_size = 268435456;")
        cursor.execute("PRAGMA wal_autocheckpoint = 1000;")
        cursor.close()

    def _init_write_connection(self) -> None:
        """Create and configure the primary write connection."""
        self._write_conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            timeout=30.0,
            isolation_level=None  # Explicit transaction control
        )
        self._write_conn.row_factory = sqlite3.Row
        self._apply_pragmas(self._write_conn)

    def initialize_schema(self) -> None:
        """Execute full DDL to create all tables and indexes across 14 domains."""
        with self._write_lock:
            # executescript executes a COMMIT before running and commits when finished
            self._write_conn.executescript(CREATE_TABLES_SQL)

    def get_read_connection(self) -> sqlite3.Connection:
        """
        Get a thread-local read-only connection.
        In-memory databases share the write connection to see table state.
        """
        if self._is_memory:
            return self._write_conn

        if not hasattr(self._local, "read_conn") or self._local.read_conn is None:
            conn = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
                timeout=30.0,
                isolation_level=None
            )
            conn.row_factory = sqlite3.Row
            self._apply_pragmas(conn)
            self._local.read_conn = conn
        return self._local.read_conn

    @contextmanager
    def read_cursor(self) -> Generator[sqlite3.Cursor, None, None]:
        """Context manager yielding a cursor for reading data."""
        conn = self.get_read_connection()
        cursor = conn.cursor()
        try:
            yield cursor
        finally:
            cursor.close()

    @contextmanager
    def write_transaction(self) -> Generator[sqlite3.Cursor, None, None]:
        """
        Context manager for serialized write transactions.
        Acquires write lock, starts IMMEDIATE transaction, and guarantees commit/rollback.
        """
        with self._write_lock:
            cursor = self._write_conn.cursor()
            cursor.execute("BEGIN IMMEDIATE;")
            try:
                yield cursor
                cursor.execute("COMMIT;")
            except Exception:
                cursor.execute("ROLLBACK;")
                raise
            finally:
                cursor.close()

    def close(self) -> None:
        """Close connections and cleanup."""
        with self._write_lock:
            if hasattr(self._local, "read_conn") and self._local.read_conn is not None:
                try:
                    self._local.read_conn.close()
                except Exception:
                    pass
                self._local.read_conn = None

            if self._write_conn is not None:
                try:
                    self._write_conn.close()
                except Exception:
                    pass
                self._write_conn = None
