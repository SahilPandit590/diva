"""
Database connection factory for Diva Emotion Engine v1.0.0.
Provides SQLite WAL mode connection pooling, foreign-key enforcement,
and serialized atomic transaction context managers.
"""

from contextlib import contextmanager
from pathlib import Path
import sqlite3
import threading
from typing import Generator, Optional


class DatabaseConnectionFactory:
    """Thread-safe SQLite connection factory configured for high concurrency WAL mode."""

    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self._is_memory = (db_path == ":memory:")
        self._write_lock = threading.RLock()
        self._write_conn: Optional[sqlite3.Connection] = None
        self._local = threading.local()

        if not self._is_memory:
            parent = Path(db_path).parent
            parent.mkdir(parents=True, exist_ok=True)

        self._init_write_connection()

    def _apply_pragmas(self, conn: sqlite3.Connection) -> None:
        """Applies required production pragmas to SQLite connection."""
        cursor = conn.cursor()
        if not self._is_memory:
            cursor.execute("PRAGMA journal_mode = WAL;")
            cursor.execute("PRAGMA synchronous = NORMAL;")
        cursor.execute("PRAGMA foreign_keys = ON;")
        cursor.execute("PRAGMA busy_timeout = 5000;")
        cursor.close()

    def _init_write_connection(self) -> None:
        """Initializes the primary write connection."""
        self._write_conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            timeout=30.0,
            isolation_level=None,  # Explicit transaction management
        )
        self._write_conn.row_factory = sqlite3.Row
        self._apply_pragmas(self._write_conn)

    def execute_script(self, sql_script: str) -> None:
        """Executes a multi-statement DDL script outside an explicit transaction block."""
        with self._write_lock:
            assert self._write_conn is not None
            self._write_conn.executescript(sql_script)

    def get_read_connection(self) -> sqlite3.Connection:
        """
        Returns a thread-local read-only connection.
        In-memory databases share the write connection to see table state.
        """
        if self._is_memory:
            assert self._write_conn is not None
            return self._write_conn

        if not hasattr(self._local, "read_conn") or self._local.read_conn is None:
            conn = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
                timeout=30.0,
                isolation_level=None,
            )
            conn.row_factory = sqlite3.Row
            self._apply_pragmas(conn)
            self._local.read_conn = conn
        return self._local.read_conn

    @contextmanager
    def read_cursor(self) -> Generator[sqlite3.Cursor, None, None]:
        """Provides a read cursor with dictionary-like row access."""
        conn = self.get_read_connection()
        cursor = conn.cursor()
        try:
            yield cursor
        finally:
            cursor.close()

    @contextmanager
    def write_transaction(self) -> Generator[sqlite3.Cursor, None, None]:
        """
        Executes a serialized write transaction.
        Starts an IMMEDIATE transaction, commits on success, and rolls back on exception.
        """
        with self._write_lock:
            assert self._write_conn is not None
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
        """Closes all connection resources."""
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
