"""
Epistemic preserver and hierarchy enforcement for Diva Memory Engine v3.0.
Enforces MEM-003: Epistemic types cannot be upgraded silently during intake or consolidation.
"""

from memory_engine.governance.exceptions import EpistemicDowngradeError
from memory_engine.types.enums import EpistemicType


class EpistemicPreserver:
    """
    Validates and preserves epistemic integrity across intake and consolidation.
    Hierarchy: OBSERVATION(5) > INFERENCE(4) > REPORTED(3) > INTERPRETATION(2) > OPINION(1) > UNKNOWN(0)
    """

    @staticmethod
    def validate_epistemic_assignment(
        source_type: EpistemicType, assigned_type: EpistemicType
    ) -> None:
        """
        Validates that assigned_type does not illegally upgrade epistemic authority.
        An INTERPRETATION cannot become an OBSERVATION.
        A REPORTED claim cannot become an OBSERVATION.
        """
        if assigned_type.rank > source_type.rank:
            raise EpistemicDowngradeError(
                f"Epistemic violation (MEM-003): Cannot upgrade epistemic rank from "
                f"{source_type.value} (rank {source_type.rank}) to "
                f"{assigned_type.value} (rank {assigned_type.rank})."
            )

    @staticmethod
    def resolve_source_epistemic(
        source_engine: str, explicit_type: EpistemicType | None = None
    ) -> EpistemicType:
        """
        Resolves the appropriate epistemic type based on submitting engine defaults.
        """
        if explicit_type is not None:
            return explicit_type

        # Engine defaults
        if source_engine == "PERCEPTION":
            return EpistemicType.OBSERVATION
        elif source_engine in ("THOUGHT", "REASONING"):
            return EpistemicType.INFERENCE
        elif source_engine in ("EMOTION", "SOCIAL_COGNITION"):
            return EpistemicType.INTERPRETATION
        elif source_engine in ("USER", "SYSTEM"):
            return EpistemicType.REPORTED
        return EpistemicType.UNKNOWN
