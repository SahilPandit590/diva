"""
Diva Memory Engine v3.0 (Hybrid Memory Architecture) Core Engine.
Coordinates all 10 subsystems through unified, sovereign memory governance.
"""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from memory_engine.appraisal.service import AppraisalService
from memory_engine.consolidation.incremental import IncrementalConsolidator
from memory_engine.consolidation.retention import RetentionEngineService
from memory_engine.consolidation.seven_gate import SevenGateConsolidator
from memory_engine.continuity.checkpoint import ContinuityEngine
from memory_engine.database.connection import DatabaseConnectionFactory
from memory_engine.database.migrations import MigrationRunner
from memory_engine.development.patterns import PatternDetector
from memory_engine.development.service import MemoryDevelopmentService
from memory_engine.entities.service import EntityAssociationService
from memory_engine.experiences.store import ExperienceStoreService
from memory_engine.governance.service import MemoryGovernanceService
from memory_engine.intake.pipeline import MemoryIntakeService
from memory_engine.jobs.outbox import OutboxWorker
from memory_engine.jobs.scheduler import BackgroundJobScheduler
from memory_engine.jobs.worker import MemoryJobWorker
from memory_engine.knowledge.store import KnowledgeStoreService
from memory_engine.retrieval.activation import ActivationEngine
from memory_engine.retrieval.intent_router import RetrievalIntent
from memory_engine.retrieval.ranking import RetrievalEngine
from memory_engine.types.claim import EvidenceReference, MemoryClaim, ProposedClaim
from memory_engine.types.continuity import ContinuityCheckpoint
from memory_engine.types.entity import Entity
from memory_engine.types.enums import (
    DomainPartition,
    EntityType,
    EpistemicType,
    EvidenceRole,
)


