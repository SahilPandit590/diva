"""
Bounded development runner and anti-recursion protocol for Diva Memory Engine v3.0.
Enforces MEM-012: Prevents infinite development loops via depth capping and circuit breakers.
"""

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from memory_engine.database.connection import DatabaseConnectionFactory
from memory_engine.types.development import DevelopmentRequest, ResourceBudget
from memory_engine.types.enums import DevelopmentOperationType


class DevelopmentDepthExceededError(ValueError):
    """Raised when a development operation exceeds the maximum allowed recursion depth (MEM-012)."""
    pass


class DevelopmentRateLimitError(ValueError):
    """Raised when the circuit breaker triggers due to excessive development requests for the same target."""
    pass


class BoundedDevelopmentRunner:
    """
    Guarantees that memory development chains terminate.
    Enforces maximum processing depth, idempotency hashing, and rate-limiting circuit breakers.
    """

    MAX_DEPTH_LIMIT = 10
    CIRCUIT_BREAKER_MAX_JOBS = 5
    CIRCUIT_BREAKER_WINDOW_HOURS = 24

    def __init__(self, factory: DatabaseConnectionFactory):
        self.factory = factory

    @classmethod
    def compute_idempotency_key(
        cls,
        operation_type: DevelopmentOperationType,
        target_memory_ids: List[uuid.UUID],
        development_objective: str,
    ) -> str:
        """
        Computes deterministic SHA-256 idempotency key:
          SHA-256(operation_type + sorted(target_memory_ids) + development_objective)
        """
        sorted_ids = sorted(str(m) for m in target_memory_ids)
        raw = f"{operation_type.value}|{','.join(sorted_ids)}|{development_objective.strip()}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def validate_and_prepare_request(
        self,
        operation_type: DevelopmentOperationType,
        initiating_subsystem: str,
        development_objective: str,
        target_memory_ids: Optional[List[uuid.UUID]] = None,
        target_claim_ids: Optional[List[uuid.UUID]] = None,
        requesting_engine: Optional[str] = None,
        parent_operation_id: Optional[uuid.UUID] = None,
        current_depth: int = 0,
        max_processing_depth: int = 5,
        priority: int = 5,
    ) -> DevelopmentRequest:
        """
        Validates recursion depth and circuit breaker before returning a frozen DevelopmentRequest.
        """
        # 1. Depth check (MEM-012)
        effective_max = min(max_processing_depth, self.MAX_DEPTH_LIMIT)
        if current_depth >= effective_max:
            raise DevelopmentDepthExceededError(
                f"Development recursion depth exceeded (MEM-012): Current depth {current_depth} "
                f"meets or exceeds limit of {effective_max}."
            )

        target_mems = target_memory_ids or []
        target_claims = target_claim_ids or []

        # 2. Circuit Breaker Check: Max 5 jobs per 24 hours per target memory set
        if target_mems:
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=self.CIRCUIT_BREAKER_WINDOW_HOURS)).isoformat()
            target_json = json.dumps(sorted(str(m) for m in target_mems))
            with self.factory.read_cursor() as cursor:
                cursor.execute(
                    """
                    SELECT count(*) FROM development_requests
                    WHERE operation_type = ?
                      AND target_memory_ids = ?
                      AND requested_at >= ?;
                    """,
                    (operation_type.value, target_json, cutoff),
                )
                recent_count = cursor.fetchone()[0]
                if recent_count >= self.CIRCUIT_BREAKER_MAX_JOBS:
                    raise DevelopmentRateLimitError(
                        f"Circuit breaker triggered: Already executed {recent_count} {operation_type.value} "
                        f"operations for these target memories in the past 24 hours."
                    )

        # 3. Idempotency Key
        idempotency_key = self.compute_idempotency_key(
            operation_type=operation_type,
            target_memory_ids=target_mems,
            development_objective=development_objective,
        )

        now = datetime.now(timezone.utc)
        return DevelopmentRequest(
            request_id=uuid.uuid4(),
            operation_type=operation_type,
            initiating_subsystem=initiating_subsystem,
            requesting_engine=requesting_engine,
            target_memory_ids=tuple(target_mems),
            target_claim_ids=tuple(target_claims),
            development_objective=development_objective,
            parent_operation_id=parent_operation_id,
            processing_depth=current_depth,
            max_processing_depth=effective_max,
            resource_budget=ResourceBudget(),
            idempotency_key=idempotency_key,
            priority=priority,
            requested_at=now,
        )
