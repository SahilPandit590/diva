"""
Unit tests for Memory Development Engine, FSM state transitions,
bounded anti-recursion (MEM-012), pattern detection, and collaborative workflow.
"""

import uuid
import pytest
from memory_engine.database.connection import DatabaseConnectionFactory
from memory_engine.database.migrations import MigrationRunner
from memory_engine.development.bounded_runner import (
    BoundedDevelopmentRunner,
    DevelopmentDepthExceededError,
    DevelopmentRateLimitError,
)
from memory_engine.development.lifecycle import (
    DevelopmentFSM,
    InvalidStateTransitionError,
)
from memory_engine.development.patterns import PatternDetector
from memory_engine.development.service import MemoryDevelopmentService
from memory_engine.entities.service import EntityAssociationService
from memory_engine.governance.service import MemoryGovernanceService
from memory_engine.knowledge.store import KnowledgeStoreService
from memory_engine.types.claim import ProposedClaim
from memory_engine.types.enums import (
    DevelopmentOperationType,
    DevelopmentStatus,
    DomainPartition,
    EntityType,
    EpistemicType,
)


@pytest.fixture
def dev_stack():
    factory = DatabaseConnectionFactory(":memory:")
    runner = MigrationRunner(factory)
    runner.apply_migrations()
    governance = MemoryGovernanceService(factory)
    knowledge = KnowledgeStoreService(factory, governance)
    entities = EntityAssociationService(factory, governance)
    patterns = PatternDetector(factory, entities)
    service = MemoryDevelopmentService(factory, governance, knowledge, patterns)
    yield service, factory, entities, patterns
    factory.close()


def test_fsm_valid_and_invalid_transitions():
    """Verifies DevelopmentStatus FSM rules (Section 3.9)."""
    # Valid transition chain
    assert DevelopmentFSM.can_transition(DevelopmentStatus.RAW, DevelopmentStatus.ORGANIZED)
    assert DevelopmentFSM.can_transition(DevelopmentStatus.ORGANIZED, DevelopmentStatus.ASSOCIATED)
    assert DevelopmentFSM.can_transition(DevelopmentStatus.ASSOCIATED, DevelopmentStatus.PROPOSED)
    assert DevelopmentFSM.can_transition(DevelopmentStatus.PROPOSED, DevelopmentStatus.UNDER_REVIEW)
    assert DevelopmentFSM.can_transition(DevelopmentStatus.UNDER_REVIEW, DevelopmentStatus.ACCEPTED)
    assert DevelopmentFSM.can_transition(DevelopmentStatus.ACCEPTED, DevelopmentStatus.SUPERSEDED)

    # Invalid transitions
    assert not DevelopmentFSM.can_transition(DevelopmentStatus.RAW, DevelopmentStatus.ACCEPTED)
    assert not DevelopmentFSM.can_transition(DevelopmentStatus.RAW, DevelopmentStatus.SUPERSEDED)

    with pytest.raises(InvalidStateTransitionError):
        DevelopmentFSM.validate_transition(DevelopmentStatus.RAW, DevelopmentStatus.ACCEPTED)


def test_bounded_development_depth_capping_mem012(dev_stack):
    """Verifies MEM-012: Recursion depth hard cap prevents infinite loops."""
    service, _, _, _ = dev_stack

    # Allowed depth
    req = service.request_development(
        operation_type=DevelopmentOperationType.GENERALIZATION,
        development_objective="Generalize recurring topic patterns",
        current_depth=3,
        max_processing_depth=5,
    )
    assert req.processing_depth == 3

    # Exceeded depth
    with pytest.raises(DevelopmentDepthExceededError):
        service.request_development(
            operation_type=DevelopmentOperationType.GENERALIZATION,
            development_objective="Excessive recursion attempt",
            current_depth=5,
            max_processing_depth=5,
        )


def test_circuit_breaker_rate_limiting(dev_stack):
    """Verifies circuit breaker suppresses requests after 5 attempts on same target in 24h."""
    service, _, _, _ = dev_stack
    target_id = uuid.uuid4()

    # Submit 5 requests for the exact same target
    for i in range(5):
        service.request_development(
            operation_type=DevelopmentOperationType.PATTERN_DETECTION,
            development_objective=f"Investigation attempt {i}",
            target_memory_ids=[target_id],
        )

    # 6th request triggers circuit breaker
    with pytest.raises(DevelopmentRateLimitError):
        service.request_development(
            operation_type=DevelopmentOperationType.PATTERN_DETECTION,
            development_objective="6th attempt",
            target_memory_ids=[target_id],
        )


def test_collaborative_development_workflow(dev_stack):
    """
    Tests Kind B and Kind C collaborative workflow:
      1. Memory initiates DevelopmentRequest
      2. Specialized engine submits DevelopmentProposal
      3. Governance accepts proposal and assigns permanent UUIDs
    """
    service, factory, entities, _ = dev_stack
    session_id = uuid.uuid4()
    entity = entities.create_or_get_entity("Nova System", EntityType.SYSTEM)

    # 1. Request
    request = service.request_development(
        operation_type=DevelopmentOperationType.CAUSAL_INVESTIGATION,
        development_objective="Investigate why Nova latency increased",
        requesting_engine="THOUGHT",
    )
    assert request.request_id is not None

    # 2. Proposal from Thought Engine
    proposed_claim = ProposedClaim(
        subject_entity_id=entity.entity_id,
        predicate="bottleneck_cause",
        object_value="High Disk I/O",
        canonical_statement="Nova latency bottleneck caused by High Disk I/O.",
        epistemic_type=EpistemicType.INFERENCE,
        source_engine="THOUGHT",
    )
    proposal_id = service.submit_development_proposal(
        request_id=request.request_id,
        originating_engine="THOUGHT",
        proposed_claims=[proposed_claim],
        rationale="Correlated telemetry metrics with disk queue saturation",
    )
    assert proposal_id is not None

    # 3. Governance Review: ACCEPT
    created_claims = service.review_development_proposal(
        proposal_id=proposal_id,
        decision="ACCEPT",
        reviewing_engine="MEMORY_GOVERNANCE",
        session_id=session_id,
        domain_partition=DomainPartition.COGNITIVE,
    )
    assert len(created_claims) == 1
    assert created_claims[0].predicate == "bottleneck_cause"
    assert created_claims[0].object_value == "High Disk I/O"

    # Verify persistent claim was created with valid UUID
    with factory.read_cursor() as cursor:
        cursor.execute("SELECT lifecycle, epistemic_type FROM claims WHERE claim_id = ?;", (str(created_claims[0].claim_id),))
        row = cursor.fetchone()
        assert row is not None
        assert row["lifecycle"] == "ACTIVE"
        assert row["epistemic_type"] == "INFERENCE"
