"""
Part 9.2 — End-to-End Verification Scenarios 01 through 10.
Implements the exact end-to-end specifications from memory_implementation_plan.txt.
"""

import json
import uuid
from datetime import datetime, timezone
import pytest

from memory_engine.development.bounded_runner import (
    DevelopmentDepthExceededError,
)
from memory_engine.engine import MemoryEngine
from memory_engine.governance.exceptions import (
    EpistemicDowngradeError,
    MemoryAccessDeniedError,
)
from memory_engine.retrieval.intent_router import RetrievalIntent
from memory_engine.types.claim import ProposedClaim, ProposedRelationship
from memory_engine.types.development import DevelopmentResult
from memory_engine.types.enums import (
    AccessAction,
    ClaimLifecycle,
    DevelopmentOperationType,
    DevelopmentResultStatus,
    DomainPartition,
    EntityType,
    EpistemicType,
    EvidenceRole,
    EvidenceStatus,
    MemoryRelationshipType,
)


@pytest.fixture
def eng():
    e = MemoryEngine(db_path=":memory:")
    yield e
    e.close()


# ============================================================================
# SCENARIO 01 — BASIC EXPERIENCE INTAKE AND RETRIEVAL
# ============================================================================
def test_scenario_01_basic_experience_intake_and_retrieval(eng):
    session_id = uuid.uuid4()

    # Step 1 & 2: Perception Engine submits text
    _, exp_id, is_dup = eng.submit_experience(
        source_engine="PERCEPTION",
        channel="TEXT",
        raw_content="Alex cancelled the meeting.",
        session_id=session_id,
        domain_partition=DomainPartition.COGNITIVE,
        explicit_epistemic=EpistemicType.OBSERVATION,
    )
    assert not is_dup
    assert exp_id is not None

    # Step 3: Entity extractor creates entity ENT-001 (Alex)
    alex_entity = eng.create_or_get_entity(
        canonical_name="Alex",
        entity_type=EntityType.PERSON,
        domain_partition=DomainPartition.COGNITIVE,
        source_engine="PERCEPTION",
    )

    # Step 4: Claim extracted: subject=Alex, predicate="cancelled", object="meeting"
    claim = eng.store_claim(
        proposal=ProposedClaim(
            subject_entity_id=alex_entity.entity_id,
            predicate="cancelled",
            object_value="meeting",
            canonical_statement="Alex cancelled the meeting.",
            epistemic_type=EpistemicType.OBSERVATION,
            source_engine="PERCEPTION",
        ),
        session_id=session_id,
        domain_partition=DomainPartition.COGNITIVE,
        source_experience_id=exp_id,
    )
    assert claim.epistemic_type == EpistemicType.OBSERVATION
    assert claim.evidence_status == EvidenceStatus.UNVERIFIED

    # Step 5: Background job worker runs FTS5 indexing
    eng.worker.process_all_pending()

    # Step 6: Thought Engine queries retrieve_memories
    results = eng.retrieve(
        query_text="meeting cancellation",
        requesting_engine="THOUGHT",
        domain_partition=DomainPartition.COGNITIVE,
        session_id=session_id,
        intent=RetrievalIntent.GENERAL,
    )
    assert len(results) > 0
    top = results[0]
    assert top["memory_id"] == str(exp_id)
    assert top["score"] > 0.1  # S_unified > threshold

    # Verify retrieval_events log entry exists
    with eng.factory.read_cursor() as cursor:
        cursor.execute(
            "SELECT * FROM retrieval_events WHERE requesting_engine = 'THOUGHT';"
        )
        r_row = cursor.fetchone()
        assert r_row is not None
        assert r_row["query_text"] == "meeting cancellation"

        # Verify audit_events read entry exists
        cursor.execute(
            """
            SELECT * FROM audit_events 
            WHERE actor_engine = 'THOUGHT' AND event_type = 'ACCESS_GRANTED';
            """
        )
        a_row = cursor.fetchone()
        assert a_row is not None


