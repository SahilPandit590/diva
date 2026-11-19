"""
Background job scheduler and lease management for Diva Memory Engine v3.0.
Ensures distributed worker safety via leasing, idempotency, and crash recovery.
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from memory_engine.database.connection import DatabaseConnectionFactory
from memory_engine.types.enums import JobStatus  # noqa: F401 – used for status literals


class BackgroundJobScheduler:
    """
    Manages asynchronous background jobs in background_jobs table.
    Enforces idempotency keys, worker lease acquisition with heartbeats,
    and automatic recovery of abandoned/crashed worker leases.
    """

    def __init__(self, factory: DatabaseConnectionFactory):
        self.factory = factory

    def schedule_job(
        self,
        job_type: str,
        input_data: Dict[str, Any],
        idempotency_key: str,
        priority: int = 5,
        max_attempts: int = 3,
        scheduled_at: Optional[datetime] = None,
    ) -> Tuple[str, bool]:
        """
        Schedules a background job.
        If idempotency_key already exists, returns (existing_job_id, False).
        Returns (new_job_id, True) on newly scheduled job.
        """
        now = datetime.now(timezone.utc)
        sched_iso = scheduled_at.isoformat() if scheduled_at else now.isoformat()

        # Check existing idempotency_key
        with self.factory.read_cursor() as cursor:
            cursor.execute(
                "SELECT job_id FROM background_jobs WHERE idempotency_key = ?;",
                (idempotency_key,),
            )
            row = cursor.fetchone()
            if row:
                return row["job_id"], False

        job_id = str(uuid.uuid4())
        with self.factory.write_transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO background_jobs (
                    job_id, job_type, input_data, status, priority,
                    max_attempts, attempt_count, idempotency_key,
                    created_at, scheduled_at
                ) VALUES (?, ?, ?, 'PENDING', ?, ?, 0, ?, ?, ?);
                """,
                (
                    job_id,
                    job_type,
                    json.dumps(input_data),
                    priority,
                    max_attempts,
                    idempotency_key,
                    now.isoformat(),
                    sched_iso,
                ),
            )
        return job_id, True

    def acquire_next_job(
        self, worker_id: str, lease_duration_seconds: int = 60
    ) -> Optional[Dict[str, Any]]:
        """
        Attempts to lease the highest-priority pending or expired job.
        Returns job details dictionary if acquired, None otherwise.
        """
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        expires_at = (now + timedelta(seconds=lease_duration_seconds)).isoformat()

        with self.factory.write_transaction() as cursor:
            # 1. Clean up expired leases and reset jobs to PENDING if attempts remain
            cursor.execute(
                """
                SELECT l.job_id, l.lease_id, j.attempt_count, j.max_attempts
                FROM background_leases l
                JOIN background_jobs j ON j.job_id = l.job_id
                WHERE l.expires_at < ?;
                """,
                (now_iso,),
            )
            expired_leases = cursor.fetchall()
            for row in expired_leases:
                cursor.execute(
                    "DELETE FROM background_leases WHERE lease_id = ?;",
                    (row["lease_id"],),
                )
                if row["attempt_count"] < row["max_attempts"]:
                    cursor.execute(
                        "UPDATE background_jobs SET status = 'PENDING' WHERE job_id = ?;",
                        (row["job_id"],),
                    )
                else:
                    cursor.execute(
                        """
                        UPDATE background_jobs 
                        SET status = 'DEAD_LETTER', error_message = 'Lease expired and max attempts exceeded'
                        WHERE job_id = ?;
                        """,
                        (row["job_id"],),
                    )

            # 2. Select next ready job (status = PENDING, scheduled_at <= now)
            cursor.execute(
                """
                SELECT job_id, job_type, input_data, priority, attempt_count, max_attempts
                FROM background_jobs
                WHERE status = 'PENDING'
                  AND (scheduled_at IS NULL OR scheduled_at <= ?)
                ORDER BY priority ASC, created_at ASC
                LIMIT 1;
                """,
                (now_iso,),
            )
            candidate = cursor.fetchone()
            if not candidate:
                return None

            job_id = candidate["job_id"]
            lease_id = str(uuid.uuid4())

            # 3. Mark job RUNNING and create lease
            cursor.execute(
                """
                UPDATE background_jobs
                SET status = 'RUNNING',
                    started_at = ?,
                    attempt_count = attempt_count + 1
                WHERE job_id = ?;
                """,
                (now_iso, job_id),
            )
            cursor.execute(
                """
                INSERT INTO background_leases (
                    lease_id, job_id, worker_id, acquired_at, expires_at, heartbeat_at
                ) VALUES (?, ?, ?, ?, ?, ?);
                """,
                (lease_id, job_id, worker_id, now_iso, expires_at, now_iso),
            )

            return {
                "lease_id": lease_id,
                "job_id": job_id,
                "job_type": candidate["job_type"],
                "input_data": json.loads(candidate["input_data"]),
                "priority": candidate["priority"],
                "attempt_count": candidate["attempt_count"] + 1,
            }

    def heartbeat(
        self, lease_id: str, worker_id: str, extension_seconds: int = 60
    ) -> bool:
        """Extends an active lease expiration time."""
        now = datetime.now(timezone.utc)
        expires_at = (now + timedelta(seconds=extension_seconds)).isoformat()
        with self.factory.write_transaction() as cursor:
            cursor.execute(
                """
                UPDATE background_leases
                SET expires_at = ?, heartbeat_at = ?
                WHERE lease_id = ? AND worker_id = ?;
                """,
                (expires_at, now.isoformat(), lease_id, worker_id),
            )
            return cursor.rowcount > 0

    def complete_job(
        self, job_id: str, worker_id: str, result_data: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Marks job COMPLETED and removes its lease."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with self.factory.write_transaction() as cursor:
            cursor.execute(
                "DELETE FROM background_leases WHERE job_id = ? AND worker_id = ?;",
                (job_id, worker_id),
            )
            cursor.execute(
                """
                UPDATE background_jobs
                SET status = 'COMPLETED',
                    completed_at = ?,
                    result_data = ?
                WHERE job_id = ?;
                """,
                (now_iso, json.dumps(result_data) if result_data else None, job_id),
            )
            return cursor.rowcount > 0

    def fail_job(
        self, job_id: str, worker_id: str, error_message: str
    ) -> bool:
        """Marks job FAILED or PENDING for retry and releases lease."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with self.factory.write_transaction() as cursor:
            cursor.execute(
                "DELETE FROM background_leases WHERE job_id = ? AND worker_id = ?;",
                (job_id, worker_id),
            )
            cursor.execute(
                """
                SELECT attempt_count, max_attempts FROM background_jobs WHERE job_id = ?;
                """,
                (job_id,),
            )
            row = cursor.fetchone()
            if row and row["attempt_count"] < row["max_attempts"]:
                cursor.execute(
                    """
                    UPDATE background_jobs
                    SET status = 'PENDING', error_message = ?
                    WHERE job_id = ?;
                    """,
                    (error_message, job_id),
                )
            else:
                # Section 3.11: exhausted all retries → DEAD_LETTER (not just FAILED)
                cursor.execute(
                    """
                    UPDATE background_jobs
                    SET status = 'DEAD_LETTER', completed_at = ?, error_message = ?
                    WHERE job_id = ?;
                    """,
                    (now_iso, error_message, job_id),
                )
            return True
