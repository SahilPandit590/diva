"""
Unit tests for Appraisal subsystem, multi-engine contributions, and historical versioning.
"""

import uuid
import pytest
from memory_engine.appraisal.service import AppraisalService
from memory_engine.database.connection import DatabaseConnectionFactory
from memory_engine.database.migrations import MigrationRunner
from memory_engine.governance.exceptions import MemoryAccessDeniedError
from memory_engine.governance.service import MemoryGovernanceService
from memory_engine.intake.pipeline import MemoryIntakeService
from memory_engine.jobs.scheduler import BackgroundJobScheduler
from memory_engine.types.enums import DomainPartition


@pytest.fixture
def appraisal_stack():
    factory = DatabaseConnectionFactory(":memory:")
    runner = MigrationRunner(factory)
    runner.apply_migrations()
    governance = MemoryGovernanceService(factory)
    scheduler = BackgroundJobScheduler(factory)
    intake = MemoryIntakeService(factory, governance, scheduler)
    service = AppraisalService(factory, governance)
    yield service, intake, factory
    factory.close()


def test_emotional_and_social_appraisals(appraisal_stack):
    """Verifies that specialized engines contribute appraisals to experiences without altering experience records."""
    service, intake, factory = appraisal_stack
    session_id = uuid.uuid4()

    # Create experience
    _, exp_id, _ = intake.submit_input(
        source_engine="PERCEPTION",
        channel="TEXT",
        domain_partition=DomainPartition.COGNITIVE,
        session_id=session_id,
        raw_content="The user shared a deeply personal milestone and thanked Diva warmly.",
    )
    assert exp_id is not None

    # 1. Emotion Engine appraisal
    app_id_emotion = service.submit_appraisal(
        experience_id=exp_id,
        appraising_engine="EMOTION",
        appraisal_type="EMOTIONAL",
        appraisal_content={"valence": 0.85, "arousal": 0.6, "primary_emotion": "GRATITUDE"},
        confidence=0.9,
        session_id=session_id,
    )
    assert app_id_emotion is not None

    # 2. Social Cognition Engine appraisal
    app_id_social = service.submit_appraisal(
        experience_id=exp_id,
        appraising_engine="SOCIAL_COGNITION",
        appraisal_type="SOCIAL",
        appraisal_content={"relational_closeness": 0.75, "social_norm": "AUTHENTIC_APPRECIATION"},
        confidence=0.95,
        session_id=session_id,
    )
    assert app_id_social is not None

    # Retrieve all appraisals
    appraisals = service.get_appraisals(exp_id)
    assert len(appraisals) == 2
    types = {a["type"] for a in appraisals}
    assert "EMOTIONAL" in types
    assert "SOCIAL" in types


def test_reappraisal_version_history(appraisal_stack):
    """Verifies that reappraisal preserves the previous snapshot in appraisal_history."""
    service, intake, _ = appraisal_stack
    session_id = uuid.uuid4()

    _, exp_id, _ = intake.submit_input(
        source_engine="PERCEPTION",
        channel="TEXT",
        domain_partition=DomainPartition.COGNITIVE,
        session_id=session_id,
        raw_content="Ambiguous situation where user reacted with silence.",
    )

    # Initial appraisal
    app_id = service.submit_appraisal(
        experience_id=exp_id,
        appraising_engine="EMOTION",
        appraisal_type="EMOTIONAL",
        appraisal_content={"valence": -0.2, "primary_emotion": "CONFUSION"},
        confidence=0.5,
        session_id=session_id,
    )

    # Re-appraisal after more context
    app_id_v2 = service.submit_appraisal(
        experience_id=exp_id,
        appraising_engine="EMOTION",
        appraisal_type="EMOTIONAL",
        appraisal_content={"valence": 0.4, "primary_emotion": "CONTEMPLATION"},
        confidence=0.85,
        session_id=session_id,
    )
    assert app_id == app_id_v2

    # Active appraisal is now version 2
    active = service.get_appraisals(exp_id, appraisal_type="EMOTIONAL")
    assert len(active) == 1
    assert active[0]["version"] == 2
    assert active[0]["content"]["primary_emotion"] == "CONTEMPLATION"

    # Historical version 1 preserved
    history = service.get_appraisal_history(app_id)
    assert len(history) == 1
    assert history[0]["version"] == 1
    assert history[0]["content"]["primary_emotion"] == "CONFUSION"


def test_unauthorized_engine_appraisal_rejected(appraisal_stack):
    """Verifies default-deny security: unauthorized engine cannot write appraisals."""
    service, intake, _ = appraisal_stack
    session_id = uuid.uuid4()

    _, exp_id, _ = intake.submit_input(
        source_engine="PERCEPTION",
        channel="TEXT",
        domain_partition=DomainPartition.COGNITIVE,
        session_id=session_id,
        raw_content="Event testing unauthorized appraisal.",
    )

    with pytest.raises(MemoryAccessDeniedError):
        service.submit_appraisal(
            experience_id=exp_id,
            appraising_engine="UNAUTHORIZED_ROGUE_ENGINE",
            appraisal_type="EMOTIONAL",
            appraisal_content={"fake": "data"},
            confidence=0.1,
            session_id=session_id,
        )
