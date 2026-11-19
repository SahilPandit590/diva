"""
Memory Development State Machine (FSM) for Diva Memory Engine v3.0.
Implements strict state transition rules defined in Section 3.9.
"""

from typing import Dict, List, Set
from memory_engine.types.enums import DevelopmentStatus


class InvalidStateTransitionError(ValueError):
    """Raised when an illegal memory development lifecycle transition is attempted."""
    pass


# Strict FSM transition table (Section 3.9)
VALID_TRANSITIONS: Dict[DevelopmentStatus, Set[DevelopmentStatus]] = {
    DevelopmentStatus.RAW: {DevelopmentStatus.ORGANIZED},
    DevelopmentStatus.ORGANIZED: {DevelopmentStatus.ASSOCIATED, DevelopmentStatus.ARCHIVED},
    DevelopmentStatus.ASSOCIATED: {DevelopmentStatus.PROPOSED, DevelopmentStatus.ACCEPTED, DevelopmentStatus.ARCHIVED},
    DevelopmentStatus.PROPOSED: {DevelopmentStatus.UNDER_REVIEW, DevelopmentStatus.ACCEPTED, DevelopmentStatus.ARCHIVED},
    DevelopmentStatus.UNDER_REVIEW: {DevelopmentStatus.ACCEPTED, DevelopmentStatus.DISPUTED},
    DevelopmentStatus.DISPUTED: {DevelopmentStatus.ACCEPTED, DevelopmentStatus.SUPERSEDED, DevelopmentStatus.ARCHIVED},
    DevelopmentStatus.ACCEPTED: {DevelopmentStatus.SUPERSEDED, DevelopmentStatus.ARCHIVED},
    DevelopmentStatus.SUPERSEDED: {DevelopmentStatus.ARCHIVED},
    DevelopmentStatus.ARCHIVED: set(),  # Terminal state (can only be un-archived via Retention Engine)
}


class DevelopmentFSM:
    """
    Finite State Machine validating knowledge development state transitions.
    """

    @staticmethod
    def can_transition(current: DevelopmentStatus, target: DevelopmentStatus) -> bool:
        """Returns True if transition from current to target is allowed."""
        return target in VALID_TRANSITIONS.get(current, set())

    @staticmethod
    def validate_transition(current: DevelopmentStatus, target: DevelopmentStatus) -> None:
        """
        Validates the transition.
        Raises InvalidStateTransitionError if the transition is prohibited.
        """
        if not DevelopmentFSM.can_transition(current, target):
            raise InvalidStateTransitionError(
                f"Invalid lifecycle transition: Cannot transition from {current.value} to {target.value}. "
                f"Allowed target states: {[s.value for s in VALID_TRANSITIONS.get(current, set())]}"
            )
