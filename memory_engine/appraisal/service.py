"""
Appraisal Service for Diva Memory Engine v3.0.
Manages cognitive appraisals submitted by specialized engines (Emotion, Social Cognition, Thought)
and maintains immutable appraisal version histories.
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from memory_engine.database.connection import DatabaseConnectionFactory
from memory_engine.governance.service import MemoryGovernanceService
from memory_engine.jobs.outbox import emit_outbox_event_in_tx
from memory_engine.types.enums import AccessAction, DomainPartition


class AppraisalService:
    """
    Subsystem 7 (Appraisal Domain): Manages multi-engine cognitive appraisals.
    An appraisal is NOT a property of an experience, but an interpretative contribution
    from the specialized engine that owns that domain (Emotion, Social Cognition, etc.).
    """

    def __init__(
        self,
        factory: DatabaseConnectionFactory,
        governance: MemoryGovernanceService,
    ):
        self.factory = factory
        self.governance = governance

    def submit_appraisal(
        self,
        experience_id: uuid.UUID,
        appraising_engine: str,
        appraisal_type: str,  # "EMOTIONAL" | "SOCIAL" | "COGNITIVE" | "PROCEDURAL"
        appraisal_content: Dict[str, Any],
        confidence: float,
        session_id: uuid.UUID,
        domain_partition: DomainPartition = DomainPartition.COGNITIVE,
    ) -> uuid.UUID:
        """
        Submits an appraisal contribution for an experience.
        If an active appraisal exists for this engine & type, archives it to appraisal_history
        and creates a new version (MEM-001, MEM-002 provenance).
        """
        # Governance authorization check
        self.governance.assert_access(
            requesting_engine=appraising_engine,
            resource_type="MEMORY",
            domain_partition=domain_partition,
            access_mode=AccessAction.WRITE,
            actor_session=str(session_id),
            target_id=str(experience_id),
        )

        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        content_json = json.dumps(appraisal_content)

        with self.factory.write_transaction() as cursor:
            # 1. Check for existing active appraisal from this engine and type
            cursor.execute(
                """
                SELECT appraisal_id, version, appraisal_content FROM memory_appraisals
                WHERE experience_id = ? AND appraising_engine = ? AND appraisal_type = ?
                  AND superseded = 0;
                """,
                (str(experience_id), appraising_engine, appraisal_type),
            )
            existing = cursor.fetchone()

            if existing:
                appraisal_id = uuid.UUID(existing["appraisal_id"])
                new_version = existing["version"] + 1

                # Record old state in appraisal_history
                cursor.execute(
                    """
                    INSERT INTO appraisal_history (
                        history_id, appraisal_id, version_number, content_snapshot,
                        recorded_at, reason
                    ) VALUES (?, ?, ?, ?, ?, 'Reappraisal submission');
                    """,
                    (
                        str(uuid.uuid4()),
                        str(appraisal_id),
                        existing["version"],
                        existing["appraisal_content"],
                        now_iso,
                    ),
                )

                # Update current active appraisal
                cursor.execute(
                    """
                    UPDATE memory_appraisals
                    SET appraisal_content = ?,
                        confidence = ?,
                        appraised_at = ?,
                        session_id = ?,
                        version = ?
                    WHERE appraisal_id = ?;
                    """,
                    (
                        content_json,
                        confidence,
                        now_iso,
                        str(session_id),
                        new_version,
                        str(appraisal_id),
                    ),
                )
            else:
                appraisal_id = uuid.uuid4()
                cursor.execute(
                    """
                    INSERT INTO memory_appraisals (
                        appraisal_id, experience_id, appraising_engine, appraisal_type,
                        appraisal_content, confidence, appraised_at, session_id,
                        version, superseded
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 0);
                    """,
                    (
                        str(appraisal_id),
                        str(experience_id),
                        appraising_engine,
                        appraisal_type,
                        content_json,
                        confidence,
                        now_iso,
                        str(session_id),
                    ),
                )

            # 2. Emit outbox event
            emit_outbox_event_in_tx(
                cursor=cursor,
                event_name="memory.appraisal_recorded",
                event_payload={
                    "appraisal_id": str(appraisal_id),
                    "experience_id": str(experience_id),
                    "appraising_engine": appraising_engine,
                    "appraisal_type": appraisal_type,
                },
                source_engine=appraising_engine,
            )

            # 3. Log audit event
            self.governance.log_audit_event_in_tx(
                cursor=cursor,
                event_type="CLAIM_ASSESSMENT_ADDED",
                target_id=str(appraisal_id),
                target_type="APPRAISAL",
                actor_engine=appraising_engine,
                actor_session=str(session_id),
                new_state={"type": appraisal_type, "confidence": confidence},
            )

        return appraisal_id

    def get_appraisals(
        self,
        experience_id: uuid.UUID,
        appraisal_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieves active appraisals for a given experience record."""
        with self.factory.read_cursor() as cursor:
            if appraisal_type:
                cursor.execute(
                    """
                    SELECT appraisal_id, experience_id, appraising_engine, appraisal_type,
                           appraisal_content, confidence, appraised_at, version
                    FROM memory_appraisals
                    WHERE experience_id = ? AND appraisal_type = ? AND superseded = 0;
                    """,
                    (str(experience_id), appraisal_type),
                )
            else:
                cursor.execute(
                    """
                    SELECT appraisal_id, experience_id, appraising_engine, appraisal_type,
                           appraisal_content, confidence, appraised_at, version
                    FROM memory_appraisals
                    WHERE experience_id = ? AND superseded = 0;
                    """,
                    (str(experience_id),),
                )

            rows = cursor.fetchall()

        results = []
        for r in rows:
            results.append({
                "appraisal_id": r["appraisal_id"],
                "experience_id": r["experience_id"],
                "engine": r["appraising_engine"],
                "type": r["appraisal_type"],
                "content": json.loads(r["appraisal_content"]),
                "confidence": r["confidence"],
                "appraised_at": r["appraised_at"],
                "version": r["version"],
            })
        return results

    def get_appraisal_history(self, appraisal_id: uuid.UUID) -> List[Dict[str, Any]]:
        """Retrieves past versions of an appraisal from appraisal_history."""
        with self.factory.read_cursor() as cursor:
            cursor.execute(
                """
                SELECT version_number, content_snapshot, recorded_at, reason
                FROM appraisal_history
                WHERE appraisal_id = ?
                ORDER BY version_number ASC;
                """,
                (str(appraisal_id),),
            )
            rows = cursor.fetchall()

        return [
            {
                "version": r["version_number"],
                "content": json.loads(r["content_snapshot"]),
                "recorded_at": r["recorded_at"],
                "reason": r["reason"],
            }
            for r in rows
        ]
