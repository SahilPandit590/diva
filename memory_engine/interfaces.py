"""
Diva Memory Engine v3.0 — Formal Protocol interfaces (Section 6.1).
Structural subtyping contracts for the MemoryEngine and cognitive-integration boundary.
All external engines interact with Memory Engine ONLY through these interfaces.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Protocol, Tuple, runtime_checkable

from memory_engine.types.claim import EvidenceReference, MemoryClaim, ProposedClaim
from memory_engine.types.continuity import ContinuityCheckpoint
from memory_engine.types.entity import Entity
from memory_engine.types.enums import DomainPartition, EntityType, EpistemicType, EvidenceRole
from memory_engine.retrieval.intent_router import RetrievalIntent


@runtime_checkable
class MemoryEngineProtocol(Protocol):
    """
    Section 6.1 — Formal structural protocol defining the complete external boundary
    of the Memory Engine.  Any class that implements these methods satisfies the protocol
    without inheriting from it (duck-typed structural subtyping).
    """

    def submit_experience(
        self,
        source_engine: str,
        channel: str,
        raw_content: str,
        session_id: uuid.UUID,
        domain_partition: DomainPartition,
        experience_summary: Optional[str],
        explicit_epistemic: Optional[EpistemicType],
        importance_flag: bool,
        participants: Optional[List[uuid.UUID]],
        world_time_start: Optional[datetime],
        world_time_end: Optional[datetime],
    ) -> Tuple[uuid.UUID, Optional[uuid.UUID], bool]:
        """Submit an incoming experience through the 7-stage intake pipeline."""
        ...

    def store_claim(
        self,
        proposal: ProposedClaim,
        session_id: uuid.UUID,
        domain_partition: DomainPartition,
        source_experience_id: Optional[uuid.UUID],
        world_time_start: Optional[datetime],
        world_time_end: Optional[datetime],
    ) -> MemoryClaim:
        """Store a propositional claim with contradiction detection and provenance."""
        ...

    def retrieve(
        self,
        query_text: str,
        requesting_engine: str,
        domain_partition: DomainPartition,
        session_id: uuid.UUID,
        intent: RetrievalIntent,
        token_budget: Optional[int],
        seed_memory_ids: Optional[List[str]],
        entity_filter: Optional[str],
        limit: int,
    ) -> List[Dict[str, Any]]:
        """Multi-layer retrieval cascade returning ranked memory items."""
        ...

    def add_evidence(
        self,
        claim_id: uuid.UUID,
        relationship: EvidenceRole,
        weight: float,
        source_memory_id: Optional[uuid.UUID],
        source_claim_id: Optional[uuid.UUID],
        added_by: str,
    ) -> EvidenceReference:
        """Link evidential support/opposition to a claim."""
        ...

    def resolve_entity(
        self,
        mention_text: str,
        domain_partition: DomainPartition,
    ) -> Optional[Entity]:
        """Resolve an entity mention by canonical name, alias, or fuzzy match."""
        ...

    def create_or_get_entity(
        self,
        canonical_name: str,
        entity_type: EntityType,
        domain_partition: DomainPartition,
        aliases: Optional[List[str]],
        source_engine: str,
    ) -> Entity:
        """Create or retrieve an entity record."""
        ...

    def create_checkpoint(
        self,
        session_id: uuid.UUID,
        domain_partition: DomainPartition,
        workspace_snapshot_ref: Optional[uuid.UUID],
        attention_snapshot_ref: Optional[uuid.UUID],
        activity_snapshot_refs: Optional[List[uuid.UUID]],
        active_goal_refs: Optional[List[uuid.UUID]],
        unresolved_commitment_refs: Optional[List[uuid.UUID]],
        requesting_engine: str,
    ) -> ContinuityCheckpoint:
        """Create a continuity checkpoint referencing external engine state snapshots."""
        ...

    def restore_checkpoint(
        self,
        session_id: uuid.UUID,
        domain_partition: DomainPartition,
        requesting_engine: str,
    ) -> Optional[ContinuityCheckpoint]:
        """Restore the latest valid continuity checkpoint."""
        ...

    def close(self) -> None:
        """Close all database connections and release locks."""
        ...
