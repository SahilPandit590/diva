"""
Experience Store Service — Section 5.2 of Memory Engine spec.
Provides FSM-gated experience lifecycle management, bitemporal snapshots,
and per-session / per-entity retrieval.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from memory_engine.database.connection import DatabaseConnectionFactory
from memory_engine.development.lifecycle import DevelopmentFSM
from memory_engine.governance.service import MemoryGovernanceService
from memory_engine.types.enums import DomainPartition, DevelopmentStatus


class ExperienceStoreService:
    """
    Section 5.2 — ExperienceStore subsystem.
    Owns experience reads, FSM-gated development-status transitions, and bitemporal queries.
    The intake pipeline writes experiences; this service manages their lifecycle after insertion.
    """

    def __init__(
        self,
        factory: DatabaseConnectionFactory,
        governance: MemoryGovernanceService,
    ) -> None:
        self.factory = factory
        self.governance = governance
        self._fsm = DevelopmentFSM()

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get_experience(self, experience_id: uuid.UUID) -> Optional[Dict[str, Any]]:
        """Fetch a single experience record by UUID. Returns None if not found."""
        with self.factory.read_cursor() as cursor:
            cursor.execute(
                "SELECT * FROM experiences WHERE experience_id = ?;",
                (str(experience_id),),
            )
            row = cursor.fetchone()
        if not row:
            return None
        return dict(row)

    def get_experiences_by_session(
        self, session_id: uuid.UUID, domain_partition: DomainPartition = DomainPartition.COGNITIVE
    ) -> List[Dict[str, Any]]:
        """Return all experiences recorded in a given session, ordered by time."""
        with self.factory.read_cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM experiences
                WHERE session_id = ? AND domain_partition = ?
                ORDER BY diva_time_recorded ASC;
                """,
                (str(session_id), domain_partition.value),
            )
            rows = cursor.fetchall()
        return [dict(r) for r in rows]

    def get_experiences_by_entity(
        self,
        entity_id: uuid.UUID,
        domain_partition: DomainPartition = DomainPartition.COGNITIVE,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Return experiences where the given entity appears as a participant.
        Uses JSON `participants` column via LIKE (the column stores a JSON array of UUIDs).
        """
        with self.factory.read_cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM experiences
                WHERE domain_partition = ?
                  AND participants LIKE ?
                ORDER BY diva_time_recorded DESC
                LIMIT ?;
                """,
                (domain_partition.value, f"%{entity_id}%", limit),
            )
            rows = cursor.fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Bitemporal snapshot — world_time axis
    # ------------------------------------------------------------------

    def get_bitemporal_snapshot(
        self,
        world_time: datetime,
        domain_partition: DomainPartition = DomainPartition.COGNITIVE,
    ) -> List[Dict[str, Any]]:
        """
        Return all experiences whose world-time interval contained `world_time`.
        Implements bitemporal Query A on the experience level:
          world_time_start <= T AND (world_time_end IS NULL OR world_time_end > T)
        """
        t_iso = world_time.isoformat()
        with self.factory.read_cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM experiences
                WHERE domain_partition = ?
                  AND (world_time_start IS NULL OR world_time_start <= ?)
                  AND (world_time_end IS NULL OR world_time_end > ?)
                ORDER BY diva_time_recorded DESC;
                """,
                (domain_partition.value, t_iso, t_iso),
            )
            rows = cursor.fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # FSM-gated status transition
    # ------------------------------------------------------------------

    def update_development_status(
        self,
        experience_id: uuid.UUID,
        new_status: DevelopmentStatus,
        actor_engine: str,
        session_id: uuid.UUID,
    ) -> Dict[str, Any]:
        """
        Transition an experience's development_status using the DevelopmentFSM.
        Raises ValueError if the transition is illegal.
        Writes audit event in the same transaction (MEM-015).
        Returns the updated experience dict.
        """
        # 1. Read current status
        exp = self.get_experience(experience_id)
        if exp is None:
            raise ValueError(f"Experience {experience_id} not found")

        current_status = DevelopmentStatus(exp["development_status"])

        # 2. FSM validation
        self._fsm.validate_transition(
            current_status,
            new_status,
        )

        now_iso = datetime.now(timezone.utc).isoformat()

        # 3. Apply update + audit in single transaction (MEM-015)
        with self.factory.write_transaction() as cursor:
            cursor.execute(
                """
                UPDATE experiences
                SET development_status = ?
                WHERE experience_id = ?;
                """,
                (new_status.value, str(experience_id)),
            )
            self.governance.log_audit_event_in_tx(
                cursor=cursor,
                event_type="EXPERIENCE_STATUS_UPDATED",
                target_id=str(experience_id),
                target_type="EXPERIENCE",
                actor_engine=actor_engine,
                actor_session=str(session_id),
                old_state={"development_status": current_status.value},
                new_state={"development_status": new_status.value},
            )

        # 4. Return refreshed record
        updated = self.get_experience(experience_id)
        assert updated is not None
        return updated