# ============================================================================
# SCENARIO 02 — EPISTEMIC TYPE PRESERVATION ACROSS ENGINES
# ============================================================================
def test_scenario_02_epistemic_type_preservation_across_engines(eng):
    session_id = uuid.uuid4()

    # Step 1 & 2: Perception submits INTERPRETATION
    _, exp_id, _ = eng.submit_experience(
        source_engine="PERCEPTION",
        channel="TEXT",
        raw_content="User seems disappointed.",
        session_id=session_id,
        explicit_epistemic=EpistemicType.INTERPRETATION,
    )
    c1 = eng.store_claim(
        proposal=ProposedClaim(
            predicate="emotional_state",
            object_value="disappointed",
            canonical_statement="User seems disappointed.",
            epistemic_type=EpistemicType.INTERPRETATION,
            source_engine="PERCEPTION",
        ),
        session_id=session_id,
        source_experience_id=exp_id,
    )
    assert c1.epistemic_type == EpistemicType.INTERPRETATION  # MEM-003-A

    # Step 3 & 4: Social Cognition submits DevelopmentProposal with INTERPRETATION
    req = eng.development.request_development(
        operation_type=DevelopmentOperationType.EMOTIONAL_REAPPRAISAL,
        development_objective="Appraise user emotion",
        requesting_engine="SOCIAL_COGNITION",
        target_memory_ids=[exp_id],
    )
    p_id = eng.development.submit_development_proposal(
        request_id=req.request_id,
        originating_engine="SOCIAL_COGNITION",
        proposed_claims=[
            ProposedClaim(
                predicate="expressed_emotion",
                object_value="disappointment",
                canonical_statement="User expressed disappointment.",
                epistemic_type=EpistemicType.INTERPRETATION,
                source_engine="SOCIAL_COGNITION",
            )
        ],
        supporting_evidence_ids=[exp_id],
        rationale="Social appraisal",
    )
    accepted_claims = eng.development.review_development_proposal(
        proposal_id=p_id,
        decision="ACCEPT",
        reviewing_engine="MEMORY_GOVERNANCE",
        session_id=session_id,
    )
    assert len(accepted_claims) == 1
    assert accepted_claims[0].epistemic_type == EpistemicType.INTERPRETATION

    # Step 5: Social Cognition attempts to submit claim with epistemic_type=OBSERVATION (FORBIDDEN)
    req_inv = eng.development.request_development(
        operation_type=DevelopmentOperationType.EMOTIONAL_REAPPRAISAL,
        development_objective="Appraise user emotion invalid",
        requesting_engine="SOCIAL_COGNITION",
        target_memory_ids=[exp_id],
    )
    p_invalid_id = eng.development.submit_development_proposal(
        request_id=req_inv.request_id,
        originating_engine="SOCIAL_COGNITION",
        proposed_claims=[
            ProposedClaim(
                predicate="expressed_emotion",
                object_value="disappointment",
                canonical_statement="User expressed disappointment (elevated).",
                epistemic_type=EpistemicType.OBSERVATION,  # Unauthorized elevation!
                source_engine="SOCIAL_COGNITION",
            )
        ],
        supporting_evidence_ids=[exp_id],
        rationale="Invalid elevation",
    )
    with pytest.raises(EpistemicDowngradeError):
        eng.development.review_development_proposal(
            proposal_id=p_invalid_id,
            decision="ACCEPT",
            reviewing_engine="MEMORY_GOVERNANCE",
            session_id=session_id,
        )


