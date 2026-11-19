"""
Development request, result, and budget contracts for Diva Memory Engine v3.0.
"""

from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

from memory_engine.types.claim import ProposedClaim, ProposedRelationship
from memory_engine.types.enums import (
    DevelopmentOperationType,
    DevelopmentResultStatus,
)


class ResourceBudget(BaseModel):
    """Resource constraints for an asynchronous development operation."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_cpu_seconds: float = Field(default=30.0, gt=0.0)
    max_llm_tokens: int = Field(default=0, ge=0)
    timeout_seconds: float = Field(default=60.0, gt=0.0)


class DevelopmentRequest(BaseModel):
    """
    Contract for requesting a memory development operation.
    Bounded processing depth prevents infinite recursive development loops (MEM-012).
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: UUID
    operation_type: DevelopmentOperationType
    initiating_subsystem: str
    requesting_engine: str | None = None
    target_memory_ids: tuple[UUID, ...] = ()
    target_claim_ids: tuple[UUID, ...] = ()
    development_objective: str
    evidence_requirements: tuple[str, ...] = ()
    parent_operation_id: UUID | None = None
    processing_depth: int = Field(default=0, ge=0)
    max_processing_depth: int = Field(default=5, ge=1, le=10)
    resource_budget: ResourceBudget = ResourceBudget()
    idempotency_key: str
    priority: int = Field(default=5, ge=0, le=10)  # 0=CRITICAL, 10=BACKGROUND
    requested_at: datetime
    deadline_at: datetime | None = None


class DevelopmentResult(BaseModel):
    """
    Outcome returned by a development operation.
    Proposals do NOT possess database UUIDs until accepted by Memory Governance.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: UUID
    originating_engine: str
    result_status: DevelopmentResultStatus
    proposed_claims: tuple[ProposedClaim, ...] = ()
    proposed_relationships: tuple[ProposedRelationship, ...] = ()
    supporting_evidence_ids: tuple[UUID, ...] = ()
    opposing_evidence_ids: tuple[UUID, ...] = ()
    unresolved_questions: tuple[str, ...] = ()
    rationale: str
    produced_at: datetime
