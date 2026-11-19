"""
Tests for ExperienceStoreService — Section 5.2.
Covers FSM-gated status transitions, audit logging (MEM-015), session/entity queries,
and bitemporal world_time snapshot.
"""

import uuid
from datetime import datetime, timedelta, timezone
import pytest
from memory_engine.engine import MemoryEngine
from memory_engine.experiences.store import ExperienceStoreService
from memory_engine.development.lifecycle import InvalidStateTransitionError
from memory_engine.types.enums import DomainPartition, DevelopmentStatus


@pytest.fixture
def eng():
    e = MemoryEngine(db_path=":memory:")
    yield e
    e.close()


@pytest.fixture
def store(eng):
    return ExperienceStoreService(eng.factory, eng.governance)


def _submit_exp(eng, raw_content="Hello world", session_id=None):
    sid = session_id or uuid.uuid4()
    _, exp_id, _ = eng.submit_experience(
        source_engine="PERCEPTION",
        channel="text",
        raw_content=raw_content,
        session_id=sid,
        domain_partition=DomainPartition.COGNITIVE,
    )
    assert exp_id is not None
    return exp_id, sid


def test_get_experience_returns_dict(eng, store):
    """get_experience returns the full row as a dict."""
    exp_id, _ = _submit_exp(eng)
    record = store.get_experience(exp_id)
    assert record is not None
    assert record["experience_id"] == str(exp_id)
    assert record["development_status"] == DevelopmentStatus.RAW.value


def test_fsm_valid_status_transition(eng, store):
    """RAW → ORGANIZED is a legal transition."""
    exp_id, sid = _submit_exp(eng)
    updated = store.update_development_status(
        experience_id=exp_id,
        new_status=DevelopmentStatus.ORGANIZED,
        actor_engine="MEMORY_DEVELOPMENT",
        session_id=sid,
    )
    assert updated["development_status"] == DevelopmentStatus.ORGANIZED.value


def test_fsm_invalid_transition_raises(eng, store):
    """RAW → ACCEPTED is illegal; InvalidStateTransitionError should be raised."""
    exp_id, sid = _submit_exp(eng)
    with pytest.raises((InvalidStateTransitionError, ValueError)):
        store.update_development_status(
            experience_id=exp_id,
            new_status=DevelopmentStatus.ACCEPTED,
            actor_engine="MEMORY_DEVELOPMENT",
            session_id=sid,
        )


def test_audit_event_written_in_same_tx(eng, store):
    """MEM-015: audit event must be in the same transaction as the status update."""
    exp_id, sid = _submit_exp(eng)
    store.update_development_status(
        experience_id=exp_id,
        new_status=DevelopmentStatus.ORGANIZED,
        actor_engine="MEMORY_DEVELOPMENT",
        session_id=sid,
    )
    with eng.factory.read_cursor() as cursor:
        cursor.execute(
            """
            SELECT event_type FROM audit_events
            WHERE target_id = ? AND event_type = 'EXPERIENCE_STATUS_UPDATED'
            ORDER BY event_at DESC LIMIT 1;
            """,
            (str(exp_id),),
        )
        row = cursor.fetchone()
    assert row is not None, "Audit event should have been written co-committed with status update"


def test_get_experiences_by_session(eng, store):
    """Session-scoped query returns only experiences from that session."""
    sid = uuid.uuid4()
    exp_id1, _ = _submit_exp(eng, raw_content="First", session_id=sid)
    exp_id2, _ = _submit_exp(eng, raw_content="Second", session_id=sid)
    _submit_exp(eng, raw_content="Other", session_id=uuid.uuid4())

    results = store.get_experiences_by_session(sid, DomainPartition.COGNITIVE)
    result_ids = {r["experience_id"] for r in results}
    assert str(exp_id1) in result_ids
    assert str(exp_id2) in result_ids
    assert len(results) == 2


def test_get_bitemporal_snapshot(eng, store):
    """Bitemporal snapshot should include experiences whose world_time spans the query time."""
    past = datetime.now(timezone.utc) - timedelta(days=10)
    future = datetime.now(timezone.utc) + timedelta(days=10)
    query_time = datetime.now(timezone.utc)

    # Experience with explicit world_time range spanning now
    _, exp_id, _ = eng.submit_experience(
        source_engine="PERCEPTION",
        channel="text",
        raw_content="Spans query time",
        session_id=uuid.uuid4(),
        domain_partition=DomainPartition.COGNITIVE,
        world_time_start=past,
        world_time_end=future,
    )
    assert exp_id is not None

    results = store.get_bitemporal_snapshot(query_time, DomainPartition.COGNITIVE)
    result_ids = {r["experience_id"] for r in results}
    assert str(exp_id) in result_ids