# ============================================================================
# SCENARIO 03 — CONTRADICTION DETECTION AND DISPUTE MARKING
# ============================================================================
def test_scenario_03_contradiction_detection_and_dispute_marking(eng):
    session_id = uuid.uuid4()
    entity = eng.create_or_get_entity("Alex", EntityType.PERSON)

    t1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    t2 = datetime(2026, 6, 1, tzinfo=timezone.utc)

    # Claim C1: Alex works at Company A (Jan 1 -> Jun 1)
    c1 = eng.store_claim(
        proposal=ProposedClaim(
            subject_entity_id=entity.entity_id,
            predicate="works_at",
            object_value="Company A",
            canonical_statement="Alex works at Company A.",
            epistemic_type=EpistemicType.REPORTED,
            source_engine="USER",
        ),
        session_id=session_id,
        world_time_start=t1,
        world_time_end=t2,
    )

    # Claim C2: Alex works at Company B (overlapping range Jan 1 -> Jun 1)
    c2 = eng.store_claim(
        proposal=ProposedClaim(
            subject_entity_id=entity.entity_id,
            predicate="works_at",
            object_value="Company B",
            canonical_statement="Alex works at Company B.",
            epistemic_type=EpistemicType.REPORTED,
            source_engine="USER",
        ),
        session_id=session_id,
        world_time_start=t1,
        world_time_end=t2,
    )

    # Expected Outcomes:
    # 1. Contradiction link created
    with eng.factory.read_cursor() as cursor:
        cursor.execute(
            """
            SELECT relationship_type FROM claim_relationships
            WHERE (claim_id_source = ? AND claim_id_target = ?)
               OR (claim_id_source = ? AND claim_id_target = ?);
            """,
            (str(c1.claim_id), str(c2.claim_id), str(c2.claim_id), str(c1.claim_id)),
        )
        row = cursor.fetchone()
        assert row is not None
        assert row["relationship_type"] == "CONTRADICTS"

    # 2. Both marked DISPUTED
    c1_refreshed = eng.knowledge.get_claim(c1.claim_id)
    c2_refreshed = eng.knowledge.get_claim(c2.claim_id)
    assert c1_refreshed.evidence_status == EvidenceStatus.DISPUTED
    assert c2_refreshed.evidence_status == EvidenceStatus.DISPUTED

    # 3. Outbox event emitted
    with eng.factory.read_cursor() as cursor:
        cursor.execute("SELECT * FROM outbox_events WHERE event_name = 'memory.claim_created';")
        assert len(cursor.fetchall()) >= 2


# ============================================================================
# SCENARIO 04 — CLAIM CORRECTION AND VERSION HISTORY
# ============================================================================
def test_scenario_04_claim_correction_and_version_history(eng):
    session_id = uuid.uuid4()
    entity = eng.create_or_get_entity("Alex Career", EntityType.PERSON)

    _, exp_id, _ = eng.submit_experience(
        source_engine="PERCEPTION",
        channel="TEXT",
        raw_content="Alex works at Company A until June.",
        session_id=session_id,
    )

    # Claim C1: Alex works at Company A
    c1 = eng.store_claim(
        proposal=ProposedClaim(
            subject_entity_id=entity.entity_id,
            predicate="employer",
            object_value="Company A",
            canonical_statement="Alex works at Company A.",
            epistemic_type=EpistemicType.OBSERVATION,
            source_engine="PERCEPTION",
        ),
        session_id=session_id,
        source_experience_id=exp_id,
        world_time_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        world_time_end=datetime(2026, 6, 30, tzinfo=timezone.utc),
    )
    assert c1.lifecycle == ClaimLifecycle.ACTIVE

    # Claim C2 submitted as a correction to C1
    c2, updated_c1 = eng.knowledge.supersede_claim(
        original_claim_id=c1.claim_id,
        new_proposal=ProposedClaim(
            subject_entity_id=entity.entity_id,
            predicate="employer",
            object_value="Company B",
            canonical_statement="Alex works at Company B.",
            epistemic_type=EpistemicType.OBSERVATION,
            source_engine="PERCEPTION",
        ),
        session_id=session_id,
        domain_partition=DomainPartition.COGNITIVE,
        reason="Alex moved to Company B in July",
        world_time_start=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )

    # Outcomes:
    assert c2.lifecycle == ClaimLifecycle.ACTIVE
    assert updated_c1.lifecycle == ClaimLifecycle.SUPERSEDED

    # Query 6: June world_time query returns C1
    june_query = eng.knowledge.query_bitemporal_world_time(
        world_target_time=datetime(2026, 6, 15, tzinfo=timezone.utc),
        subject_entity_id=entity.entity_id,
    )
    assert len(june_query) == 1
    assert june_query[0].object_value == "Company A"

    # Query 7: August world_time query returns C2
    aug_query = eng.knowledge.query_bitemporal_world_time(
        world_target_time=datetime(2026, 8, 1, tzinfo=timezone.utc),
        subject_entity_id=entity.entity_id,
    )
    assert len(aug_query) == 1
    assert aug_query[0].object_value == "Company B"

    # Original experience record remains unchanged (MEM-006-B)
    exp_rec = eng.experience_store.get_experience(exp_id)
    assert exp_rec is not None
    assert exp_rec["experience_summary"] == "Alex works at Company A until June."


