"""
Continuity checkpoint manager for Diva Memory Engine v3.0.
Persists authorized snapshot references owned by other engines without inspecting private state.
"""

import json
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from memory_engine.database.connection import DatabaseConnectionFactory
from memory_engine.governance.service import MemoryGovernanceService
from memory_engine.jobs.outbox import emit_outbox_event_in_tx
from memory_engine.types.continuity import ContinuityCheckpoint
from memory_engine.types.enums import AccessAction, DomainPartition


class ContinuityEngine:
    """
    Subsystem 9: Memory Continuity.
    Persists and restores authorized cognitive state checkpoints.
    Enforces that cognitive and autonomous checkpoints are stored separately (MEM-014).
    """

    def __init__(
        self,
        factory: DatabaseConnectionFactory,
        governance: MemoryGovernanceService,
    ):
        self.factory = factory
        self.governance = governance

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
        """
        Creates an immutable checkpoint of cognitive state references.
        """
        self.governance.assert_access(
            requesting_engine=requesting_engine,
            resource_type="MEMORY",
            domain_partition=domain_partition,
            access_mode=AccessAction.WRITE,
            actor_session=str(session_id),
        )

        checkpoint_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()

        act_refs = [str(r) for r in (activity_snapshot_refs or [])]
        goal_refs = [str(r) for r in (active_goal_refs or [])]
        comm_refs = [str(r) for r in (unresolved_commitment_refs or [])]

        with self.factory.write_transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO continuity_checkpoints (
                    checkpoint_id, session_id, schema_version, workspace_snapshot_ref,
                    attention_snapshot_ref, activity_snapshot_refs, active_goal_refs,
                    unresolved_commitment_refs, created_at, valid, restoration_attempted,
                    domain_partition
                ) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, 1, 0, ?);
                """,
                (
                    str(checkpoint_id),
                    str(session_id),
                    str(workspace_snapshot_ref) if workspace_snapshot_ref else None,
                    str(attention_snapshot_ref) if attention_snapshot_ref else None,
                    json.dumps(act_refs),
                    json.dumps(goal_refs),
                    json.dumps(comm_refs),
                    now_iso,
                    domain_partition.value,
                ),
            )

            emit_outbox_event_in_tx(
                cursor=cursor,
                event_name="memory.checkpoint_created",
                event_payload={
                    "checkpoint_id": str(checkpoint_id),
                    "session_id": str(session_id),
                    "partition": domain_partition.value,
                },
                source_engine="MEMORY_CONTINUITY",
            )

        return ContinuityCheckpoint(
            checkpoint_id=checkpoint_id,
            session_id=session_id,
            schema_version=1,
            domain_partition=domain_partition,
            workspace_snapshot_ref=workspace_snapshot_ref,
            attention_snapshot_ref=attention_snapshot_ref,
            activity_snapshot_refs=tuple(activity_snapshot_refs or ()),
            active_goal_refs=tuple(active_goal_refs or ()),
            unresolved_commitment_refs=tuple(unresolved_commitment_refs or ()),
            created_at=now,
            valid=True,
            restoration_attempted=False,
            restoration_succeeded=None,
        )

    def restore_latest_checkpoint(
        self,
        session_id: uuid.UUID,
        domain_partition: DomainPartition = DomainPartition.COGNITIVE,
        requesting_engine: str = "COGNITIVE_INTEGRATION",
    ) -> Optional[ContinuityCheckpoint]:
        """
        Retrieves the most recent valid checkpoint for session and partition.
        """
        self.governance.assert_access(
            requesting_engine=requesting_engine,
            resource_type="MEMORY",
            domain_partition=domain_partition,
            access_mode=AccessAction.READ,
            actor_session=str(session_id),
        )

        with self.factory.read_cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM continuity_checkpoints
                WHERE session_id = ? AND domain_partition = ? AND valid = 1
                ORDER BY created_at DESC
                LIMIT 1;
                """,
                (str(session_id), domain_partition.value),
            )
            row = cursor.fetchone()
            if not row:
                return None

            checkpoint_id = row["checkpoint_id"]

        with self.factory.write_transaction() as cursor:
            cursor.execute(
                """
                UPDATE continuity_checkpoints
                SET restoration_attempted = 1, restoration_succeeded = 1
                WHERE checkpoint_id = ?;
                """,
                (checkpoint_id,),
            )

        return ContinuityCheckpoint(
            checkpoint_id=uuid.UUID(row["checkpoint_id"]),
            session_id=uuid.UUID(row["session_id"]),
            schema_version=row["schema_version"],
            domain_partition=DomainPartition(row["domain_partition"]),
            workspace_snapshot_ref=uuid.UUID(row["workspace_snapshot_ref"]) if row["workspace_snapshot_ref"] else None,
            attention_snapshot_ref=uuid.UUID(row["attention_snapshot_ref"]) if row["attention_snapshot_ref"] else None,
            activity_snapshot_refs=tuple(uuid.UUID(r) for r in json.loads(row["activity_snapshot_refs"])),
            active_goal_refs=tuple(uuid.UUID(r) for r in json.loads(row["active_goal_refs"])),
            unresolved_commitment_refs=tuple(uuid.UUID(r) for r in json.loads(row["unresolved_commitment_refs"])),
            created_at=datetime.fromisoformat(row["created_at"]),
            valid=bool(row["valid"]),
            restoration_attempted=True,
            restoration_succeeded=True,
        )
