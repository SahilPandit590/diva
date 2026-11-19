"""
Emotion Classification Module for Diva Emotion Engine v1.0.0.
Component 4 from Part 2 & Part 1.3.
Classifies candidate emotional responses against the authoritative EmotionRegistry,
mapping primitives and evaluating constituent prerequisites for complex blends.
"""

from typing import List, Optional, Tuple
from emotion_engine.types.enums import EmotionType
from emotion_engine.types.registry import EMOTION_REGISTRY, EmotionDefinition


class EmotionClassificationModule:
    """Classifies and validates emotion categories against the registry."""

    @staticmethod
    def get_definition(category_name: str) -> Optional[EmotionDefinition]:
        """Looks up authoritative definition by name."""
        return EMOTION_REGISTRY.get(category_name)

    @staticmethod
    def is_primitive(category_name: str) -> bool:
        """Checks if category is an authoritative Primitive Emotion (12)."""
        edef = EMOTION_REGISTRY.get(category_name)
        return bool(edef and edef.emotion_type == EmotionType.PRIMITIVE)

    @staticmethod
    def is_complex(category_name: str) -> bool:
        """Checks if category is an authoritative Complex Emotion (18)."""
        edef = EMOTION_REGISTRY.get(category_name)
        return bool(edef and edef.emotion_type == EmotionType.COMPLEX)

    @classmethod
    def evaluate_complex_emergence(
        cls,
        complex_category: str,
        active_primitive_names: List[str],
    ) -> bool:
        """
        Evaluates whether an active set of primitive emotions fulfills the
        constituent prerequisites for complex emotion emergence.
        """
        edef = cls.get_definition(complex_category)
        if not edef or edef.emotion_type != EmotionType.COMPLEX:
            return False

        if not edef.constituent_primitives:
            return True

        active_upper = {p.strip().upper() for p in active_primitive_names}
        req_upper = {c.strip().upper() for c in edef.constituent_primitives}
        return req_upper.issubset(active_upper)
