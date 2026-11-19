"""
Unit tests for KnowledgeStoreService, contradiction detection (MEM-005),
claim superseding (MEM-006), and bitemporal queries.
"""

import time
import uuid
from datetime import datetime, timedelta, timezone
import pytest
from memory_engine.database.connection import DatabaseConnectionFactory
from memory_engine.database.migrations import MigrationRunner
from memory_engine.entities.service import EntityAssociationService
from memory_engine.governance.service import MemoryGovernanceService
from memory_engine.knowledge.store import KnowledgeStoreService
from memory_engine.types.claim import ProposedClaim
from memory_engine.types.enums import (
    ClaimLifecycle,
    DomainPartition,
    EntityType,
    EpistemicType,
    EvidenceRole,
    EvidenceStatus,
)


@pytest.fixture
def knowledge_stack():
    factory = DatabaseConnectionFactory(":memory:")
    runner = MigrationRunner(factory)
    runner.apply_migrations()
    governance = MemoryGovernanceService(factory)
    entities = EntityAssociationService(factory, governance)
    service = KnowledgeStoreService(factory, governance)
    yield service, factory, entities
    factory.close()


def test_claim_creation_and_provenance_mem002(knowledge_stack):
    """Verifies MEM-002: Every persisted claim has source_engine and non-null provenance_hash."""
    service, factory, _ = knowledge_stack
    session_id = uuid.uuid4()
    proposal = ProposedClaim(
        predicate="resides_in",
        object_value="Tokyo",
        canonical_statement="User resides in Tokyo.",
        epistemic_type=EpistemicType.OBSERVATION,
        source_engine="PERCEPTION",
    )
    claim = service.create_claim(proposal, session_id, DomainPartition.COGNITIVE)

    assert claim.claim_id is not None
    assert claim.source_engine == "PERCEPTION"
    assert claim.provenance_hash is not None and len(claim.provenance_hash) == 64
    assert claim.evidence_status == EvidenceStatus.UNVERIFIED
    assert claim.lifecycle == ClaimLifecycle.ACTIVE

    # Check database row
    with factory.read_cursor() as cursor:
        cursor.execute("SELECT version, lifecycle FROM claims WHERE claim_id = ?;", (str(claim.claim_id),))
        row = cursor.fetchone()
        assert row["version"] == 1
        assert row["lifecycle"] == "ACTIVE"


def test_contradiction_detection_mem005(knowledge_stack):
    """Verifies MEM-005: Conflicting claims create CONTRADICTS link and are both marked DISPUTED."""
    service, factory, entities = knowledge_stack
    session_id = uuid.uuid4()
    entity = entities.create_or_get_entity("User Alice", EntityType.PERSON)
    entity_id = entity.entity_id

    # Claim 1: "User lives in New York"
    p1 = ProposedClaim(
        subject_entity_id=entity_id,
        predicate="current_city",
        object_value="New York",
        canonical_statement="User current city is New York.",
        epistemic_type=EpistemicType.REPORTED,
        source_engine="USER",
    )
    c1 = service.create_claim(p1, session_id, DomainPartition.COGNITIVE)
    assert c1.evidence_status == EvidenceStatus.UNVERIFIED

    # Claim 2: "User lives in London" (contradiction on same subject & predicate)
    p2 = ProposedClaim(
        subject_entity_id=entity_id,
        predicate="current_city",
        object_value="London",
        canonical_statement="User current city is London.",
        epistemic_type=EpistemicType.REPORTED,
        source_engine="USER",
    )
    c2 = service.create_claim(p2, session_id, DomainPartition.COGNITIVE)

    # Both claims should now be marked DISPUTED
    c1_updated = service.get_claim(c1.claim_id)
    c2_updated = service.get_claim(c2.claim_id)
    assert c1_updated.evidence_status == EvidenceStatus.DISPUTED
    assert c2_updated.evidence_status == EvidenceStatus.DISPUTED

    # Verify CONTRADICTS relationship exists in claim_relationships
    with factory.read_cursor() as cursor:
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


