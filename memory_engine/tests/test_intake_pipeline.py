"""
Unit tests for Memory Intake Pipeline, idempotency (MEM-001), epistemic preservation (MEM-003),
and payload hash verification.
"""

import hashlib
import json
import uuid
import pytest
from memory_engine.database.connection import DatabaseConnectionFactory
from memory_engine.database.migrations import MigrationRunner
from memory_engine.entities.service import EntityAssociationService
from memory_engine.governance.exceptions import EpistemicDowngradeError
from memory_engine.governance.service import MemoryGovernanceService
from memory_engine.intake.epistemic import EpistemicPreserver
from memory_engine.intake.pipeline import MemoryIntakeService
from memory_engine.jobs.scheduler import BackgroundJobScheduler
from memory_engine.jobs.worker import MemoryJobWorker
from memory_engine.types.enums import DomainPartition, EntityType, EpistemicType


@pytest.fixture
def intake_stack():
    factory = DatabaseConnectionFactory(":memory:")
    runner = MigrationRunner(factory)
    runner.apply_migrations()
    governance = MemoryGovernanceService(factory)
    scheduler = BackgroundJobScheduler(factory)
    entities = EntityAssociationService(factory, governance)
    worker = MemoryJobWorker(factory, scheduler, entities)
    service = MemoryIntakeService(factory, governance, scheduler)
    yield service, factory, scheduler, entities, worker
    factory.close()


def test_intake_idempotency_mem001(intake_stack):
    """Verifies MEM-001: Submitting identical content twice returns existing record."""
    service, factory, _, _, _ = intake_stack
    session_id = uuid.uuid4()
    content = "The user mentioned they are studying cognitive architecture and AI systems."

    # First submission
    ev1, exp1, is_dup1 = service.submit_input(
        source_engine="PERCEPTION",
        channel="TEXT",
        domain_partition=DomainPartition.COGNITIVE,
        session_id=session_id,
        raw_content=content,
    )
    assert not is_dup1
    assert exp1 is not None

    # Second submission with exact same content, source, and session
    ev2, exp2, is_dup2 = service.submit_input(
        source_engine="PERCEPTION",
        channel="TEXT",
        domain_partition=DomainPartition.COGNITIVE,
        session_id=session_id,
        raw_content=content,
    )
    assert is_dup2
    assert ev2 == ev1
    assert exp2 == exp1

    # Verify only ONE experience and ONE input_event exist in database
    with factory.read_cursor() as cursor:
        cursor.execute("SELECT count(*) FROM experiences;")
        assert cursor.fetchone()[0] == 1
        cursor.execute("SELECT count(*) FROM input_events;")
        assert cursor.fetchone()[0] == 1


def test_epistemic_preservation_mem003(intake_stack):
    """Verifies MEM-003: Epistemic hierarchy ranks cannot be upgraded."""
    # Attempting to upgrade INTERPRETATION (rank 2) to OBSERVATION (rank 5) must raise error
    with pytest.raises(EpistemicDowngradeError):
        EpistemicPreserver.validate_epistemic_assignment(
            source_type=EpistemicType.INTERPRETATION,
            assigned_type=EpistemicType.OBSERVATION,
        )

    # Downgrading or equal rank is permitted
    EpistemicPreserver.validate_epistemic_assignment(
        source_type=EpistemicType.OBSERVATION,
        assigned_type=EpistemicType.INFERENCE,
    )


def test_payload_hash_integrity(intake_stack):
    """Verifies that payload content_hash strictly matches SHA-256 of payload bytes."""
    service, factory, _, _, _ = intake_stack
    session_id = uuid.uuid4()
    content = "Analyzing the multifaceted implications of hybrid memory architecture."
    expected_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

    _, exp_id, _ = service.submit_input(
        source_engine="PERCEPTION",
        channel="TEXT",
        domain_partition=DomainPartition.COGNITIVE,
        session_id=session_id,
        raw_content=content,
    )

    with factory.read_cursor() as cursor:
        cursor.execute(
            "SELECT payload_data, content_hash FROM experience_payloads WHERE experience_id = ?;",
            (str(exp_id),),
        )
        row = cursor.fetchone()
        assert row is not None
        assert row["content_hash"] == expected_hash
        assert hashlib.sha256(row["payload_data"]).hexdigest() == expected_hash


