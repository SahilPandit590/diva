"""
Tests for entity resolution pipeline — Section 3.3.
Covers Step 1 (exact canonical), Step 2 (exact alias), and Step 3 (fuzzy alias matching).
"""

import uuid
import pytest
from memory_engine.engine import MemoryEngine
from memory_engine.types.enums import DomainPartition, EntityType


@pytest.fixture
def eng():
    e = MemoryEngine(db_path=":memory:")
    yield e
    e.close()


def test_exact_canonical_name_resolution(eng):
    """Step 1: resolve by exact canonical name."""
    entity = eng.create_or_get_entity(
        canonical_name="Alice",
        entity_type=EntityType.PERSON,
        domain_partition=DomainPartition.COGNITIVE,
    )
    resolved = eng.resolve_entity("Alice", DomainPartition.COGNITIVE)
    assert resolved is not None
    assert resolved.entity_id == entity.entity_id
    assert resolved.canonical_name == "Alice"


def test_exact_alias_resolution(eng):
    """Step 2: resolve by exact registered alias."""
    entity = eng.create_or_get_entity(
        canonical_name="Robert Johnson",
        entity_type=EntityType.PERSON,
        domain_partition=DomainPartition.COGNITIVE,
        aliases=["Bob"],
    )
    resolved = eng.resolve_entity("Bob", DomainPartition.COGNITIVE)
    assert resolved is not None
    assert resolved.entity_id == entity.entity_id
    assert resolved.canonical_name == "Robert Johnson"


def test_fuzzy_alias_resolution_one_char_typo(eng):
    """Step 3: fuzzy match — one-character typo in alias text."""
    entity = eng.create_or_get_entity(
        canonical_name="Catherine",
        entity_type=EntityType.PERSON,
        domain_partition=DomainPartition.COGNITIVE,
        aliases=["Cath"],
    )
    # 'Cath' vs 'Cat' — Levenshtein distance 1, ratio > 0.85
    resolved = eng.resolve_entity("Cat", DomainPartition.COGNITIVE)
    assert resolved is not None
    assert resolved.entity_id == entity.entity_id


def test_fuzzy_match_registers_provisional_alias(eng):
    """Fuzzy match should persist a provisional alias for future use."""
    eng.create_or_get_entity(
        canonical_name="Michael",
        entity_type=EntityType.PERSON,
        domain_partition=DomainPartition.COGNITIVE,
        aliases=["Mike"],
    )
    # First time: fuzzy match for 'Mik'
    resolved = eng.resolve_entity("Mik", DomainPartition.COGNITIVE)
    assert resolved is not None

    # Second time: should now resolve via the registered provisional alias (exact alias match)
    resolved2 = eng.resolve_entity("Mik", DomainPartition.COGNITIVE)
    assert resolved2 is not None
    assert resolved2.entity_id == resolved.entity_id


def test_no_match_returns_none(eng):
    """Completely unrelated text should return None."""
    eng.create_or_get_entity(
        canonical_name="David",
        entity_type=EntityType.PERSON,
        domain_partition=DomainPartition.COGNITIVE,
    )
    result = eng.resolve_entity("Zxqwerty", DomainPartition.COGNITIVE)
    assert result is None


def test_partition_isolation_in_resolution(eng):
    """Entity in COGNITIVE partition should not be found when resolving in AUTONOMOUS."""
    eng.create_or_get_entity(
        canonical_name="SharedName",
        entity_type=EntityType.CONCEPT,
        domain_partition=DomainPartition.COGNITIVE,
    )
    result = eng.resolve_entity("SharedName", DomainPartition.AUTONOMOUS)
    assert result is None