class MemoryEngine:
    """
    Primary interface for Diva Memory Engine v3.0.
    Provides sovereign memory access, intake validation, episodic persistence,
    claim management, multi-layer retrieval cascade, consolidation, and continuity.
    """

    def __init__(self, db_path: str = ":memory:"):
        self.factory = DatabaseConnectionFactory(db_path)
        self.migrations = MigrationRunner(self.factory)
        self.migrations.apply_migrations()

        self.governance = MemoryGovernanceService(self.factory)
        self.scheduler = BackgroundJobScheduler(self.factory)
        self.outbox = OutboxWorker(self.factory)

        self.intake = MemoryIntakeService(self.factory, self.governance, self.scheduler)
        self.knowledge = KnowledgeStoreService(self.factory, self.governance)
        self.entities = EntityAssociationService(self.factory, self.governance)
        self.worker = MemoryJobWorker(self.factory, self.scheduler, self.entities)
        self.patterns = PatternDetector(self.factory, self.entities)
        self.development = MemoryDevelopmentService(
            self.factory, self.governance, self.knowledge, self.patterns
        )
        self.activation = ActivationEngine(self.factory)
        self.retrieval = RetrievalEngine(self.factory, self.governance, self.activation)
        self.consolidation = SevenGateConsolidator(self.factory, self.governance)
        self.incremental_consolidation = IncrementalConsolidator(
            self.factory, self.consolidation
        )
        self.retention = RetentionEngineService(self.factory, self.governance)
        self.continuity = ContinuityEngine(self.factory, self.governance)
        self.appraisals = AppraisalService(self.factory, self.governance)
        self.experience_store = ExperienceStoreService(self.factory, self.governance)

    def submit_experience(
        self,
        source_engine: str,
        channel: str,
        raw_content: str,
        session_id: uuid.UUID,
        domain_partition: DomainPartition = DomainPartition.COGNITIVE,
        experience_summary: Optional[str] = None,
        explicit_epistemic: Optional[EpistemicType] = None,
        importance_flag: bool = False,
        participants: Optional[List[uuid.UUID]] = None,
        world_time_start: Optional[datetime] = None,
        world_time_end: Optional[datetime] = None,
    ) -> Tuple[uuid.UUID, Optional[uuid.UUID], bool]:
        """Submits an incoming experience through the 7-stage intake pipeline."""
        return self.intake.submit_input(
            source_engine=source_engine,
            channel=channel,
            domain_partition=domain_partition,
            session_id=session_id,
            raw_content=raw_content,
            experience_summary=experience_summary,
            explicit_epistemic=explicit_epistemic,
            importance_flag=importance_flag,
            participants=participants,
            world_time_start=world_time_start,
            world_time_end=world_time_end,
        )

    def store_claim(
        self,
        proposal: ProposedClaim,
        session_id: uuid.UUID,
        domain_partition: DomainPartition = DomainPartition.COGNITIVE,
        source_experience_id: Optional[uuid.UUID] = None,
        world_time_start: Optional[datetime] = None,
        world_time_end: Optional[datetime] = None,
    ) -> MemoryClaim:
        """Stores a propositional claim with contradiction detection and provenance."""
        return self.knowledge.create_claim(
            proposal=proposal,
            session_id=session_id,
            domain_partition=domain_partition,
            source_experience_id=source_experience_id,
            world_time_start=world_time_start,
            world_time_end=world_time_end,
        )

    def retrieve(
        self,
        query_text: str,
        requesting_engine: str,
        domain_partition: DomainPartition = DomainPartition.COGNITIVE,
        session_id: uuid.UUID = uuid.UUID("00000000-0000-0000-0000-000000000000"),
        intent: RetrievalIntent = RetrievalIntent.GENERAL,
        token_budget: Optional[int] = None,
        seed_memory_ids: Optional[List[str]] = None,
        entity_filter: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Multi-layer retrieval cascade returning ranked memory items scaled by intent."""
        return self.retrieval.retrieve(
            query_text=query_text,
            requesting_engine=requesting_engine,
            domain_partition=domain_partition,
            session_id=session_id,
            intent=intent,
            token_budget=token_budget,
            seed_memory_ids=seed_memory_ids,
            entity_filter=entity_filter,
            limit=limit,
        )

    def submit_appraisal(
        self,
        experience_id: uuid.UUID,
        appraising_engine: str,
        appraisal_type: str,
        appraisal_content: Dict[str, Any],
        confidence: float,
        session_id: uuid.UUID,
        domain_partition: DomainPartition = DomainPartition.COGNITIVE,
    ) -> uuid.UUID:
        """Submits a domain-specific appraisal contribution for an experience."""
        return self.appraisals.submit_appraisal(
            experience_id=experience_id,
            appraising_engine=appraising_engine,
            appraisal_type=appraisal_type,
            appraisal_content=appraisal_content,
            confidence=confidence,
            session_id=session_id,
            domain_partition=domain_partition,
        )

    def get_appraisals(
        self,
        experience_id: uuid.UUID,
        appraisal_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieves active appraisals for an experience."""
        return self.appraisals.get_appraisals(experience_id, appraisal_type)

    def add_evidence(
        self,
        claim_id: uuid.UUID,
        relationship: EvidenceRole,
        weight: float = 1.0,
        source_memory_id: Optional[uuid.UUID] = None,
        source_claim_id: Optional[uuid.UUID] = None,
        added_by: str = "THOUGHT",
    ) -> EvidenceReference:
        """Links evidential support/opposition to a claim."""
        return self.knowledge.add_evidence(
            claim_id=claim_id,
            relationship=relationship,
            weight=weight,
            source_memory_id=source_memory_id,
            source_claim_id=source_claim_id,
            added_by=added_by,
        )

    def resolve_entity(
        self, mention_text: str, domain_partition: DomainPartition = DomainPartition.COGNITIVE
    ) -> Optional[Entity]:
        """Resolves an entity mention by canonical name or registered alias."""
        return self.entities.resolve_entity(mention_text, domain_partition)

    def create_or_get_entity(
        self,
        canonical_name: str,
        entity_type: EntityType = EntityType.UNKNOWN,
        domain_partition: DomainPartition = DomainPartition.COGNITIVE,
        aliases: Optional[List[str]] = None,
        source_engine: str = "PERCEPTION",
    ) -> Entity:
        """Creates or retrieves an entity record."""
        return self.entities.create_or_get_entity(
            canonical_name=canonical_name,
            entity_type=entity_type,
            domain_partition=domain_partition,
            aliases=aliases,
            source_engine=source_engine,
        )

    def merge_entities(
        self,
        source_entity_id: uuid.UUID,
        target_entity_id: uuid.UUID,
        actor_engine: str = "MEMORY_GOVERNANCE",
        actor_session: str = "00000000-0000-0000-0000-000000000000",
    ) -> None:
        """Merges source entity into target entity, updating aliases and participants."""
        self.entities.merge_entities(
            source_entity_id=source_entity_id,
            target_entity_id=target_entity_id,
            actor_engine=actor_engine,
            actor_session=actor_session,
        )

    def create_checkpoint(
        self,
        session_id: uuid.UUID,
        domain_partition: DomainPartition = DomainPartition.COGNITIVE,
        workspace_snapshot_ref: Optional[uuid.UUID] = None,
        attention_snapshot_ref: Optional[uuid.UUID] = None,
        activity_snapshot_refs: Optional[List[uuid.UUID]] = None,
        active_goal_refs: Optional[List[uuid.UUID]] = None,
        unresolved_commitment_refs: Optional[List[uuid.UUID]] = None,
        requesting_engine: str = "COGNITIVE_INTEGRATION",
    ) -> ContinuityCheckpoint:
        """Creates a continuity checkpoint referencing external engine state snapshots."""
        return self.continuity.create_checkpoint(
            session_id=session_id,
            domain_partition=domain_partition,
            workspace_snapshot_ref=workspace_snapshot_ref,
            attention_snapshot_ref=attention_snapshot_ref,
            activity_snapshot_refs=activity_snapshot_refs,
            active_goal_refs=active_goal_refs,
            unresolved_commitment_refs=unresolved_commitment_refs,
            requesting_engine=requesting_engine,
        )

    def restore_checkpoint(
        self,
        session_id: uuid.UUID,
        domain_partition: DomainPartition = DomainPartition.COGNITIVE,
        requesting_engine: str = "COGNITIVE_INTEGRATION",
    ) -> Optional[ContinuityCheckpoint]:
        """Restores the latest valid continuity checkpoint."""
        return self.continuity.restore_latest_checkpoint(
            session_id=session_id,
            domain_partition=domain_partition,
            requesting_engine=requesting_engine,
        )

    def consolidate_memories(
        self,
        source_memory_ids: List[uuid.UUID],
        summary: str,
        claims: List[Dict[str, Any]],
        domain_partition: DomainPartition = DomainPartition.COGNITIVE,
        initiating_engine: str = "MEMORY_CONSOLIDATION",
    ) -> Tuple[bool, Optional[uuid.UUID], Dict[str, Any]]:
        """Executes the 7-gate consolidation protocol."""
        return self.consolidation.consolidate(
            source_memory_ids=source_memory_ids,
            consolidated_summary=summary,
            consolidated_claims=claims,
            domain_partition=domain_partition,
            initiating_engine=initiating_engine,
        )

    def close(self) -> None:
        """Closes all database connections and releases locks."""
        self.factory.close()
