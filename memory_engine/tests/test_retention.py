"""
Unit tests for Retention Engine, dependency locking, and reversible cold archiving (MEM-010).
"""

import uuid
from pathlib import Path
import pytest
from memory_engine.consolidation.retention import (
    ArchiveIntegrityError,
    DependencyLockedError,
    RetentionEngineService,
)
from memory_engine.database.connection import DatabaseConnectionFactory
from memory_engine.database.migrations import MigrationRunner
from memory_engine.governance.service import MemoryGovernanceService
from memory_engine.intake.pipeline import MemoryIntakeService
from memory_engine.jobs.scheduler import BackgroundJobScheduler
from memory_engine.types.enums import DomainPartition


@pytest.fixture
def retention_stack(tmp_path):
    factory = DatabaseConnectionFactory(":memory:")
    runner = MigrationRunner(factory)
    runner.apply_migrations()
    governance = MemoryGovernanceService(factory)
    scheduler = BackgroundJobScheduler(factory)
    intake = MemoryIntakeService(factory, governance, scheduler)
    retention = RetentionEngineService(factory, governance)
    yield retention, intake, factory, tmp_path
    factory.close()


def test_dependency_locking_prevents_archival_mem010(retention_stack):
    """Verifies MEM-010: Memories with active dependencies cannot be archived."""
    retention, intake, factory, archive_dir = retention_stack
    session_id = uuid.uuid4()

    # Create an experience
    _, exp_id, _ = intake.submit_input(
        source_engine="PERCEPTION",
        channel="TEXT",
        domain_partition=DomainPartition.COGNITIVE,
        session_id=session_id,
        raw_content="Critical source event for downstream derivations.",
        importance_flag=True,
    )
    assert exp_id is not None

    # Mark experience as CONSOLIDATED so it meets base eligibility
    with factory.write_transaction() as cursor:
        cursor.execute(
            "UPDATE experiences SET retention_status = 'CONSOLIDATED' WHERE experience_id = ?;",
            (str(exp_id),),
        )

    # Add downstream dependency (dependent relies on this source)
    dependent_id = uuid.uuid4()
    retention.add_dependency(dependent_id=dependent_id, source_id=exp_id, dependency_type="CLAIM")

    # Attempt to archive must fail due to active dependency
    with pytest.raises(DependencyLockedError):
        retention.archive_memory(memory_id=exp_id, archive_dir=archive_dir)


def test_reversible_cold_archival_mem010(retention_stack):
    """
    Verifies MEM-010: Archival compresses payload; restoration decompresses
    and completely restores memory to usable state.
    """
    retention, intake, factory, archive_dir = retention_stack
    session_id = uuid.uuid4()
    original_text = "Comprehensive logs of machine learning training run with weights and hyperparams."

    _, exp_id, _ = intake.submit_input(
        source_engine="PERCEPTION",
        channel="TEXT",
        domain_partition=DomainPartition.COGNITIVE,
        session_id=session_id,
        raw_content=original_text,
    )
    assert exp_id is not None

    # Transition to CONSOLIDATED so it is eligible
    with factory.write_transaction() as cursor:
        cursor.execute(
            "UPDATE experiences SET retention_status = 'CONSOLIDATED' WHERE experience_id = ?;",
            (str(exp_id),),
        )

    # 1. Archive
    archive_id = retention.archive_memory(memory_id=exp_id, archive_dir=archive_dir)
    assert archive_id is not None

    # Verify status in database
    with factory.read_cursor() as cursor:
        cursor.execute("SELECT retention_status FROM experiences WHERE experience_id = ?;", (str(exp_id),))
        assert cursor.fetchone()[0] == "ARCHIVED"

        cursor.execute("SELECT is_archived, archive_path FROM experience_payloads WHERE experience_id = ?;", (str(exp_id),))
        p_row = cursor.fetchone()
        assert p_row["is_archived"] == 1
        assert Path(p_row["archive_path"]).exists()

    # 2. Restore (Reversibility check)
    restored_bytes = retention.restore_archived_memory(memory_id=exp_id)
    assert restored_bytes.decode("utf-8") == original_text

    # Verify database state after restore
    with factory.read_cursor() as cursor:
        cursor.execute("SELECT retention_status FROM experiences WHERE experience_id = ?;", (str(exp_id),))
        assert cursor.fetchone()[0] == "CONSOLIDATED"

        cursor.execute("SELECT is_archived, payload_data FROM experience_payloads WHERE experience_id = ?;", (str(exp_id),))
        p_row = cursor.fetchone()
        assert p_row["is_archived"] == 0
        assert p_row["payload_data"].decode("utf-8") == original_text


def test_archive_checksum_tamper_detection(retention_stack):
    """Verifies that tampering with an archived file is caught via checksum validation."""
    retention, intake, factory, archive_dir = retention_stack
    session_id = uuid.uuid4()

    _, exp_id, _ = intake.submit_input(
        source_engine="PERCEPTION",
        channel="TEXT",
        domain_partition=DomainPartition.COGNITIVE,
        session_id=session_id,
        raw_content="Tamper-proof payload verification test.",
    )
    with factory.write_transaction() as cursor:
        cursor.execute(
            "UPDATE experiences SET retention_status = 'CONSOLIDATED' WHERE experience_id = ?;",
            (str(exp_id),),
        )

    retention.archive_memory(memory_id=exp_id, archive_dir=archive_dir)

    # Tamper with file on disk
    archive_file = archive_dir / f"{exp_id}.zlib"
    archive_file.write_bytes(b"corrupted_bytes_that_violate_checksum")

    with pytest.raises(ArchiveIntegrityError):
        retention.restore_archived_memory(memory_id=exp_id)
