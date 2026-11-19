"""
Unit tests for Memory Governance, access policy enforcement, audit logging, and partition isolation.
"""

import uuid
import pytest
from memory_engine.database.connection import DatabaseConnectionFactory
from memory_engine.database.migrations import MigrationRunner
from memory_engine.governance.exceptions import MemoryAccessDeniedError
from memory_engine.governance.service import MemoryGovernanceService
from memory_engine.types.claim import ProposedClaim
from memory_engine.types.enums import AccessAction, DomainPartition, EpistemicType


@pytest.fixture
def governance_service():
    factory = DatabaseConnectionFactory(":memory:")
    runner = MigrationRunner(factory)
    runner.apply_migrations()
    service = MemoryGovernanceService(factory)
    yield service
    factory.close()


def test_default_deny_unknown_engine(governance_service):
    """Verifies that an unregistered engine is denied access by default."""
    allowed, policy_id = governance_service.check_access_policy(
        requesting_engine="UNKNOWN_ROGUE_ENGINE",
        resource_type="MEMORY",
        domain_partition=DomainPartition.COGNITIVE,
        access_mode=AccessAction.READ,
    )
    assert not allowed
    assert policy_id is None

    with pytest.raises(MemoryAccessDeniedError):
        governance_service.assert_access(
            requesting_engine="UNKNOWN_ROGUE_ENGINE",
            resource_type="MEMORY",
            domain_partition=DomainPartition.COGNITIVE,
            access_mode=AccessAction.READ,
        )


def test_authorized_engine_access(governance_service):
    """Verifies that PERCEPTION engine is allowed to write experiences in COGNITIVE partition."""
    allowed, policy_id = governance_service.check_access_policy(
        requesting_engine="PERCEPTION",
        resource_type="MEMORY",
        domain_partition=DomainPartition.COGNITIVE,
        access_mode=AccessAction.WRITE,
    )
    assert allowed
    assert policy_id is not None


def test_audit_log_recorded_on_access(governance_service):
    """Verifies MEM-015: Every access attempt creates an entry in audit_events."""
    session_id = str(uuid.uuid4())
    # 1. Allowed access
    governance_service.assert_access(
        requesting_engine="PERCEPTION",
        resource_type="MEMORY",
        domain_partition=DomainPartition.COGNITIVE,
        access_mode=AccessAction.WRITE,
        actor_session=session_id,
        target_id="exp-123",
    )

    # 2. Denied access
    with pytest.raises(MemoryAccessDeniedError):
        governance_service.assert_access(
            requesting_engine="EXTERNAL_ACTOR",
            resource_type="MEMORY",
            domain_partition=DomainPartition.COGNITIVE,
            access_mode=AccessAction.DELETE,
            actor_session=session_id,
            target_id="exp-456",
        )

    with governance_service.factory.read_cursor() as cursor:
        cursor.execute("SELECT event_type, actor_engine FROM audit_events ORDER BY event_at ASC;")
        rows = cursor.fetchall()
        assert len(rows) >= 2
        assert rows[-2]["event_type"] == "ACCESS_GRANTED"
        assert rows[-2]["actor_engine"] == "PERCEPTION"
        assert rows[-1]["event_type"] == "ACCESS_DENIED"
        assert rows[-1]["actor_engine"] == "EXTERNAL_ACTOR"


def test_partition_isolation_mem014(governance_service):
    """Verifies MEM-014: Autonomous engines cannot read Cognitive partition memory."""
    allowed, _ = governance_service.check_access_policy(
        requesting_engine="AUTONOMOUS",
        resource_type="MEMORY",
        domain_partition=DomainPartition.COGNITIVE,
        access_mode=AccessAction.READ,
    )
    assert not allowed, "Autonomous engine MUST NOT access Cognitive partition directly!"


def test_claim_identity_assignment(governance_service):
    """Verifies that candidate claims get assigned persistent UUIDs and provenance hashes."""
    proposal = ProposedClaim(
        subject_entity_id=uuid.uuid4(),
        predicate="likes",
        object_value="tea",
        canonical_statement="User likes Earl Grey tea.",
        epistemic_type=EpistemicType.OBSERVATION,
        source_engine="PERCEPTION",
        confidence=0.95,
        rationale="Observed in conversation",
    )
    session_id = uuid.uuid4()
    claim = governance_service.create_claim_from_proposal(
        proposal=proposal,
        session_id=session_id,
        domain_partition=DomainPartition.COGNITIVE,
    )
    assert isinstance(claim.claim_id, uuid.UUID)
    assert len(claim.provenance_hash) == 64
    assert claim.epistemic_type == EpistemicType.OBSERVATION
    assert claim.canonical_statement == "User likes Earl Grey tea."
