"""
Governance, access policy, and audit contracts for Diva Memory Engine v3.0.
"""

from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict

from memory_engine.types.enums import (
    AccessAction,
    AccessEffect,
    DomainPartition,
)


class AccessPolicy(BaseModel):
    """
    Access permission rule evaluated by MemoryGovernanceService.
    Default-deny: Any engine lacking an explicit rule is denied access.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_id: UUID
    requesting_engine: str
    target_domain: str
    permitted_actions: tuple[AccessAction, ...]
    allowed_partitions: tuple[DomainPartition, ...]
    requires_audit: bool = True
    is_active: bool = True


class AuditEvent(BaseModel):
    """
    Immutable audit log record. Must be logged on every critical status change
    and on every access attempt (allowed or denied) per MEM-015.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    audit_id: UUID
    event_type: str
    actor_engine: str
    action: AccessAction
    target_table: str
    target_id: str
    partition: DomainPartition
    outcome: AccessEffect
    details: str = ""
    timestamp: datetime


class SchemaVersion(BaseModel):
    """Tracks applied database schema versions."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int
    applied_at: datetime
    description: str