def test_claim_superseding_mem006(knowledge_stack):
    """
    Verifies MEM-006: Submitting a corrected claim creates SUPERSEDES relationship;
    original claim lifecycle -> SUPERSEDED; original content remains unchanged.
    """
    service, factory, entities = knowledge_stack
    session_id = uuid.uuid4()
    entity = entities.create_or_get_entity("User Bob", EntityType.PERSON)
    entity_id = entity.entity_id

    # Original claim
    orig_p = ProposedClaim(
        subject_entity_id=entity_id,
        predicate="job_title",
        object_value="Junior Engineer",
        canonical_statement="User is a Junior Engineer.",
        epistemic_type=EpistemicType.REPORTED,
        source_engine="USER",
    )
    orig_claim = service.create_claim(orig_p, session_id, DomainPartition.COGNITIVE)
    assert orig_claim.lifecycle == ClaimLifecycle.ACTIVE

    # Corrected claim
    corr_p = ProposedClaim(
        subject_entity_id=entity_id,
        predicate="job_title",
        object_value="Senior Engineer",
        canonical_statement="User is a Senior Engineer.",
        epistemic_type=EpistemicType.REPORTED,
        source_engine="USER",
    )
    new_claim, updated_orig = service.supersede_claim(
        original_claim_id=orig_claim.claim_id,
        new_proposal=corr_p,
        session_id=session_id,
        domain_partition=DomainPartition.COGNITIVE,
        reason="User was promoted to Senior Engineer",
    )

    # 1. New claim is ACTIVE
    assert new_claim.lifecycle == ClaimLifecycle.ACTIVE
    assert new_claim.canonical_statement == "User is a Senior Engineer."

    # 2. Original claim lifecycle is SUPERSEDED, but text is unchanged!
    assert updated_orig.lifecycle == ClaimLifecycle.SUPERSEDED
    assert updated_orig.canonical_statement == "User is a Junior Engineer."

    # 3. SUPERSEDES relationship exists
    with factory.read_cursor() as cursor:
        cursor.execute(
            """
            SELECT relationship_type FROM claim_relationships
            WHERE claim_id_source = ? AND claim_id_target = ?;
            """,
            (str(new_claim.claim_id), str(orig_claim.claim_id)),
        )
        rel = cursor.fetchone()
        assert rel is not None
        assert rel["relationship_type"] == "SUPERSEDES"


def test_evidence_recalculation(knowledge_stack):
    """Verifies that evidence status recalculates from UNVERIFIED -> SUPPORTED -> CORROBORATED -> DISPUTED."""
    service, factory, _ = knowledge_stack
    session_id = uuid.uuid4()

    claim = service.create_claim(
        ProposedClaim(
            predicate="status",
            object_value="active",
            canonical_statement="Project Alpha is active.",
            epistemic_type=EpistemicType.INFERENCE,
            source_engine="THOUGHT",
        ),
        session_id=session_id,
        domain_partition=DomainPartition.COGNITIVE,
    )
    assert claim.evidence_status == EvidenceStatus.UNVERIFIED

    # Create a source claim to act as valid evidence reference
    ev_claim1 = service.create_claim(
        ProposedClaim(
            predicate="evidence_fact_1",
            object_value="verified",
            canonical_statement="Observation 1 confirms status.",
            epistemic_type=EpistemicType.OBSERVATION,
            source_engine="PERCEPTION",
        ),
        session_id=session_id,
        domain_partition=DomainPartition.COGNITIVE,
    )
    ev_claim2 = service.create_claim(
        ProposedClaim(
            predicate="evidence_fact_2",
            object_value="verified",
            canonical_statement="Observation 2 confirms status.",
            epistemic_type=EpistemicType.OBSERVATION,
            source_engine="PERCEPTION",
        ),
        session_id=session_id,
        domain_partition=DomainPartition.COGNITIVE,
    )
    ev_claim3 = service.create_claim(
        ProposedClaim(
            predicate="evidence_fact_3",
            object_value="conflicting",
            canonical_statement="Observation 3 opposes status.",
            epistemic_type=EpistemicType.OBSERVATION,
            source_engine="PERCEPTION",
        ),
        session_id=session_id,
        domain_partition=DomainPartition.COGNITIVE,
    )

    # Add 1st supporting evidence
    service.add_evidence(
        claim.claim_id,
        EvidenceRole.SUPPORTS,
        weight=1.0,
        source_claim_id=ev_claim1.claim_id,
    )
    c_after1 = service.get_claim(claim.claim_id)
    assert c_after1.evidence_status == EvidenceStatus.SUPPORTED

    # Add 2nd supporting evidence -> CORROBORATED
    service.add_evidence(
        claim.claim_id,
        EvidenceRole.SUPPORTS,
        weight=1.0,
        source_claim_id=ev_claim2.claim_id,
    )
    c_after2 = service.get_claim(claim.claim_id)
    assert c_after2.evidence_status == EvidenceStatus.CORROBORATED

    # Add opposing evidence -> DISPUTED
    service.add_evidence(
        claim.claim_id,
        EvidenceRole.OPPOSES,
        weight=1.0,
        source_claim_id=ev_claim3.claim_id,
    )
    c_after3 = service.get_claim(claim.claim_id)
    assert c_after3.evidence_status == EvidenceStatus.DISPUTED


