"""
Background job worker loop for Diva Memory Engine v3.0.
Executes leased background tasks with fault tolerance and idempotency.
"""

import uuid
from typing import Optional

from memory_engine.database.connection import DatabaseConnectionFactory
from memory_engine.entities.service import EntityAssociationService
from memory_engine.jobs.handlers import JobHandlers
from memory_engine.jobs.scheduler import BackgroundJobScheduler


class MemoryJobWorker:
    """
    Worker process leasing and executing background tasks.
    Enforces that workers maintain heartbeats and report completion/failures.
    """

    def __init__(
        self,
        factory: DatabaseConnectionFactory,
        scheduler: BackgroundJobScheduler,
        entities: EntityAssociationService,
        worker_id: Optional[str] = None,
    ):
        self.factory = factory
        self.scheduler = scheduler
        self.handlers = JobHandlers(factory, entities)
        self.worker_id = worker_id or f"worker_{uuid.uuid4().hex[:8]}"

    def run_once(self) -> bool:
        """
        Attempts to acquire and process a single pending background job.
        Returns True if a job was processed, False if queue was empty.
        """
        job = self.scheduler.acquire_next_job(worker_id=self.worker_id, lease_duration_seconds=30)
        if not job:
            return False

        job_id = job["job_id"]
        job_type = job["job_type"]
        input_data = job["input_data"]

        try:
            if job_type == "FTS5_INDEXING":
                result = self.handlers.handle_fts5_indexing(input_data)
            elif job_type == "ENTITY_LINKING":
                result = self.handlers.handle_entity_linking(input_data)
            else:
                result = {"status": "SKIPPED", "reason": f"Unknown job type: {job_type}"}

            self.scheduler.complete_job(job_id=job_id, worker_id=self.worker_id, result_data=result)
            return True
        except Exception as e:
            self.scheduler.fail_job(job_id=job_id, worker_id=self.worker_id, error_message=str(e))
            return True

    def process_all_pending(self, max_jobs: int = 100) -> int:
        """
        Processes pending jobs until the queue is drained or max_jobs is reached.
        Returns the number of jobs executed.
        """
        count = 0
        while count < max_jobs and self.run_once():
            count += 1
        return count
