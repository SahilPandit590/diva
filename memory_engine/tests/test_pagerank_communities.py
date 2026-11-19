"""
Tests for NetworkX graph projection, PageRank, and Louvain community detection — Section 4.4.
"""

import uuid
import pytest
from memory_engine.engine import MemoryEngine
from memory_engine.types.enums import DomainPartition, MemoryRelationshipType


@pytest.fixture
def eng():
    e = MemoryEngine(db_path=":memory:")
    yield e
    e.close()


def _add_experience(eng, content):
    _, exp_id, _ = eng.submit_experience(
        source_engine="PERCEPTION",
        channel="text",
        raw_content=content,
        session_id=uuid.uuid4(),
        domain_partition=DomainPartition.COGNITIVE,
    )
    assert exp_id is not None
    return exp_id


def test_graph_projection_loads_relationships(eng):
    """refresh_graph_projection should build a non-empty DiGraph after creating memory links."""
    exp_a = _add_experience(eng, "Memory A")
    exp_b = _add_experience(eng, "Memory B")

    eng.entities.link_memories(
        source_id=exp_a,
        target_id=exp_b,
        relationship_type=MemoryRelationshipType.ASSOCIATED_WITH,
        confidence=0.9,
    )

    eng.activation.refresh_graph_projection()
    assert len(eng.activation._graph) > 0
    assert len(eng.activation._graph.edges) > 0


def test_pagerank_returns_scores(eng):
    """compute_pagerank should return a dict of {memory_id: score} for all graph nodes."""
    exp_a = _add_experience(eng, "PR Memory A")
    exp_b = _add_experience(eng, "PR Memory B")
    exp_c = _add_experience(eng, "PR Memory C")

    eng.entities.link_memories(exp_a, exp_b, MemoryRelationshipType.CAUSED_BY, 0.9)
    eng.entities.link_memories(exp_b, exp_c, MemoryRelationshipType.ASSOCIATED_WITH, 0.8)
    eng.entities.link_memories(exp_a, exp_c, MemoryRelationshipType.SIMILAR_TO, 0.7)

    ranks = eng.activation.compute_pagerank()
    assert len(ranks) == 3
    for node_id, score in ranks.items():
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0
    # Scores should sum close to 1.0 (PageRank property)
    assert abs(sum(ranks.values()) - 1.0) < 0.01


def test_pagerank_on_empty_graph_returns_empty(eng):
    """compute_pagerank with no relationships returns empty dict."""
    ranks = eng.activation.compute_pagerank()
    assert ranks == {}


def test_community_detection_groups_nodes(eng):
    """detect_communities should group connected nodes into communities."""
    exp_a = _add_experience(eng, "Community A1")
    exp_b = _add_experience(eng, "Community A2")
    exp_c = _add_experience(eng, "Community B1")

    # A and B are connected; C is isolated
    eng.entities.link_memories(exp_a, exp_b, MemoryRelationshipType.ASSOCIATED_WITH, 0.9)

    communities = eng.activation.detect_communities()
    assert len(communities) >= 1
    # Flatten to check all experiences appear
    all_nodes = set().union(*communities)
    assert str(exp_a) in all_nodes
    assert str(exp_b) in all_nodes


def test_community_detection_on_empty_graph_returns_empty(eng):
    """detect_communities with no relationships returns empty list."""
    result = eng.activation.detect_communities()
    assert result == []