# ============================================================================
# SCENARIO 05 — COLLABORATIVE DEVELOPMENT CYCLE
# ============================================================================
def test_scenario_05_collaborative_development_cycle(eng):
    session_id = uuid.uuid4()
    alex = eng.create_or_get_entity("Alex Cancellations", EntityType.PERSON)

    # Create 3 experiences of Alex cancelling
    exp_ids = []
    for i in range(3):
        _, eid, _ = eng.submit_experience(
            source_engine="PERCEPTION",
            channel="TEXT",
            raw_content=f"Alex cancelled appointment number {i+1}.",
            session_id=session_id,
            participants=[alex.entity_id],
        )
        exp_ids.append(eid)

    # 1. Memory pattern detection / request creation
    req = eng.development.request_development(
        operation_type=DevelopmentOperationType.CAUSAL_INVESTIGATION,
        development_objective="Investigate co-occurrence of Alex and cancellations",
        target_memory_ids=exp_ids,
        target_engine="THOUGHT",
    )
    assert req is not None

    # 2. Thought Engine produces proposal
    prop_id = eng.development.submit_development_proposal(
        request_id=req.request_id,
        originating_engine="THOUGHT",
        proposed_claims=[
            ProposedClaim(
                subject_entity_id=alex.entity_id,
                predicate="behavior_pattern",
                object_value="avoids_commitments",
                canonical_statement="Alex may be avoiding commitments.",
                epistemic_type=EpistemicType.INTERPRETATION,
                source_engine="THOUGHT",
            )
        ],
        supporting_evidence_ids=exp_ids,
        rationale="Causal investigation",
    )

    # 3. Governance accepts and assigns UUIDs
    accepted_claims = eng.development.review_development_proposal(
        proposal_id=prop_id,
        decision="ACCEPT",
        reviewing_engine="MEMORY_GOVERNANCE",
        session_id=session_id,
    )
    assert len(accepted_claims) == 1
    new_claim = accepted_claims[0]
    assert new_claim.epistemic_type == EpistemicType.INTERPRETATION
    assert new_claim.evidence_status == EvidenceStatus.UNVERIFIED

    # Check derivation_links table
    with eng.factory.read_cursor() as cursor:
        cursor.execute(
            "SELECT * FROM derivation_links WHERE derived_id = ?;",
            (str(new_claim.claim_id),),
        )
        d_links = cursor.fetchall()
        assert len(d_links) == 3


# ============================================================================
# SCENARIO 06 — BOUNDED DEVELOPMENT DEPTH ENFORCEMENT
# ============================================================================
def test_scenario_06_bounded_development_depth_enforcement(eng):
    target_ids = [uuid.uuid4()]

    # Depths 0 through 4 should be accepted
    for d in range(5):
        req = eng.development.request_development(
            operation_type=DevelopmentOperationType.PATTERN_DETECTION,
            development_objective=f"Chain depth {d}",
            target_memory_ids=target_ids,
            processing_depth=d,
            max_processing_depth=5,
        )
        assert req.processing_depth == d

    # At depth 5 (meeting max_processing_depth=5), raising DevelopmentDepthExceededError (MEM-018-A)
    with pytest.raises(DevelopmentDepthExceededError):
        eng.development.request_development(
            operation_type=DevelopmentOperationType.PATTERN_DETECTION,
            development_objective="Chain depth 5 exceed",
            target_memory_ids=target_ids,
            processing_depth=5,
            max_processing_depth=5,
        )


