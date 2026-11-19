"""
Memory Governance Service for Diva Memory Engine v3.0.
Responsible for access policy enforcement, domain partition boundary checking,
audit logging, and sovereign authority over claim and representation identities.
"""

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from memory_engine.database.connection import DatabaseConnectionFactory
from memory_engine.governance.exceptions import (
    MemoryAccessDeniedError,
    PartitionViolationError,
)
from memory_engine.types.claim import MemoryClaim, ProposedClaim
from memory_engine.types.enums import (
    AccessAction,
    AccessEffect,
    ClaimLifecycle,
    DomainPartition,
    EvidenceStatus,
)


class MemoryGovernanceService:
    """
    Sovereign gatekeeper for Memory Engine state.
    Enforces the following invariants:
      - Default-deny access control via access_policies table.
      - MEM-014: Cognitive and Autonomous partitions are strictly isolated.
      - MEM-015: Every write operation records an audit_events entry in the same transaction.
      - Sole authority over UUID assignment: external engines cannot supply persistent claim IDs.
    """

    def __init__(self, factory: DatabaseConnectionFactory):
        self.factory = factory

    def check_access_policy(
        self,
        requesting_engine: str,
        resource_type: str,
        domain_partition: DomainPartition,
        access_mode: AccessAction,
    ) -> Tuple[bool, Optional[str]]:
        """
        Evaluates active policies in access_policies table.
        Returns (is_allowed, matching_policy_id).
        """
        # Admin bypass for internal Memory Governance operations
        if requesting_engine == "MEMORY_GOVERNANCE":
            return True, "00000000-0000-0000-0000-000000000009"

        with self.factory.read_cursor() as cursor:
            # Query policies matching partition and resource type
            cursor.execute(
                """
                SELECT policy_id, target_resource, resource_type, domain_partition,
                       permitted_engines, access_modes
                FROM access_policies
                WHERE active = 1
                  AND domain_partition = ?
                  AND (resource_type = ? OR resource_type = 'ALL');
                """,
                (domain_partition.value, resource_type),
            )
            rows = cursor.fetchall()

            for row in rows:
                policy_id = row["policy_id"]
                permitted_engines = json.loads(row["permitted_engines"])
                access_modes = json.loads(row["access_modes"])

                if (
                    requesting_engine in permitted_engines
                    and access_mode.value in access_modes
                ):
                    return True, policy_id

        return False, None

    def assert_access(
        self,
        requesting_engine: str,
        resource_type: str,
        domain_partition: DomainPartition,
        access_mode: AccessAction,
        actor_session: str = "00000000-0000-0000-0000-000000000000",
        target_id: str = "UNKNOWN",
    ) -> str:
        """
        Asserts that requesting_engine has permission.
        Logs ACCESS_DENIED or ACCESS_GRANTED to audit log.
        Raises MemoryAccessDeniedError if denied.
        """
        allowed, policy_id = self.check_access_policy(
            requesting_engine, resource_type, domain_partition, access_mode
        )

        now_iso = datetime.now(timezone.utc).isoformat()
        audit_id = str(uuid.uuid4())

        # Write audit event in a quick write transaction
        with self.factory.write_transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO audit_events (
                    audit_id, event_type, target_id, target_type, actor_engine,
                    actor_session, old_state, new_state, event_at, policy_id
                ) VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?);
                """,
                (
                    audit_id,
                    "ACCESS_GRANTED" if allowed else "ACCESS_DENIED",
                    target_id,
                    resource_type,
                    requesting_engine,
                    actor_session,
                    now_iso,
                    policy_id,
                ),
            )

        if not allowed:
            raise MemoryAccessDeniedError(
                f"Access DENIED: Engine '{requesting_engine}' is not authorized to "
                f"perform '{access_mode.value}' on '{resource_type}' in partition '{domain_partition.value}'."
            )

        return policy_id

    def log_audit_event_in_tx(
        self,
        cursor: sqlite3.Cursor,
        event_type: str,
        target_id: str,
        target_type: str,
        actor_engine: str,
        actor_session: str,
        policy_id: Optional[str] = None,
        old_state: Optional[Dict[str, Any]] = None,
        new_state: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Writes an immutable audit log row within an existing active transaction (MEM-015).
        """
        audit_id = str(uuid.uuid4())
        now_iso = datetime.now(timezone.utc).isoformat()
        cursor.execute(
            """
            INSERT INTO audit_events (
                audit_id, event_type, target_id, target_type, actor_engine,
                actor_session, old_state, new_state, event_at, policy_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                audit_id,
                event_type,
                target_id,
                target_type,
                actor_engine,
                actor_session,
                json.dumps(old_state) if old_state else None,
                json.dumps(new_state) if new_state else None,
                now_iso,
                policy_id,
            ),
        )
        return audit_id

    def create_claim_from_proposal(
        self,
        proposal: ProposedClaim,
        session_id: uuid.UUID,
        domain_partition: DomainPartition,
        source_experience_id: Optional[uuid.UUID] = None,
        world_time_start: Optional[datetime] = None,
        world_time_end: Optional[datetime] = None,
    ) -> MemoryClaim:
        """
        Transforms a candidate ProposedClaim into a persistent MemoryClaim.
        Assigns a new UUID and calculates a tamper-evident provenance_hash.
        External engines CANNOT supply claim UUIDs.
        """
        claim_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        # Compute provenance hash: SHA-256(canonical_statement + source_engine + diva_time)
        prov_raw = f"{proposal.canonical_statement}|{proposal.source_engine}|{now.isoformat()}"
        provenance_hash = hashlib.sha256(prov_raw.encode("utf-8")).hexdigest()

        return MemoryClaim(
            claim_id=claim_id,
            subject_entity_id=proposal.subject_entity_id,
            predicate=proposal.predicate,
            object_value=proposal.object_value,
            canonical_statement=proposal.canonical_statement,
            epistemic_type=proposal.epistemic_type,
            evidence_status=EvidenceStatus.UNVERIFIED,
            lifecycle=ClaimLifecycle.ACTIVE,
            domain_partition=domain_partition,
            source_engine=proposal.source_engine,
            source_session_id=session_id,
            source_experience_id=source_experience_id,
            world_time_start=world_time_start,
            world_time_end=world_time_end,
            diva_time_recorded=now,
            provenance_hash=provenance_hash,
            version=1,
        )
