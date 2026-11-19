"""
Continuity checkpoint contract for Diva Memory Engine v3.0.
Memory persists state references for other engines without interpreting their private contents.
"""

from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict

from memory_engine.types.enums import DomainPartition


class ContinuityCheckpoint(BaseModel):
    """
    Checkpoint storing authorized snapshot references owned by other engines.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    checkpoint_id: UUID
    session_id: UUID
    schema_version: int = 1
    domain_partition: DomainPartition = DomainPartition.COGNITIVE
    workspace_snapshot_ref: UUID | None = None
    attention_snapshot_ref: UUID | None = None
    activity_snapshot_refs: tuple[UUID, ...] = ()
    active_goal_refs: tuple[UUID, ...] = ()
    unresolved_commitment_refs: tuple[UUID, ...] = ()
    created_at: datetime
    valid: bool = True
    restoration_attempted: bool = False
    restoration_succeeded: bool | None = None
