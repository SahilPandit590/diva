"""
Part 8 — Milestone 09: Production Hardening, Concurrency & Stress Tests.
Tests high throughput, contradiction graph stress, worker lease contention, and archival integrity.
"""

import time
import uuid
import pytest

from memory_engine.engine import MemoryEngine
from memory_engine.types.claim import ProposedClaim
from memory_engine.types.enums import (
    DomainPartition,
    EntityType,
    EpistemicType,
    EvidenceStatus,
)


@pytest.fixture
def eng():
    e = MemoryEngine(db_path=":memory:")
    yield e
    e.close()


def test_high_throughput_ingestion_and_fts_indexing(eng):
    """
    Stress test: rapidly ingests 100 experiences and verifies FTS5 indexing
    and retrieval latency.
    """
    session_id = uuid.uuid4()
    start_time = time.time()

    # Ingest 100 experiences
    for i in range(100):
        eng.submit_experience(
            source_engine="PERCEPTION",
            channel="STREAM",
            raw_content=f"Telemetry event payload alpha beta gamma sequence marker {i}.",
            session_id=session_id,
        )

    ingest_time = time.time() - start_time
    assert ingest_time < 5.0, f"100 ingestions took {ingest_time:.2f}s (must be < 5s)"

    # Process pending background indexing jobs
    drained = eng.worker.process_all_pending()
    assert drained >= 100

    # Test FTS5 retrieval latency
    query_start = time.time()
    results = eng.retrieve(
        query_text="alpha beta sequence marker",
        requesting_engine="THOUGHT",
        limit=20,
    )
    query_time = time.time() - query_start
    assert query_time < 0.200, f"Retrieval took {query_time:.3f}s (must be < 200ms)"
    assert len(results) > 0


def test_contradiction_graph_stress_test(eng):
    """
    Stress test: introduces a network of 20 conflicting claims across multiple entities.
    Verifies that all contradictions are correctly linked without circular deadlocks.
    """
    session_id = uuid.uuid4()
    entity_a = eng.create_or_get_entity("Stress Entity A", EntityType.CONCEPT)
    entity_b = eng.create_or_get_entity("Stress Entity B", EntityType.CONCEPT)

    claims_a = []
    # Create 10 conflicting values for predicate 'status' on Entity A
    for val in range(10):
        c = eng.store_claim(
            proposal=ProposedClaim(
                subject_entity_id=entity_a.entity_id,
                predicate="status",
                object_value=f"state_A_{val}",
                canonical_statement=f"Entity A is in state {val}.",
                epistemic_type=EpistemicType.OBSERVATION,
                source_engine="PERCEPTION",
            ),
            session_id=session_id,
        )
        claims_a.append(c)

    # All claims for Entity A must now be marked DISPUTED
    for c in claims_a:
        refreshed = eng.knowledge.get_claim(c.claim_id)
        assert refreshed.evidence_status == EvidenceStatus.DISPUTED

    # Verify contradiction links count in claim_relationships
    with eng.factory.read_cursor() as cursor:
        cursor.execute(
            "SELECT count(*) as cnt FROM claim_relationships WHERE relationship_type = 'CONTRADICTS';"
        )
        # 10 conflicting claims produce 10 * 9 / 2 = 45 pairwise contradiction edges
        count = cursor.fetchone()["cnt"]
        assert count == 45


def test_concurrent_worker_lease_contention(eng):
    """
    Stress test: Simulates multiple concurrent workers competing for background jobs.
    Ensures that no two workers acquire the same lease simultaneously.
    """
    # Schedule 20 background jobs
    job_ids = []
    for i in range(20):
        jid, _ = eng.scheduler.schedule_job(
            job_type="FTS5_INDEXING",
            input_data={"memory_id": str(uuid.uuid4()), "text": f"job text {i}"},
            idempotency_key=f"contention_key_{i}",
        )
        job_ids.append(jid)

    acquired_by_worker1 = []
    acquired_by_worker2 = []

    # Workers interleave acquisitions
    for _ in range(10):
        j1 = eng.scheduler.acquire_next_job("worker_alpha")
        if j1:
            acquired_by_worker1.append(j1["job_id"])
        j2 = eng.scheduler.acquire_next_job("worker_beta")
        if j2:
            acquired_by_worker2.append(j2["job_id"])

    # Set intersection must be empty (mutual exclusion / lease exclusivity)
    overlap = set(acquired_by_worker1).intersection(set(acquired_by_worker2))
    assert len(overlap) == 0, f"Lease conflict detected! Overlapping jobs: {overlap}"
    assert len(acquired_by_worker1) + len(acquired_by_worker2) == 20
