"""
Memory Intake Processing Pipeline for Diva Memory Engine v3.0.
Implements the 7-stage intake pipeline with idempotency (MEM-001) and epistemic tagging (MEM-003).
"""

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from memory_engine.database.connection import DatabaseConnectionFactory
from memory_engine.governance.service import MemoryGovernanceService
from memory_engine.intake.epistemic import EpistemicPreserver
from memory_engine.intake.worthiness import WorthinessScorer
from memory_engine.jobs.outbox import emit_outbox_event_in_tx
from memory_engine.jobs.scheduler import BackgroundJobScheduler
from memory_engine.types.enums import (
    AccessAction,
    DevelopmentStatus,
    DomainPartition,
    EpistemicType,
    RetentionStatus,
    ValidityStatus,
)


class MemoryIntakeService:
    """
    Executes the 7-stage Memory Intake Pipeline.
    Synchronous validation and persistence guarantees data durability;
    deep processing (entity linking, embedding, generalization) is scheduled asynchronously.
    """

    def __init__(
        self,
        factory: DatabaseConnectionFactory,
        governance: MemoryGovernanceService,
        scheduler: BackgroundJobScheduler,
    ):
        self.factory = factory
        self.governance = governance
        self.scheduler = scheduler

    def submit_input(
        self,
        source_engine: str,
        channel: str,
        domain_partition: DomainPartition,
        session_id: uuid.UUID,
        raw_content: str,
        experience_summary: Optional[str] = None,
        explicit_epistemic: Optional[EpistemicType] = None,
        importance_flag: bool = False,
        participants: Optional[List[uuid.UUID]] = None,
        world_time_start: Optional[datetime] = None,
        world_time_end: Optional[datetime] = None,
    ) -> Tuple[uuid.UUID, Optional[uuid.UUID], bool]:
        """
        Processes an incoming signal through the 7-stage pipeline.
        Returns: (event_id, experience_id_or_none, is_duplicate).
        """
        # =====================================================================
        # STAGE 1: INTAKE VALIDATION & PERMISSION CHECK
        # =====================================================================
        self.governance.assert_access(
            requesting_engine=source_engine,
            resource_type="MEMORY",
            domain_partition=domain_partition,
            access_mode=AccessAction.WRITE,
            actor_session=str(session_id),
        )

        content_bytes = raw_content.encode("utf-8")
        content_hash = hashlib.sha256(content_bytes).hexdigest()

        # Idempotency check (MEM-001): Have we seen this exact input in this session?
        with self.factory.read_cursor() as cursor:
            cursor.execute(
                """
                SELECT event_id, processed FROM input_events
                WHERE content_hash = ? AND session_id = ? AND source_engine = ?;
                """,
                (content_hash, str(session_id), source_engine),
            )
            existing_event = cursor.fetchone()
            if existing_event:
                event_id = uuid.UUID(existing_event["event_id"])
                # Look for existing experience
                cursor.execute(
                    "SELECT experience_id FROM experiences WHERE source_event_id = ?;",
                    (str(event_id),),
                )
                exp_row = cursor.fetchone()
                existing_exp_id = uuid.UUID(exp_row["experience_id"]) if exp_row else None
                return event_id, existing_exp_id, True

        event_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()

        # =====================================================================
        # STAGE 2: EPISTEMIC TAGGING (MEM-003)
        # =====================================================================
        epistemic = EpistemicPreserver.resolve_source_epistemic(
            source_engine=source_engine, explicit_type=explicit_epistemic
        )

        # =====================================================================
        # STAGE 3: EXPERIENCE WORTHINESS FILTER
        # =====================================================================
        is_worthy = WorthinessScorer.is_worthy(
            source_engine=source_engine,
            content=raw_content,
            is_novel=True,
            is_flagged_important=importance_flag,
            in_active_session=True,
        )

        with self.factory.write_transaction() as cursor:
            # Insert immutable input_event
            cursor.execute(
                """
                INSERT INTO input_events (
                    event_id, source_engine, channel, domain_partition,
                    session_id, raw_content, content_hash, received_at,
                    processed, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1);
                """,
                (
                    str(event_id),
                    source_engine,
                    channel,
                    domain_partition.value,
                    str(session_id),
                    raw_content,
                    content_hash,
                    now_iso,
                    1 if not is_worthy else 0,
                ),
            )

            if not is_worthy:
                # Discarded by worthiness filter: preserved in input_events only
                return event_id, None, False

            # =================================================================
            # STAGE 4: EXPERIENCE & PAYLOAD RECORD CREATION
            # =================================================================
            experience_id = uuid.uuid4()
            payload_id = uuid.uuid4()
            summary = experience_summary or (raw_content[:200] + "..." if len(raw_content) > 200 else raw_content)
            participants_list = [str(p) for p in (participants or [])]

            # Provenance hash: SHA-256(summary + participants + diva_time_recorded)
            prov_raw = f"{summary}|{json.dumps(participants_list)}|{now_iso}"
            provenance_hash = hashlib.sha256(prov_raw.encode("utf-8")).hexdigest()

            # Insert experience record
            cursor.execute(
                """
                INSERT INTO experiences (
                    experience_id, source_event_id, session_id, domain_partition,
                    experience_summary, participants, world_time_start, world_time_end,
                    diva_time_recorded, development_status, validity_status,
                    retention_status, permanent_importance, temporary_importance,
                    access_count, provenance_hash, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'RAW', 'CURRENT', 'ACTIVE', ?, 0.0, 0, ?, 1);
                """,
                (
                    str(experience_id),
                    str(event_id),
                    str(session_id),
                    domain_partition.value,
                    summary,
                    json.dumps(participants_list),
                    world_time_start.isoformat() if world_time_start else None,
                    world_time_end.isoformat() if world_time_end else None,
                    now_iso,
                    0.8 if importance_flag else 0.5,
                    provenance_hash,
                ),
            )

            # Insert experience payload
            cursor.execute(
                """
                INSERT INTO experience_payloads (
                    payload_id, experience_id, payload_format, payload_data,
                    content_hash, created_at, is_archived
                ) VALUES (?, ?, 'JSON', ?, ?, ?, 0);
                """,
                (
                    str(payload_id),
                    str(experience_id),
                    content_bytes,
                    content_hash,
                    now_iso,
                ),
            )

            # Mark input_event as processed
            cursor.execute(
                "UPDATE input_events SET processed = 1 WHERE event_id = ?;",
                (str(event_id),),
            )

            # =================================================================
            # STAGE 7: EVENT EMISSION & AUDIT (ATOMIC)
            # =================================================================
            emit_outbox_event_in_tx(
                cursor=cursor,
                event_name="memory.experience_persisted",
                event_payload={
                    "experience_id": str(experience_id),
                    "session_id": str(session_id),
                    "domain_partition": domain_partition.value,
                    "source_engine": source_engine,
                    "epistemic_type": epistemic.value,
                },
                source_engine="MEMORY_INTAKE",
            )

            self.governance.log_audit_event_in_tx(
                cursor=cursor,
                event_type="EXPERIENCE_CREATED",
                target_id=str(experience_id),
                target_type="EXPERIENCE",
                actor_engine=source_engine,
                actor_session=str(session_id),
                new_state={"summary": summary, "epistemic": epistemic.value},
            )

        # =====================================================================
        # STAGE 5 & 6: ASYNCHRONOUS DEEP PROCESSING JOBS
        # =====================================================================
        # 1. Schedule Entity Linking
        self.scheduler.schedule_job(
            job_type="ENTITY_LINKING",
            input_data={"experience_id": str(experience_id), "text": summary},
            idempotency_key=f"entity_linking:{experience_id}",
            priority=5,
        )

        # 2. Schedule FTS5 indexing
        self.scheduler.schedule_job(
            job_type="FTS5_INDEXING",
            input_data={
                "memory_id": str(experience_id),
                "summary": summary,
                "statements": "",
                "entities": "",
            },
            idempotency_key=f"fts_indexing:{experience_id}",
            priority=4,
        )

        return event_id, experience_id, False
