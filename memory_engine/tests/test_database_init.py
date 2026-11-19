"""
Unit tests for database initialization, PRAGMA invariants, STRICT tables, and migrations.
"""

import sqlite3
import pytest
from memory_engine.database.connection import DatabaseConnectionFactory
from memory_engine.database.migrations import MigrationRunner


@pytest.fixture
def db_factory():
    factory = DatabaseConnectionFactory(":memory:")
    runner = MigrationRunner(factory)
    runner.apply_migrations()
    yield factory
    factory.close()


def test_schema_and_tables_created(db_factory):
    with db_factory.read_cursor() as cursor:
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = {row[0] for row in cursor.fetchall()}

    expected_tables = {
        "schema_versions",
        "access_policies",
        "audit_events",
        "background_jobs",
        "background_leases",
        "outbox_events",
        "input_events",
        "experiences",
        "experience_payloads",
        "entities",
        "entity_aliases",
        "claims",
        "entity_attributes",
        "claim_assessments",
        "claim_versions",
        "evidence_references",
        "derivation_links",
        "memory_relationships",
        "claim_relationships",
        "memory_representations",
        "representation_lineage",
        "memory_appraisals",
        "appraisal_history",
        "development_requests",
        "development_proposals",
        "development_reviews",
        "consolidation_jobs",
        "consolidation_coverage",
        "residual_claims",
        "retrieval_events",
        "memory_embeddings_fallback",
        "retention_records",
        "archive_records",
        "memory_dependencies",
        "continuity_checkpoints",
        "memories_fts",
    }

    missing = expected_tables - tables
    assert not missing, f"Missing expected tables: {missing}"


def test_seed_access_policies(db_factory):
    with db_factory.read_cursor() as cursor:
        cursor.execute("SELECT count(*) FROM access_policies WHERE active = 1;")
        count = cursor.fetchone()[0]
        assert count == 14, f"Expected 14 active seed policies, found {count}"


def test_pragmas_enforced(db_factory):
    with db_factory.read_cursor() as cursor:
        cursor.execute("PRAGMA foreign_keys;")
        assert cursor.fetchone()[0] == 1, "Foreign keys must be ON"

        cursor.execute("PRAGMA busy_timeout;")
        assert cursor.fetchone()[0] == 30000, "Busy timeout must be 30000ms"


def test_transaction_rollback_on_error(db_factory):
    with pytest.raises(ValueError):
        with db_factory.write_transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO schema_versions (version_name, applied_at, migration_sql, checksum)
                VALUES ('test_rollback', 'now', 'SELECT 1;', 'abc');
                """
            )
            raise ValueError("Forced error to test rollback")

    with db_factory.read_cursor() as cursor:
        cursor.execute("SELECT count(*) FROM schema_versions WHERE version_name = 'test_rollback';")
        assert cursor.fetchone()[0] == 0, "Failed transaction was not rolled back!"


def test_strict_mode_enforcement(db_factory):
    """Verifies that STRICT tables reject invalid column data types."""
    with pytest.raises(sqlite3.IntegrityError):
        with db_factory.write_transaction() as cursor:
            # schema_versions has version_id INTEGER PRIMARY KEY
            # Trying to insert a string where integer is required in STRICT table
            cursor.execute(
                """
                INSERT INTO schema_versions (version_id, version_name, applied_at, migration_sql, checksum)
                VALUES ('NOT_AN_INTEGER', 'invalid_name', '2026-11-18', 'sql', 'hash');
                """
            )