# ============================================================================
# SCENARIO 07 — CONSOLIDATION WITH ALL SEVEN GATES
# ============================================================================
def test_scenario_07_consolidation_with_all_seven_gates(eng):
    session_id = uuid.uuid4()
    exp_ids = []
    for i in range(5):
        _, eid, _ = eng.submit_experience(
            source_engine="PERCEPTION",
            channel="TEXT",
            raw_content=f"Diva learning Python debugging step {i+1}.",
            session_id=session_id,
        )
        exp_ids.append(eid)

    claims = [
        {"predicate": "skill", "object_value": "Python debugging", "epistemic_type": "OBSERVATION"},
        {"predicate": "progress", "object_value": "step completed", "epistemic_type": "OBSERVATION"},
    ]

    success, rep_id, audit = eng.consolidate_memories(
        source_memory_ids=exp_ids,
        summary="Diva successfully learned Python debugging across 5 steps in November 2026.",
        claims=claims,
        initiating_engine="MEMORY_CONSOLIDATION",
    )
    assert success
    assert rep_id is not None
    assert audit.get("all_gates_passed") is True

    # Source experiences should now have retention_status = 'CONSOLIDATED'
    with eng.factory.read_cursor() as cursor:
        cursor.execute(
            "SELECT retention_status FROM experiences WHERE experience_id IN (?, ?, ?, ?, ?);",
            tuple(str(eid) for eid in exp_ids),
        )
        rows = cursor.fetchall()
        for r in rows:
            assert r["retention_status"] == "CONSOLIDATED"


# ============================================================================
# SCENARIO 08 — CONSOLIDATION GATE FAILURE (GATE 7 VIOLATION)
# ============================================================================
def test_scenario_08_consolidation_gate_failure(eng):
    session_id = uuid.uuid4()
    # Experience created with explicit INTERPRETATION
    _, eid, _ = eng.submit_experience(
        source_engine="PERCEPTION",
        channel="TEXT",
        raw_content="User sounded hesitant.",
        session_id=session_id,
        explicit_epistemic=EpistemicType.INTERPRETATION,
    )
    eng.store_claim(
        proposal=ProposedClaim(
            predicate="user_tone",
            object_value="hesitant",
            canonical_statement="User sounded hesitant.",
            epistemic_type=EpistemicType.INTERPRETATION,
            source_engine="PERCEPTION",
        ),
        session_id=session_id,
        source_experience_id=eid,
    )

    # Consolidated claims attempt to upgrade INTERPRETATION to OBSERVATION (Gate 7 fail)
    invalid_claims = [
        {"predicate": "user_tone", "object_value": "hesitant", "epistemic_type": "OBSERVATION"}
    ]

    success, rep_id, audit = eng.consolidate_memories(
        source_memory_ids=[eid],
        summary="Consolidation upgrading interpretation to observation.",
        claims=invalid_claims,
    )
    assert not success
    assert rep_id is None
    assert "Gate 7" in audit.get("reason", "")


