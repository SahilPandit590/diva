"""
End-to-end integration and architectural invariant verification for Diva Memory Engine v3.0.
Verifies MEM-001 through MEM-015, retrieval cascade, continuity checkpoints, and consolidation.
"""

import uuid
from datetime import datetime, timezone
import pytest

from memory_engine import (
    DomainPartition,
    EntityType,
    EpistemicType,
    EvidenceRole,
    EvidenceStatus,
    MemoryEngine,
    ProposedClaim,
)


@pytest.fixture
def engine():
    eng = MemoryEngine(":memory:")
    yield eng
    eng.close()


def test_full_memory_engine_workflow(engine):
    """
    Tests the complete unified workflow:
      1. Submit experiences
      2. Resolve entities & aliases
      3. Store propositions & add evidence
      4. Multi-layer retrieval cascade
      5. Seven-gate consolidation
      6. Continuity checkpointing & restore
      7. Outbox event processing
    """
    session_id = uuid.uuid4()

    # Step 1: Ingest experience 1
    ev1, exp1, is_dup1 = engine.submit_experience(
        source_engine="PERCEPTION",
        channel="TEXT",
        raw_content="User introduced themselves as Dr. Evelyn Vance, a leading quantum researcher.",
        session_id=session_id,
        domain_partition=DomainPartition.COGNITIVE,
        importance_flag=True,
    )
    assert not is_dup1
    assert exp1 is not None

    # Step 2: Ingest experience 2
    ev2, exp2, is_dup2 = engine.submit_experience(
        source_engine="PERCEPTION",
        channel="TEXT",
        raw_content="Dr. Evelyn mentioned she is actively collaborating on quantum error correction.",
        session_id=session_id,
        domain_partition=DomainPartition.COGNITIVE,
        importance_flag=True,
    )
    assert not is_dup2
    assert exp2 is not None

    # Step 3: Entity creation and alias resolution
    evelyn = engine.create_or_get_entity(
        canonical_name="Dr. Evelyn Vance",
        entity_type=EntityType.PERSON,
        domain_partition=DomainPartition.COGNITIVE,
        aliases=["Evelyn", "Dr. Vance"],
        source_engine="PERCEPTION",
    )
    assert evelyn.canonical_name == "Dr. Evelyn Vance"

    # Alias resolution
    resolved = engine.resolve_entity("Dr. Vance", DomainPartition.COGNITIVE)
    assert resolved is not None
    assert resolved.entity_id == evelyn.entity_id

    # Step 4: Store claims
    c1 = engine.store_claim(
        proposal=ProposedClaim(
            subject_entity_id=evelyn.entity_id,
            predicate="field_of_study",
            object_value="Quantum Physics",
            canonical_statement="Dr. Evelyn Vance specializes in Quantum Physics.",
            epistemic_type=EpistemicType.OBSERVATION,
            source_engine="PERCEPTION",
        ),
        session_id=session_id,
        domain_partition=DomainPartition.COGNITIVE,
        source_experience_id=exp1,
    )
    assert c1.evidence_status == EvidenceStatus.UNVERIFIED

    # Add supporting evidence
    c2_support = engine.store_claim(
        proposal=ProposedClaim(
            subject_entity_id=evelyn.entity_id,
            predicate="observed_collaboration",
            object_value="Quantum Error Correction",
            canonical_statement="Paper co-authorship in quantum error correction.",
            epistemic_type=EpistemicType.OBSERVATION,
            source_engine="PERCEPTION",
        ),
        session_id=session_id,
        domain_partition=DomainPartition.COGNITIVE,
        source_experience_id=exp2,
    )

    engine.add_evidence(
        claim_id=c1.claim_id,
        relationship=EvidenceRole.SUPPORTS,
        weight=1.0,
        source_claim_id=c2_support.claim_id,
    )
    c1_updated = engine.knowledge.get_claim(c1.claim_id)
    assert c1_updated.evidence_status == EvidenceStatus.SUPPORTED

    # Step 5: Multi-layer retrieval cascade
    results = engine.retrieve(
        query_text="quantum researcher",
        requesting_engine="THOUGHT",
        domain_partition=DomainPartition.COGNITIVE,
        session_id=session_id,
        limit=5,
    )
    assert len(results) >= 2
    assert any("Evelyn" in r["summary"] for r in results)

    # Step 6: Seven-gate consolidation
    passed, repr_id, gate_results = engine.consolidate_memories(
        source_memory_ids=[exp1, exp2],
        summary="Dr. Evelyn Vance is a quantum researcher working on error correction.",
        claims=[{"statement": "Specializes in Quantum Physics"}],
        domain_partition=DomainPartition.COGNITIVE,
        initiating_engine="MEMORY_GOVERNANCE",
    )
    assert passed
    assert repr_id is not None
    assert all(gate_results.values())

    # Step 7: Continuity checkpoint & restore
    checkpoint = engine.create_checkpoint(
        session_id=session_id,
        domain_partition=DomainPartition.COGNITIVE,
        workspace_snapshot_ref=uuid.uuid4(),
        attention_snapshot_ref=uuid.uuid4(),
        requesting_engine="COGNITIVE_INTEGRATION",
    )
    assert checkpoint.valid
    assert not checkpoint.restoration_attempted

    restored = engine.restore_checkpoint(
        session_id=session_id,
        domain_partition=DomainPartition.COGNITIVE,
        requesting_engine="COGNITIVE_INTEGRATION",
    )
    assert restored is not None
    assert restored.checkpoint_id == checkpoint.checkpoint_id
    assert restored.restoration_attempted
    assert restored.restoration_succeeded

    # Step 8: Outbox worker event processing
    events_dispatched = []

    def on_event(name, payload):
        events_dispatched.append(name)

    engine.outbox.subscribe("memory.experience_persisted", on_event)
    engine.outbox.subscribe("memory.claim_created", on_event)
    engine.outbox.subscribe("memory.consolidation_completed", on_event)
    engine.outbox.subscribe("memory.checkpoint_created", on_event)

    published = engine.outbox.process_pending_events()
    assert published >= 4
    assert "memory.experience_persisted" in events_dispatched
    assert "memory.claim_created" in events_dispatched
    assert "memory.consolidation_completed" in events_dispatched
    assert "memory.checkpoint_created" in events_dispatched
