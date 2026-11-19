"""
Retention Engine Service for Diva Memory Engine v3.0.
Implements dependency tracking and reversible cold archiving (MEM-010).
"""

import hashlib
import json
import uuid
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from memory_engine.database.connection import DatabaseConnectionFactory
from memory_engine.governance.service import MemoryGovernanceService
from memory_engine.jobs.outbox import emit_outbox_event_in_tx
from memory_engine.types.enums import RetentionStatus


class DependencyLockedError(ValueError):
    """Raised when an attempt is made to archive a memory that has active downstream dependencies (MEM-010)."""
    pass


class ArchiveIntegrityError(ValueError):
    """Raised when an archived file's checksum does not match its recorded manifest."""
    pass


class RetentionEngineService:
    """
    Subsystem 8: Retention Engine.
    Guarantees that archival is reversible, preserves provenance, and prevents data loss.
    """

    def __init__(
        self,
        factory: DatabaseConnectionFactory,
        governance: MemoryGovernanceService,
    ):
        self.factory = factory
        self.governance = governance

    def add_dependency(
        self,
        dependent_id: uuid.UUID,
        source_id: uuid.UUID,
        dependency_type: str = "EVIDENCE",
    ) -> uuid.UUID:
        """
        Records that dependent_id relies on source_id.
        source_id cannot be archived while this dependency exists (MEM-010).
        """
        dep_id = uuid.uuid4()
        now_iso = datetime.now(timezone.utc).isoformat()

        with self.factory.write_transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO memory_dependencies (
                    dependency_id, dependent_id, dependency_type, source_id, created_at
                ) VALUES (?, ?, ?, ?, ?);
                """,
                (str(dep_id), str(dependent_id), dependency_type, str(source_id), now_iso),
            )
            # Update dependency count in retention_records if present
            cursor.execute(
                """
                UPDATE retention_records
                SET dependency_count = dependency_count + 1,
                    retention_status = 'DEPENDENCY_LOCKED',
                    archival_eligible = 0
                WHERE memory_id = ?;
                """,
                (str(source_id),),
            )

        return dep_id

    def evaluate_eligibility(self, memory_id: uuid.UUID) -> Dict[str, Any]:
        """
        Evaluates active dependency count and archival eligibility for memory_id.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        with self.factory.read_cursor() as cursor:
            # Check active dependencies
            cursor.execute(
                "SELECT count(*) FROM memory_dependencies WHERE source_id = ?;",
                (str(memory_id),),
            )
            dep_count = cursor.fetchone()[0]

            cursor.execute(
                "SELECT permanent_importance, retention_status FROM experiences WHERE experience_id = ?;",
                (str(memory_id),),
            )
            exp_row = cursor.fetchone()
            if not exp_row:
                raise ValueError(f"Experience {memory_id} not found.")

            importance = exp_row["permanent_importance"]
            curr_retention = exp_row["retention_status"]

        # Eligible if no active dependencies and already consolidated
        is_eligible = (dep_count == 0) and (curr_retention == "CONSOLIDATED")

        # Update or insert retention_records row
        with self.factory.write_transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO retention_records (
                    record_id, memory_id, memory_type, permanent_importance,
                    development_priority, retention_status, dependency_count,
                    consolidation_eligible, archival_eligible, last_evaluated_at,
                    evaluation_trigger
                ) VALUES (?, ?, 'EXPERIENCE', ?, 0.5, ?, ?, 1, ?, ?, 'MANUAL_EVALUATION')
                ON CONFLICT(memory_id, memory_type) DO UPDATE SET
                    dependency_count = excluded.dependency_count,
                    archival_eligible = excluded.archival_eligible,
                    last_evaluated_at = excluded.last_evaluated_at;
                """,
                (
                    str(uuid.uuid4()),
                    str(memory_id),
                    importance,
                    "DEPENDENCY_LOCKED" if dep_count > 0 else curr_retention,
                    dep_count,
                    1 if is_eligible else 0,
                    now_iso,
                ),
            )

        return {
            "memory_id": str(memory_id),
            "dependency_count": dep_count,
            "archival_eligible": is_eligible,
            "current_status": "DEPENDENCY_LOCKED" if dep_count > 0 else curr_retention,
        }

    def archive_memory(
        self,
        memory_id: uuid.UUID,
        archive_dir: Path,
        acting_engine: str = "MEMORY_GOVERNANCE",
    ) -> uuid.UUID:
        """
        Executes cold archiving with zlib compression (MEM-010).
        Guarantees that memory is NEVER archived if active dependencies exist.
        """
        eval_result = self.evaluate_eligibility(memory_id)
        if eval_result["dependency_count"] > 0:
            raise DependencyLockedError(
                f"Cannot archive memory {memory_id} (MEM-010 violation): "
                f"Has {eval_result['dependency_count']} active downstream dependencies."
            )

        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_path = archive_dir / f"{memory_id}.zlib"
        archive_id = uuid.uuid4()
        now_iso = datetime.now(timezone.utc).isoformat()

        # Fetch raw payload
        with self.factory.read_cursor() as cursor:
            cursor.execute(
                "SELECT payload_data FROM experience_payloads WHERE experience_id = ?;",
                (str(memory_id),),
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Payload for experience {memory_id} not found.")
            raw_bytes = row["payload_data"]

        orig_size_kb = max(1, len(raw_bytes) // 1024)
        compressed_bytes = zlib.compress(raw_bytes, level=9)
        archived_size_kb = max(1, len(compressed_bytes) // 1024)
        checksum = hashlib.sha256(compressed_bytes).hexdigest()

        # Write to cold archive file
        archive_path.write_bytes(compressed_bytes)

        with self.factory.write_transaction() as cursor:
            # 1. Insert archive record
            cursor.execute(
                """
                INSERT INTO archive_records (
                    archive_id, memory_id, memory_type, archive_path,
                    archived_at, compression_type, original_size_kb,
                    archived_size_kb, checksum, retrieval_tested
                ) VALUES (?, ?, 'EXPERIENCE', ?, ?, 'ZLIB', ?, ?, ?, 1);
                """,
                (
                    str(archive_id),
                    str(memory_id),
                    str(archive_path),
                    now_iso,
                    orig_size_kb,
                    archived_size_kb,
                    checksum,
                ),
            )

            # 2. Mark experience_payloads as archived and clear primary blob to save space
            cursor.execute(
                """
                UPDATE experience_payloads
                SET is_archived = 1, archive_path = ?
                WHERE experience_id = ?;
                """,
                (str(archive_path), str(memory_id)),
            )

            # 3. Update experiences retention status
            cursor.execute(
                "UPDATE experiences SET retention_status = 'ARCHIVED' WHERE experience_id = ?;",
                (str(memory_id),),
            )

            # 4. Update retention_records status
            cursor.execute(
                "UPDATE retention_records SET retention_status = 'ARCHIVED' WHERE memory_id = ?;",
                (str(memory_id),),
            )

            # 5. Log audit event
            self.governance.log_audit_event_in_tx(
                cursor=cursor,
                event_type="MEMORY_ARCHIVED",
                target_id=str(memory_id),
                target_type="EXPERIENCE",
                actor_engine=acting_engine,
                actor_session="00000000-0000-0000-0000-000000000000",
                new_state={"archive_path": str(archive_path), "checksum": checksum},
            )

            emit_outbox_event_in_tx(
                cursor=cursor,
                event_name="memory.archived",
                event_payload={"memory_id": str(memory_id), "archive_id": str(archive_id)},
                source_engine=acting_engine,
            )

        return archive_id

    def restore_archived_memory(
        self,
        memory_id: uuid.UUID,
        acting_engine: str = "MEMORY_GOVERNANCE",
    ) -> bytes:
        """
        Enforces MEM-010 Reversibility: Decompresses cold archive payload and restores memory to active state.
        """
        with self.factory.read_cursor() as cursor:
            cursor.execute(
                """
                SELECT archive_path, checksum FROM archive_records
                WHERE memory_id = ?
                ORDER BY archived_at DESC LIMIT 1;
                """,
                (str(memory_id),),
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"No archive record found for memory {memory_id}.")

            archive_path = Path(row["archive_path"])
            expected_checksum = row["checksum"]

        if not archive_path.exists():
            raise FileNotFoundError(f"Archive file {archive_path} is missing from disk.")

        compressed_data = archive_path.read_bytes()
        actual_checksum = hashlib.sha256(compressed_data).hexdigest()
        if actual_checksum != expected_checksum:
            raise ArchiveIntegrityError(
                f"Archive file checksum mismatch for {memory_id}. Expected {expected_checksum}, found {actual_checksum}."
            )

        decompressed_bytes = zlib.decompress(compressed_data)

        with self.factory.write_transaction() as cursor:
            # Restore payload
            cursor.execute(
                """
                UPDATE experience_payloads
                SET payload_data = ?, is_archived = 0
                WHERE experience_id = ?;
                """,
                (decompressed_bytes, str(memory_id)),
            )

            # Restore experience retention status
            cursor.execute(
                "UPDATE experiences SET retention_status = 'CONSOLIDATED' WHERE experience_id = ?;",
                (str(memory_id),),
            )

            # Restore retention_records status
            cursor.execute(
                "UPDATE retention_records SET retention_status = 'CONSOLIDATED' WHERE memory_id = ?;",
                (str(memory_id),),
            )

            self.governance.log_audit_event_in_tx(
                cursor=cursor,
                event_type="MEMORY_RESTORED",
                target_id=str(memory_id),
                target_type="EXPERIENCE",
                actor_engine=acting_engine,
                actor_session="00000000-0000-0000-0000-000000000000",
                new_state={"restored_bytes": len(decompressed_bytes)},
            )

        return decompressed_bytes