# ============================================================================
# SCENARIO 09 — ZERO-LLM OPERATION VERIFICATION
# ============================================================================
def test_scenario_09_zero_llm_operation_verification(eng):
    # eng was initialized without embedding_provider or reasoning_provider
    session_id = uuid.uuid4()

    # Step 1: Submit 10 experiences
    exp_ids = []
    for i in range(10):
        _, eid, _ = eng.submit_experience(
            source_engine="PERCEPTION",
            channel="TEXT",
            raw_content=f"Zero-LLM deterministic operation test event number {i}.",
            session_id=session_id,
        )
        exp_ids.append(eid)
    assert len(exp_ids) == 10

    # Step 2: FTS5 keyword retrieval
    eng.worker.process_all_pending()
    fts_results = eng.retrieve("deterministic operation", requesting_engine="THOUGHT")
    assert len(fts_results) > 0

    # Step 3: SQL temporal query
    with eng.factory.read_cursor() as cursor:
        cursor.execute("SELECT count(*) as cnt FROM experiences;")
        assert cursor.fetchone()["cnt"] >= 10

    # Step 4: Spreading activation graph retrieval
    eng.activation.refresh_graph_projection()
    spread = eng.activation.spreading_activation(seed_memory_ids=[str(exp_ids[0])])
    assert isinstance(spread, dict)

    # Step 5: Contradiction detection
    entity = eng.create_or_get_entity("Deterministic Entity", EntityType.CONCEPT)
    c1 = eng.store_claim(
        ProposedClaim(
            subject_entity_id=entity.entity_id,
            predicate="state",
            object_value="ON",
            canonical_statement="State is ON.",
            epistemic_type=EpistemicType.OBSERVATION,
            source_engine="PERCEPTION",
        ),
        session_id=session_id,
    )
    c2 = eng.store_claim(
        ProposedClaim(
            subject_entity_id=entity.entity_id,
            predicate="state",
            object_value="OFF",
            canonical_statement="State is OFF.",
            epistemic_type=EpistemicType.OBSERVATION,
            source_engine="PERCEPTION",
        ),
        session_id=session_id,
    )
    assert eng.knowledge.get_claim(c1.claim_id).evidence_status == EvidenceStatus.DISPUTED

    # Step 6: Pattern detection (co-occurrence)
    co_occurs = eng.development.execute_independent_pattern_detection()
    assert isinstance(co_occurs, list)

    # Step 7: Consolidation cycle
    ok, _, _ = eng.consolidate_memories(
        source_memory_ids=exp_ids[:3],
        summary="Zero LLM batch consolidation",
        claims=[{"predicate": "mode", "object_value": "offline", "epistemic_type": "OBSERVATION"}],
    )
    assert ok

    # Step 8 & 9: Create and restore checkpoint
    cp = eng.create_checkpoint(session_id=session_id)
    assert cp is not None
    restored = eng.restore_checkpoint(session_id=session_id)
    assert restored is not None
    assert restored.checkpoint_id == cp.checkpoint_id


# ============================================================================
# SCENARIO 10 — CROSS-DOMAIN ACCESS DENIAL
# ============================================================================
def test_scenario_10_cross_domain_access_denial(eng):
    session_id = uuid.uuid4()

    # Step 1: AUTONOMOUS engine submits experience
    _, auto_exp_id, _ = eng.submit_experience(
        source_engine="AUTONOMOUS",
        channel="INTERNAL",
        raw_content="Autonomous background process telemetry.",
        session_id=session_id,
        domain_partition=DomainPartition.AUTONOMOUS,
    )
    assert auto_exp_id is not None

    # Step 2: COGNITIVE engine queries AUTONOMOUS partition directly -> Access denied
    with pytest.raises(MemoryAccessDeniedError):
        eng.retrieve(
            query_text="telemetry",
            requesting_engine="THOUGHT",  # Cognitive engine
            domain_partition=DomainPartition.AUTONOMOUS,  # Partition violation!
            session_id=session_id,
        )

    # Step 3: COGNITIVE engine attempts to write claim to AUTONOMOUS partition -> Access denied
    with pytest.raises(MemoryAccessDeniedError):
        eng.store_claim(
            proposal=ProposedClaim(
                predicate="rogue_write",
                object_value="illegal",
                canonical_statement="Illegal cross-domain write.",
                epistemic_type=EpistemicType.OBSERVATION,
                source_engine="THOUGHT",
            ),
            session_id=session_id,
            domain_partition=DomainPartition.AUTONOMOUS,
        )
