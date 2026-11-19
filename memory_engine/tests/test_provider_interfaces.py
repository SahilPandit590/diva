"""
Tests for MemoryEngineProtocol and Provider interfaces — Sections 6.1 & 6.2.
Verifies structural subtyping (isinstance check on Protocol) and mock provider behaviour.
"""

import uuid
import pytest
from memory_engine.engine import MemoryEngine
from memory_engine.interfaces import MemoryEngineProtocol
from memory_engine.providers import (
    EmbeddingProvider,
    MockEmbeddingProvider,
    MockReasoningProvider,
    ReasoningProvider,
)


@pytest.fixture
def eng():
    e = MemoryEngine(db_path=":memory:")
    yield e
    e.close()


def test_memory_engine_satisfies_protocol(eng):
    """MemoryEngine must structurally satisfy MemoryEngineProtocol (Section 6.1)."""
    assert isinstance(eng, MemoryEngineProtocol), (
        "MemoryEngine must implement all methods defined in MemoryEngineProtocol"
    )


def test_mock_embedding_provider_satisfies_protocol():
    """MockEmbeddingProvider must satisfy EmbeddingProvider protocol (Section 6.2)."""
    provider = MockEmbeddingProvider()
    assert isinstance(provider, EmbeddingProvider)


def test_mock_reasoning_provider_satisfies_protocol():
    """MockReasoningProvider must satisfy ReasoningProvider protocol (Section 6.2)."""
    provider = MockReasoningProvider()
    assert isinstance(provider, ReasoningProvider)


def test_mock_embedding_produces_correct_dimension():
    """Embeddings from MockEmbeddingProvider must have consistent dimensionality."""
    provider = MockEmbeddingProvider()
    dim = provider.embedding_dim()
    embeddings = provider.embed(["hello world", "foo bar", ""])
    assert len(embeddings) == 3
    for vec in embeddings:
        assert len(vec) == dim, f"Expected dim={dim}, got {len(vec)}"


def test_mock_embedding_deterministic():
    """Same text should always produce the same embedding."""
    provider = MockEmbeddingProvider()
    text = "deterministic test sentence"
    vec_a = provider.embed([text])[0]
    vec_b = provider.embed([text])[0]
    assert vec_a == vec_b


def test_mock_reasoning_provider_returns_string():
    """MockReasoningProvider.reason() must return a non-empty string."""
    provider = MockReasoningProvider()
    result = provider.reason(
        prompt="Why does this pattern repeat?",
        context="Context data from memory engine.",
    )
    assert isinstance(result, str)
    assert len(result) > 0