def test_background_jobs_and_outbox_scheduled(intake_stack):
    """Verifies that persisting an experience schedules background jobs and emits outbox events."""
    service, factory, scheduler, _, _ = intake_stack
    session_id = uuid.uuid4()

    _, exp_id, _ = service.submit_input(
        source_engine="PERCEPTION",
        channel="TEXT",
        domain_partition=DomainPartition.COGNITIVE,
        session_id=session_id,
        raw_content="Major project milestone reached with flying colors and clear evidence.",
    )

    with factory.read_cursor() as cursor:
        # Check outbox event
        cursor.execute(
            "SELECT event_name, event_payload FROM outbox_events WHERE published = 0;"
        )
        outbox_row = cursor.fetchone()
        assert outbox_row is not None
        assert outbox_row["event_name"] == "memory.experience_persisted"

        # Check background jobs
        cursor.execute("SELECT job_type FROM background_jobs ORDER BY priority ASC;")
        jobs = [r["job_type"] for r in cursor.fetchall()]
        assert "FTS5_INDEXING" in jobs
        assert "ENTITY_LINKING" in jobs


def test_job_worker_processes_indexing_and_linking(intake_stack):
    """Verifies that MemoryJobWorker drains scheduled jobs, populates FTS5 index, and resolves entities."""
    service, factory, scheduler, entities, worker = intake_stack
    session_id = uuid.uuid4()

    # Pre-register an entity with alias
    e = entities.create_or_get_entity(
        canonical_name="Diva Core",
        entity_type=EntityType.SYSTEM,
        aliases=["Diva"],
    )

    # Ingest experience mentioning alias "Diva"
    _, exp_id, _ = service.submit_input(
        source_engine="PERCEPTION",
        channel="TEXT",
        domain_partition=DomainPartition.COGNITIVE,
        session_id=session_id,
        raw_content="Diva completed background initialization seamlessly.",
    )
    assert exp_id is not None

    # Run worker to process scheduled FTS5_INDEXING and ENTITY_LINKING
    processed = worker.process_all_pending()
    assert processed >= 2

    # Verify FTS5 table has the indexed memory
    with factory.read_cursor() as cursor:
        cursor.execute("SELECT memory_id FROM memories_fts WHERE memories_fts MATCH 'background initialization';")
        row = cursor.fetchone()
        assert row is not None
        assert row["memory_id"] == str(exp_id)

        # Verify entity linking updated participants
        cursor.execute("SELECT participants FROM experiences WHERE experience_id = ?;", (str(exp_id),))
        parts = json.loads(cursor.fetchone()["participants"])
        assert str(e.entity_id) in parts


def test_dead_letter_queue_on_max_attempts(intake_stack):
    """Section 3.11: Jobs that exceed max_attempts transition to DEAD_LETTER status."""
    _, factory, scheduler, _, _ = intake_stack
    job_id, _ = scheduler.schedule_job(
        job_type="TEST_FAILING_JOB",
        input_data={"test": 1},
        idempotency_key="fail_key_1",
        max_attempts=2,
    )

    worker_id = "test_worker_1"

    # Attempt 1
    job1 = scheduler.acquire_next_job(worker_id)
    assert job1 is not None
    scheduler.fail_job(job1["job_id"], worker_id, "Error 1")

    # Should be PENDING for retry
    with factory.read_cursor() as cursor:
        cursor.execute("SELECT status, attempt_count FROM background_jobs WHERE job_id = ?;", (job_id,))
        row = cursor.fetchone()
        assert row["status"] == "PENDING"
        assert row["attempt_count"] == 1

    # Attempt 2 (exhausts max_attempts=2)
    job2 = scheduler.acquire_next_job(worker_id)
    assert job2 is not None
    scheduler.fail_job(job2["job_id"], worker_id, "Error 2 (final)")

    # Status must now be DEAD_LETTER
    with factory.read_cursor() as cursor:
        cursor.execute("SELECT status, attempt_count FROM background_jobs WHERE job_id = ?;", (job_id,))
        row = cursor.fetchone()
        assert row["status"] == "DEAD_LETTER"
        assert row["attempt_count"] == 2