def test_bitemporal_world_time_query(knowledge_stack):
    """Verifies Query A: 'What was true in the world at time T?'"""
    service, _, entities = knowledge_stack
    session_id = uuid.uuid4()
    entity = entities.create_or_get_entity("Traveler", EntityType.PERSON)
    entity_id = entity.entity_id

    t1 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2025, 6, 1, 0, 0, tzinfo=timezone.utc)
    t3 = datetime(2025, 12, 1, 0, 0, tzinfo=timezone.utc)

    # Claim true from Jan 1 to June 1, 2025
    service.create_claim(
        ProposedClaim(
            subject_entity_id=entity_id,
            predicate="location",
            object_value="Paris",
            canonical_statement="User was in Paris.",
            epistemic_type=EpistemicType.OBSERVATION,
            source_engine="PERCEPTION",
        ),
        session_id=session_id,
        domain_partition=DomainPartition.COGNITIVE,
        world_time_start=t1,
        world_time_end=t2,
    )

    # Claim true from June 1, 2025 onward (end is None)
    service.create_claim(
        ProposedClaim(
            subject_entity_id=entity_id,
            predicate="location",
            object_value="Berlin",
            canonical_statement="User was in Berlin.",
            epistemic_type=EpistemicType.OBSERVATION,
            source_engine="PERCEPTION",
        ),
        session_id=session_id,
        domain_partition=DomainPartition.COGNITIVE,
        world_time_start=t2,
        world_time_end=None,
    )

    # Query at March 1, 2025: should return Paris only
    march_query = service.query_bitemporal_world_time(
        world_target_time=datetime(2025, 3, 1, tzinfo=timezone.utc),
        subject_entity_id=entity_id,
    )
    assert len(march_query) == 1
    assert march_query[0].object_value == "Paris"

    # Query at August 1, 2025: should return Berlin only
    august_query = service.query_bitemporal_world_time(
        world_target_time=datetime(2025, 8, 1, tzinfo=timezone.utc),
        subject_entity_id=entity_id,
    )
    assert len(august_query) == 1
    assert august_query[0].object_value == "Berlin"


def test_contradiction_temporal_non_overlap(knowledge_stack):
    """
    Section 3.2: Conflicting object_values for the same subject & predicate
    do NOT contradict if their world_time intervals do not overlap.
    """
    service, factory, entities = knowledge_stack
    session_id = uuid.uuid4()
    entity = entities.create_or_get_entity("Alice Historian", EntityType.PERSON)
    entity_id = entity.entity_id

    # 2020 - 2022: Alice lived in Boston
    c1 = service.create_claim(
        ProposedClaim(
            subject_entity_id=entity_id,
            predicate="city",
            object_value="Boston",
            canonical_statement="Alice lived in Boston.",
            epistemic_type=EpistemicType.OBSERVATION,
            source_engine="PERCEPTION",
        ),
        session_id=session_id,
        domain_partition=DomainPartition.COGNITIVE,
        world_time_start=datetime(2020, 1, 1, tzinfo=timezone.utc),
        world_time_end=datetime(2022, 12, 31, tzinfo=timezone.utc),
    )

    # 2023 - 2025: Alice lived in Seattle (no overlap with 2020-2022)
    c2 = service.create_claim(
        ProposedClaim(
            subject_entity_id=entity_id,
            predicate="city",
            object_value="Seattle",
            canonical_statement="Alice lived in Seattle.",
            epistemic_type=EpistemicType.OBSERVATION,
            source_engine="PERCEPTION",
        ),
        session_id=session_id,
        domain_partition=DomainPartition.COGNITIVE,
        world_time_start=datetime(2023, 1, 1, tzinfo=timezone.utc),
        world_time_end=datetime(2025, 12, 31, tzinfo=timezone.utc),
    )

    c1_refreshed = service.get_claim(c1.claim_id)
    c2_refreshed = service.get_claim(c2.claim_id)

    # Neither should be DISPUTED because time intervals do not overlap
    assert c1_refreshed.evidence_status != EvidenceStatus.DISPUTED
    assert c2_refreshed.evidence_status != EvidenceStatus.DISPUTED

