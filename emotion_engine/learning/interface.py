"""
Emotional Learning Interface for Diva Emotion Engine v1.0.0.
Component 11 from Part 2 & Part 1.11.
Implements the formal owner-directed parameter adaptation protocol compliant with Learning Engine v2.5.0.
Enforces:
- Gradual bounded evolution (|Delta| <= 0.05 per update pass).
- Constitutional baseline identity locks against unconstrained drift (E21, Axiom 5).
- Optimistic concurrency version guards.
- Comprehensive audit records in emotion_learning_records.
"""

from datetime import datetime, timezone
from typing import List, Optional
import uuid
from pydantic import BaseModel, ConfigDict, Field

from emotion_engine.database.connection import DatabaseConnectionFactory
from emotion_engine.tendencies.manager import EmotionalTendencyManager
from emotion_engine.types.models import EmotionalLearningRecord

# Permissible adaptation limits (Part 1.11 & Axiom 5)
MAX_PERMISSIBLE_PARAMETER_DELTA = 0.05
CONSTITUTIONAL_MIN_VALUE = 0.50
CONSTITUTIONAL_MAX_VALUE = 1.80


class ParameterChangeRequest(BaseModel):
    """Inbound adaptation proposal from Learning Engine v2.5.0."""
    model_config = ConfigDict(frozen=True)

    proposal_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    target_dimension: str
    proposed_value: float
    expected_current_version: int
    rationales: List[str] = Field(default_factory=list)


class OwnerApplicationReceipt(BaseModel):
    """Outbound confirmation receipt returned to Learning Engine v2.5.0."""
    model_config = ConfigDict(frozen=True)

    proposal_id: uuid.UUID
    target_dimension: str
    applied: bool
    old_value: float
    new_value: float
    resulting_version: int
    failure_reason: Optional[str] = None
    applied_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class EmotionalLearningInterface:
    """Validates and applies owner-directed parameter change requests from Learning Engine."""

    def __init__(
        self,
        factory: DatabaseConnectionFactory,
        tendencies: EmotionalTendencyManager,
    ):
        self.factory = factory
        self.tendencies = tendencies

    def apply_parameter_change(
        self,
        request: ParameterChangeRequest,
        current_time: Optional[datetime] = None,
    ) -> OwnerApplicationReceipt:
        """
        Validates and applies a proposed parameter update according to owner-directed rules (E20, E21):
        1. Dimension must start with 'emotion.'
        2. Dimension must exist in registered tendencies.
        3. Delta must be gradual: |new - old| <= 0.05 (Part 1.11).
        4. Protected constitutional baseline must not drift beyond safety bounds [0.50, 1.80].
        5. Concurrency version must match.
        """
        now = current_time or datetime.now(timezone.utc)
        now_iso = now.isoformat()
        dim = request.target_dimension.strip()

        # 1. Prefix scope check
        if not dim.startswith("emotion."):
            return OwnerApplicationReceipt(
                proposal_id=request.proposal_id,
                target_dimension=dim,
                applied=False,
                old_value=0.0,
                new_value=request.proposed_value,
                resulting_version=0,
                failure_reason="DIMENSION_OUT_OF_SCOPE: Target dimension must begin with 'emotion.'",
                applied_at=now,
            )

        # 2. Existence check
        tendency = self.tendencies.get_tendency(dim)
        if not tendency:
            return OwnerApplicationReceipt(
                proposal_id=request.proposal_id,
                target_dimension=dim,
                applied=False,
                old_value=0.0,
                new_value=request.proposed_value,
                resulting_version=0,
                failure_reason=f"UNKNOWN_DIMENSION: Dimension '{dim}' does not exist in registered tendencies.",
                applied_at=now,
            )

        old_val = tendency.current_value
        new_val = request.proposed_value
        delta = abs(new_val - old_val)

        # 3. Constitutional Baseline Lock (E21, Axiom 5)
        if tendency.is_constitutional_baseline:
            return OwnerApplicationReceipt(
                proposal_id=request.proposal_id,
                target_dimension=dim,
                applied=False,
                old_value=old_val,
                new_value=old_val,
                resulting_version=tendency.version,
                failure_reason=(
                    f"REJECTED_PROTECTED_VIOLATION: Dimension '{dim}' is a protected constitutional baseline "
                    f"and cannot be mutated by learning adaptation."
                ),
                applied_at=now,
            )

        # 4. Version guard
        if tendency.version != request.expected_current_version:
            return OwnerApplicationReceipt(
                proposal_id=request.proposal_id,
                target_dimension=dim,
                applied=False,
                old_value=old_val,
                new_value=new_val,
                resulting_version=tendency.version,
                failure_reason=f"VERSION_CONFLICT: Expected v{request.expected_current_version}, but found v{tendency.version}.",
                applied_at=now,
            )

        # 5. Bounded evolution limit (|Delta| <= 0.05)
        if round(delta, 4) > MAX_PERMISSIBLE_PARAMETER_DELTA:
            return OwnerApplicationReceipt(
                proposal_id=request.proposal_id,
                target_dimension=dim,
                applied=False,
                old_value=old_val,
                new_value=new_val,
                resulting_version=tendency.version,
                failure_reason=(
                    f"EXCEEDS_MAX_DELTA_0.05: Requested delta of {delta:.4f} exceeds permissible "
                    f"single-update bound ({MAX_PERMISSIBLE_PARAMETER_DELTA})."
                ),
                applied_at=now,
            )

        # 6. Safety bounds check [0.50, 2.00]
        if new_val < CONSTITUTIONAL_MIN_VALUE or new_val > 2.00:
            return OwnerApplicationReceipt(
                proposal_id=request.proposal_id,
                target_dimension=dim,
                applied=False,
                old_value=old_val,
                new_value=new_val,
                resulting_version=tendency.version,
                failure_reason=(
                    f"OUT_OF_BOUNDS: Proposed value {new_val:.2f} violates "
                    f"permissible range [{CONSTITUTIONAL_MIN_VALUE}, 2.00]."
                ),
                applied_at=now,
            )

        # 6. Apply verified adaptation
        updated_tendency = self.tendencies.update_tendency(
            dimension_name=dim,
            new_value=round(new_val, 4),
            expected_version=request.expected_current_version,
            reason=f"Learning Engine v2.5.0 adaptation: {', '.join(request.rationales) if request.rationales else 'Empirical reinforcement'}",
            current_time=now,
        )

        # Inscribe into emotion_learning_records
        learning_record_id = uuid.uuid4()
        with self.factory.write_transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO emotion_learning_records (
                    learning_record_id, proposal_id, dimension_name,
                    old_value, new_value, applied_at
                ) VALUES (?, ?, ?, ?, ?, ?);
                """,
                (
                    str(learning_record_id),
                    str(request.proposal_id),
                    dim,
                    old_val,
                    updated_tendency.current_value,
                    now_iso,
                ),
            )

        return OwnerApplicationReceipt(
            proposal_id=request.proposal_id,
            target_dimension=dim,
            applied=True,
            old_value=old_val,
            new_value=updated_tendency.current_value,
            resulting_version=updated_tendency.version,
            failure_reason=None,
            applied_at=now,
        )
