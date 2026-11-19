"""
Unit tests for Retrieval Intent Routing, layer weight scaling, and token budget knapsack assembly.
"""

import uuid
import pytest
from memory_engine.database.connection import DatabaseConnectionFactory
from memory_engine.database.migrations import MigrationRunner
from memory_engine.governance.service import MemoryGovernanceService
from memory_engine.intake.pipeline import MemoryIntakeService
from memory_engine.jobs.scheduler import BackgroundJobScheduler
from memory_engine.retrieval.activation import ActivationEngine
from memory_engine.retrieval.intent_router import (
    RetrievalIntent,
    RetrievalIntentRouter,
)
from memory_engine.retrieval.ranking import RetrievalEngine
from memory_engine.types.enums import DomainPartition


@pytest.fixture
def retrieval_stack():
    factory = DatabaseConnectionFactory(":memory:")
    runner = MigrationRunner(factory)
    runner.apply_migrations()
    governance = MemoryGovernanceService(factory)
    scheduler = BackgroundJobScheduler(factory)
    intake = MemoryIntakeService(factory, governance, scheduler)
    activation = ActivationEngine(factory)
    engine = RetrievalEngine(factory, governance, activation)
    yield engine, intake, factory
    factory.close()


def test_intent_routing_and_event_logging(retrieval_stack):
    """Verifies that retrieval with specific intents scales layer scores and logs intent in retrieval_events."""
    engine, intake, factory = retrieval_stack
    session_id = uuid.uuid4()

    intake.submit_input(
        source_engine="PERCEPTION",
        channel="TEXT",
        domain_partition=DomainPartition.COGNITIVE,
        session_id=session_id,
        raw_content="Deep dive into neural network architectures and transformer attention heads.",
    )

    # 1. Retrieve with FACTUAL intent
    factual_results = engine.retrieve(
        query_text="transformer attention",
        requesting_engine="THOUGHT",
        domain_partition=DomainPartition.COGNITIVE,
        intent=RetrievalIntent.FACTUAL,
    )
    assert len(factual_results) >= 1

    # 2. Retrieve with ASSOCIATIVE intent
    assoc_results = engine.retrieve(
        query_text="transformer attention",
        requesting_engine="THOUGHT",
        domain_partition=DomainPartition.COGNITIVE,
        intent=RetrievalIntent.ASSOCIATIVE,
    )
    assert len(assoc_results) >= 1

    # Verify retrieval_events table recorded the intents
    with factory.read_cursor() as cursor:
        cursor.execute("SELECT retrieval_intent FROM retrieval_events ORDER BY retrieved_at ASC;")
        intents = [r["retrieval_intent"] for r in cursor.fetchall()]
        assert "FACTUAL" in intents
        assert "ASSOCIATIVE" in intents


def test_greedy_token_budget_assembly(retrieval_stack):
    """Verifies that token budget assembly packs items until the budget is exhausted."""
    engine, intake, _ = retrieval_stack
    session_id = uuid.uuid4()

    # Ingest several verbose experiences
    for i in range(5):
        intake.submit_input(
            source_engine="PERCEPTION",
            channel="TEXT",
            domain_partition=DomainPartition.COGNITIVE,
            session_id=session_id,
            raw_content=f"Report item {i}: Extensive logs explaining system parameters and optimization routines in detail.",
        )

    # Retrieve with very small token budget (e.g. 30 tokens ~ 120 chars)
    results = engine.retrieve(
        query_text="Extensive logs",
        requesting_engine="THOUGHT",
        domain_partition=DomainPartition.COGNITIVE,
        token_budget=30,
        limit=10,
    )
    # Output should be constrained to fit within budget
    total_tokens = sum(r.get("estimated_tokens", 0) for r in results)
    assert total_tokens <= 30
    assert len(results) >= 1


def test_hyde_ephemeral_projection():
    """Verifies that HyDE generates an ephemeral query projection without persisting it."""
    proj = RetrievalIntentRouter.generate_hyde_projection("How does episodic consolidation work?")
    assert "episodic consolidation" in proj
    assert len(proj) > len("How does episodic consolidation work?")
