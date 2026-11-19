"""
Part 9.2 — End-to-End Verification Scenarios 11 through 20.
Implements the exact end-to-end specifications from memory_implementation_plan.txt.
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
import pytest

from memory_engine.development.service import MemoryDevelopmentService
from memory_engine.engine import MemoryEngine
from memory_engine.governance.exceptions import MemoryAccessDeniedError
from memory_engine.retrieval.intent_router import RetrievalIntent
from memory_engine.types.claim import ProposedClaim
from memory_engine.types.enums import (
    AccessAction,
    DevelopmentOperationType,
    DevelopmentResultStatus,
    DomainPartition,
    EntityStatus,
    EntityType,
    EpistemicType,
    EvidenceStatus,
    MemoryRelationshipType,
)


@pytest.fixture
def eng():
    e = MemoryEngine(db_path=":memory:")
    yield e
    e.close()


# ============================================================================
# SCENARIO 11 — ENTITY RESOLUTION AND MERGE
# ============================================================================
def test_scenario_11_entity_resolution_and_merge(eng):
    session_id = uuid.uuid4()

    # Step 1: EXP-001 mentions "Alex"
    alex_entity = eng.create_or_get_entity("Alex", EntityType.PERSON)
    _, exp1_id, _ = eng.submit_experience(
        source_engine="PERCEPTION",
        channel="TEXT",
        raw_content="Alex joined the team.",
        session_id=session_id,
        participants=[alex_entity.entity_id],
    )

    # Step 2: EXP-005 mentions "Alexander Chen"
    alexander_entity = eng.create_or_get_entity("Alexander Chen", EntityType.PERSON)
    _, exp5_id, _ = eng.submit_experience(
        source_engine="PERCEPTION",
        channel="TEXT",
        raw_content="Alexander Chen led the retrospective.",
        session_id=session_id,
        participants=[alexander_entity.entity_id],
    )

    # Step 5 & 6: Governance merges Alexander Chen into Alex
    eng.merge_entities(
        source_entity_id=alexander_entity.entity_id,
        target_entity_id=alex_entity.entity_id,
        actor_engine="MEMORY_GOVERNANCE",
    )

    # Step 7 & Expected Outcomes:
    # 1. Alexander Chen status is MERGED, merged_into is Alex
    with eng.factory.read_cursor() as cursor:
        cursor.execute(
            "SELECT status, merged_into FROM entities WHERE entity_id = ?;",
            (str(alexander_entity.entity_id),),
        )
        row = cursor.fetchone()
        assert row["status"] == "MERGED"
        assert row["merged_into"] == str(alex_entity.entity_id)

        # 2. Alex entity has alias "Alexander Chen"
        cursor.execute(
            "SELECT * FROM entity_aliases WHERE entity_id = ? AND alias_text = 'Alexander Chen';",
            (str(alex_entity.entity_id),),
        )
        assert cursor.fetchone() is not None

        # 3. EXP-005 participants updated to include Alex
        cursor.execute(
            "SELECT participants FROM experiences WHERE experience_id = ?;",
            (str(exp5_id),),
        )
        parts = json.loads(cursor.fetchone()["participants"])
        assert str(alex_entity.entity_id) in parts

        # 4. ENTITY_MERGED audit event recorded
        cursor.execute(
            "SELECT * FROM audit_events WHERE event_type = 'ENTITY_MERGED' AND target_id = ?;",
            (str(alexander_entity.entity_id),),
        )
        assert cursor.fetchone() is not None


# ============================================================================
# SCENARIO 12 — CONTINUITY CHECKPOINT AND RECOVERY
# ============================================================================
def test_scenario_12_continuity_checkpoint_and_recovery(eng):
    session_id = uuid.uuid4()
    goals = [uuid.uuid4() for _ in range(5)]
    commitments = [uuid.uuid4() for _ in range(2)]
    attention_snapshot = uuid.uuid4()

    # Step 2: Create checkpoint
    cp = eng.create_checkpoint(
        session_id=session_id,
        domain_partition=DomainPartition.COGNITIVE,
        attention_snapshot_ref=attention_snapshot,
        active_goal_refs=goals,
        unresolved_commitment_refs=commitments,
        requesting_engine="COGNITIVE_INTEGRATION",
    )
    assert cp is not None
    assert len(cp.active_goal_refs) == 5

    # Step 3 & 4: Restore checkpoint (simulating recovery)
    restored = eng.restore_checkpoint(
        session_id=session_id,
        domain_partition=DomainPartition.COGNITIVE,
        requesting_engine="COGNITIVE_INTEGRATION",
    )
    assert restored is not None
    assert restored.attention_snapshot_ref == attention_snapshot
    assert len(restored.active_goal_refs) == 5
    assert len(restored.unresolved_commitment_refs) == 2


# ============================================================================
# SCENARIO 13 — BACKGROUND JOB CRASH RECOVERY
# ============================================================================
def test_scenario_13_background_job_crash_recovery(eng):
    job_id, _ = eng.scheduler.schedule_job(
        job_type="PATTERN_DETECTION",
        input_data={"scan": "all"},
        idempotency_key="crash_job_key",
        max_attempts=3,
    )

    # Worker 1 acquires job with 1-second lease
    worker1_id = "crashed_worker"
    leased = eng.scheduler.acquire_next_job(worker1_id, lease_duration_seconds=1)
    assert leased is not None
    assert leased["job_id"] == job_id

    # Simulate worker crash: lease expires in database
    past = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    with eng.factory.write_transaction() as cursor:
        cursor.execute("UPDATE background_leases SET expires_at = ? WHERE job_id = ?;", (past, job_id))

    # Worker 2 attempts to acquire: scheduler cleans expired lease and resets job to PENDING
    worker2_id = "recovery_worker"
    reacquired = eng.scheduler.acquire_next_job(worker2_id, lease_duration_seconds=60)
    assert reacquired is not None
    assert reacquired["job_id"] == job_id
    assert reacquired["attempt_count"] == 2

    # Worker 2 completes job successfully
    eng.scheduler.complete_job(job_id, worker2_id, result_data={"status": "ok"})

    with eng.factory.read_cursor() as cursor:
        cursor.execute("SELECT status FROM background_jobs WHERE job_id = ?;", (job_id,))
        assert cursor.fetchone()["status"] == "COMPLETED"


# ============================================================================
# SCENARIO 14 — OUTBOX EVENT TRANSACTIONAL CONSISTENCY
# ============================================================================
def test_scenario_14_outbox_event_transactional_consistency(eng):
    session_id = uuid.uuid4()
    _, exp_id, _ = eng.submit_experience(
        source_engine="PERCEPTION",
        channel="TEXT",
        raw_content="Transactional consistency message.",
        session_id=session_id,
    )
    assert exp_id is not None

    # Verify that outbox event exists in database
    with eng.factory.read_cursor() as cursor:
        cursor.execute(
            "SELECT * FROM outbox_events WHERE event_name = 'memory.experience_persisted' AND published = 0;"
        )
        row = cursor.fetchone()
        assert row is not None

    # OutboxWorker drains pending events
    published_count = eng.outbox.process_pending_events(batch_size=10)
    assert published_count >= 1

    # Verify marked as published
    with eng.factory.read_cursor() as cursor:
        cursor.execute(
            "SELECT * FROM outbox_events WHERE event_name = 'memory.experience_persisted' AND published = 1;"
        )
        assert cursor.fetchone() is not None


# ============================================================================
# SCENARIO 15 — REAPPRAISAL VERSIONING
# ============================================================================
def test_scenario_15_reappraisal_versioning(eng):
    session_id = uuid.uuid4()
    _, exp_id, _ = eng.submit_experience(
        source_engine="PERCEPTION",
        channel="TEXT",
        raw_content="Difficult interaction occurred.",
        session_id=session_id,
    )

    # Initial appraisal
    apr1 = eng.submit_appraisal(
        experience_id=exp_id,
        appraising_engine="EMOTION",
        appraisal_type="EMOTIONAL_PAD",
        appraisal_content={"valence": -0.6, "arousal": 0.5, "state": "frustrated"},
        confidence=0.75,
        session_id=session_id,
    )

    # Reappraisal: Diva felt confused, not frustrated
    apr2 = eng.submit_appraisal(
        experience_id=exp_id,
        appraising_engine="EMOTION",
        appraisal_type="EMOTIONAL_PAD",
        appraisal_content={"valence": -0.2, "arousal": 0.3, "state": "confused"},
        confidence=0.80,
        session_id=session_id,
    )

    # Outcomes:
    appraisals = eng.get_appraisals(exp_id, appraisal_type="EMOTIONAL_PAD")
    assert len(appraisals) == 1
    current = appraisals[0]
    assert current["content"]["state"] == "confused"
    assert current["version"] == 2

    # appraisal_history has 1 archived version (v1 snapshot recorded before update)
    # The current v2 lives in memory_appraisals, not history.
    appraisal_id = current["appraisal_id"]
    with eng.factory.read_cursor() as cursor:
        cursor.execute(
            "SELECT * FROM appraisal_history WHERE appraisal_id = ? ORDER BY version_number ASC;",
            (str(appraisal_id),),
        )
        history = cursor.fetchall()
        assert len(history) == 1
        assert history[0]["version_number"] == 1


# ============================================================================
# SCENARIO 16 — FTS5 INDEX REBUILD
# ============================================================================
def test_scenario_16_fts5_index_rebuild(eng):
    session_id = uuid.uuid4()
    for i in range(5):
        eng.submit_experience(
            source_engine="PERCEPTION",
            channel="TEXT",
            raw_content=f"FTS5 rebuild test record number {i}.",
            session_id=session_id,
        )
    eng.worker.process_all_pending()

    # Verify FTS5 works
    res_before = eng.retrieve("rebuild test record", requesting_engine="THOUGHT")
    assert len(res_before) > 0

    # Simulate index corruption / drop
    with eng.factory.write_transaction() as cursor:
        cursor.execute("DROP TABLE memories_fts;")

    # SQL retrieval still continues to function (graceful fallback)
    res_fallback = eng.retrieve("rebuild test record", requesting_engine="THOUGHT")
    assert isinstance(res_fallback, list)

    # Rebuild FTS5 table
    with eng.factory.write_transaction() as cursor:
        cursor.execute(
            """
            CREATE VIRTUAL TABLE memories_fts USING fts5(
                memory_id UNINDEXED,
                experience_summary,
                canonical_statements,
                entity_names,
                tokenize = 'porter unicode61'
            );
            """
        )
        # Re-populate from experiences table (source-of-truth columns)
        cursor.execute(
            """
            INSERT INTO memories_fts (memory_id, experience_summary, canonical_statements, entity_names)
            SELECT experience_id, experience_summary, '', '' FROM experiences;
            """
        )

    # Post-rebuild query works identically
    res_after = eng.retrieve("rebuild test record", requesting_engine="THOUGHT")
    assert len(res_after) > 0


# ============================================================================
# SCENARIO 17 — DEVELOPMENT PRIORITY CALCULATION
# ============================================================================
def test_scenario_17_development_priority_calculation():
    calc = MemoryDevelopmentService.calculate_development_priority

    # Memory A: I_perm=0.9, recurrence=5, uncertainty=0.1, dependency=0.2
    # P_dev(A) = 0.4(0.9) + 0.2(0.5) + 0.2(0.1) + 0.2(0.2) = 0.36 + 0.10 + 0.02 + 0.04 = 0.52
    p_a = calc(permanent_importance=0.9, recurrence=5.0, uncertainty=0.1, dependency=0.2)
    assert p_a == 0.52

    # Memory B: I_perm=0.3, recurrence=8, uncertainty=0.9, dependency=0.1
    # P_dev(B) = 0.4(0.3) + 0.2(0.8) + 0.2(0.9) + 0.2(0.1) = 0.12 + 0.16 + 0.18 + 0.02 = 0.48
    p_b = calc(permanent_importance=0.3, recurrence=8.0, uncertainty=0.9, dependency=0.1)
    assert p_b == 0.48

    # Memory C: I_perm=0.5, recurrence=2, uncertainty=0.5, dependency=0.8
    # P_dev(C) = 0.4(0.5) + 0.2(0.2) + 0.2(0.5) + 0.2(0.8) = 0.20 + 0.04 + 0.10 + 0.16 = 0.50
    p_c = calc(permanent_importance=0.5, recurrence=2.0, uncertainty=0.5, dependency=0.8)
    assert p_c == 0.50

    # Development priority order: A (0.52) > C (0.50) > B (0.48)
    assert p_a > p_c > p_b


# ============================================================================
# SCENARIO 18 — ARCHIVAL ELIGIBILITY ENFORCEMENT
# ============================================================================
def test_scenario_18_archival_eligibility_enforcement(eng, tmp_path):
    session_id = uuid.uuid4()
    _, m1_id, _ = eng.submit_experience(
        source_engine="PERCEPTION",
        channel="TEXT",
        raw_content="Archival eligibility candidate.",
        session_id=session_id,
    )
    assert m1_id is not None

    # Mark consolidated
    with eng.factory.write_transaction() as cursor:
        cursor.execute(
            "UPDATE experiences SET retention_status = 'CONSOLIDATED' WHERE experience_id = ?;",
            (str(m1_id),),
        )

    # 1. Add active dependency: cannot be archived (MEM-010-A)
    dep_claim_id = uuid.uuid4()
    eng.retention.add_dependency(
        dependent_id=dep_claim_id,
        source_id=m1_id,
    )

    from memory_engine.consolidation.retention import DependencyLockedError

    with pytest.raises(DependencyLockedError):
        eng.retention.archive_memory(m1_id, archive_dir=tmp_path / "archive")

    # 2. Release dependency by removing from memory_dependencies table, then archive
    with eng.factory.write_transaction() as cursor:
        cursor.execute(
            "DELETE FROM memory_dependencies WHERE source_id = ? AND dependent_id = ?;",
            (str(m1_id), str(dep_claim_id)),
        )
        # Reset retention_records dependency count
        cursor.execute(
            "UPDATE retention_records SET dependency_count = 0, archival_eligible = 1 WHERE memory_id = ?;",
            (str(m1_id),),
        )

    archive_id = eng.retention.archive_memory(m1_id, archive_dir=tmp_path / "archive")
    assert archive_id is not None

    # Restoration recovers content with checksum verification
    payload_bytes = eng.retention.restore_archived_memory(m1_id)
    assert payload_bytes is not None
    assert b"Archival eligibility candidate" in payload_bytes


# ============================================================================
# SCENARIO 19 — BITEMPORAL QUERY CORRECTNESS
# ============================================================================
def test_scenario_19_bitemporal_query_correctness(eng):
    session_id = uuid.uuid4()
    alex = eng.create_or_get_entity("Alex Historical", EntityType.PERSON)

    # Jan 1: Recorded that Alex works at Acme Corp
    c1 = eng.store_claim(
        proposal=ProposedClaim(
            subject_entity_id=alex.entity_id,
            predicate="company",
            object_value="Acme Corp",
            canonical_statement="Alex works at Acme Corp.",
            epistemic_type=EpistemicType.OBSERVATION,
            source_engine="PERCEPTION",
        ),
        session_id=session_id,
        world_time_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        world_time_end=datetime(2026, 7, 31, tzinfo=timezone.utc),
    )

    # Aug 1: Correction recorded: Alex now works at Globex
    c2, _ = eng.knowledge.supersede_claim(
        original_claim_id=c1.claim_id,
        new_proposal=ProposedClaim(
            subject_entity_id=alex.entity_id,
            predicate="company",
            object_value="Globex",
            canonical_statement="Alex works at Globex.",
            epistemic_type=EpistemicType.OBSERVATION,
            source_engine="PERCEPTION",
        ),
        session_id=session_id,
        domain_partition=DomainPartition.COGNITIVE,
        world_time_start=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )

    # Query A: June world-time returns Acme Corp
    res_june = eng.knowledge.query_bitemporal_world_time(
        world_target_time=datetime(2026, 6, 1, tzinfo=timezone.utc),
        subject_entity_id=alex.entity_id,
    )
    assert len(res_june) == 1
    assert res_june[0].object_value == "Acme Corp"

    # Query C: Current active claim returns Globex
    curr = eng.knowledge.get_claim(c2.claim_id)
    assert curr.lifecycle.value == "ACTIVE"
    assert curr.object_value == "Globex"


# ============================================================================
# SCENARIO 20 — FULL HYBRID DEVELOPMENT CYCLE
# ============================================================================
def test_scenario_20_full_hybrid_development_cycle(eng):
    session_id = uuid.uuid4()
    exp_ids = []

    # 1. 10 experiences involving debugging and async errors
    for i in range(10):
        _, eid, _ = eng.submit_experience(
            source_engine="PERCEPTION",
            channel="TEXT",
            raw_content=f"Diva debugging async errors in subsystem {i}.",
            session_id=session_id,
        )
        exp_ids.append(eid)
    assert len(exp_ids) == 10

    # 2. Pattern detection creates DevelopmentRequest -> Thought Engine
    req = eng.development.request_development(
        operation_type=DevelopmentOperationType.CAUSAL_INVESTIGATION,
        development_objective="Investigate async debugging pattern",
        target_memory_ids=exp_ids,
        target_engine="THOUGHT",
    )
    assert req is not None

    # 3. Thought Engine submits hypothesis claim via submit_development_proposal
    proposal_id_1 = eng.development.submit_development_proposal(
        request_id=req.request_id,
        originating_engine="THOUGHT",
        proposed_claims=[
            ProposedClaim(
                predicate="root_cause",
                object_value="concurrency_race",
                canonical_statement="Async errors likely caused by concurrency race.",
                epistemic_type=EpistemicType.INFERENCE,
                source_engine="THOUGHT",
            )
        ],
        supporting_evidence_ids=[eid for eid in exp_ids],
        rationale="Pattern of repeated async failures across subsystems.",
    )

    # 4. Memory Governance reviews and accepts proposal 1
    claims_1 = eng.development.review_development_proposal(
        proposal_id=proposal_id_1,
        decision="ACCEPT",
        reviewing_engine="MEMORY_GOVERNANCE",
        session_id=session_id,
    )
    assert len(claims_1) == 1
    assert claims_1[0].epistemic_type == EpistemicType.INFERENCE

    # 5. Learning Engine creates its own DevelopmentRequest and submits lesson
    req2 = eng.development.request_development(
        operation_type=DevelopmentOperationType.PROCEDURAL_EXTRACTION,
        development_objective="Extract procedural debugging lesson",
        target_memory_ids=exp_ids,
        target_engine="LEARNING",
    )
    proposal_id_2 = eng.development.submit_development_proposal(
        request_id=req2.request_id,
        originating_engine="LEARNING",
        proposed_claims=[
            ProposedClaim(
                predicate="debugging_protocol",
                object_value="use_mutex",
                canonical_statement="Always serialize writer transactions with mutex.",
                epistemic_type=EpistemicType.INFERENCE,
                source_engine="LEARNING",
            )
        ],
        supporting_evidence_ids=[eid for eid in exp_ids],
        rationale="Common debugging pattern requiring mutex-based serialization.",
    )
    claims_2 = eng.development.review_development_proposal(
        proposal_id=proposal_id_2,
        decision="ACCEPT",
        reviewing_engine="MEMORY_GOVERNANCE",
        session_id=session_id,
    )
    assert len(claims_2) == 1

    # 6. Seven-gate consolidation
    ok, rep_id, audit = eng.consolidate_memories(
        source_memory_ids=exp_ids,
        summary="Comprehensive summary of async debugging lessons.",
        claims=[
            {"predicate": "root_cause", "object_value": "concurrency_race", "epistemic_type": "INFERENCE"},
            {"predicate": "debugging_protocol", "object_value": "use_mutex", "epistemic_type": "INFERENCE"},
        ],
    )
    assert ok
    assert rep_id is not None
    assert audit["all_gates_passed"] is True
