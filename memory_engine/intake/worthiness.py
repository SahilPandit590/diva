"""
Worthiness scorer for Diva Memory Engine v3.0.
Determines which input events warrant persistent episodic experience creation.
"""

from typing import Dict, Any


class WorthinessScorer:
    """
    Scored decision table determining if an input event becomes a persistent experience.
    Weights: novelty(0.3) + source(0.2) + semantic(0.2) + flagged(0.2) + session(0.1)
    Threshold: score >= 0.45
    """

    THRESHOLD = 0.45

    SOURCE_WEIGHTS = {
        "PERCEPTION": 1.0,
        "INTERACTION": 0.9,
        "THOUGHT": 0.8,
        "REASONING": 0.8,
        "LEARNING": 0.75,
        "EMOTION": 0.7,
        "SOCIAL_COGNITION": 0.7,
        "AUTONOMOUS_ACTIVITY": 0.7,
        "SYSTEM": 0.6,
        "EXTERNAL_TOOL": 0.5,
    }

    @classmethod
    def evaluate(
        cls,
        source_engine: str,
        content: str,
        is_novel: bool = True,
        is_flagged_important: bool = False,
        in_active_session: bool = True,
    ) -> float:
        """Computes the composite worthiness score in [0.0, 1.0]."""
        novelty_score = 1.0 if is_novel else 0.0
        source_score = cls.SOURCE_WEIGHTS.get(source_engine.upper(), 0.5)

        # Semantic score heuristic based on length and information content
        words = len(content.split())
        if words > 15:
            semantic_score = 1.0
        elif words > 5:
            semantic_score = 0.7
        else:
            semantic_score = 0.3

        flagged_score = 1.0 if is_flagged_important else 0.0
        session_score = 0.8 if in_active_session else 0.2

        total_score = (
            0.30 * novelty_score
            + 0.20 * source_score
            + 0.20 * semantic_score
            + 0.20 * flagged_score
            + 0.10 * session_score
        )
        return round(total_score, 4)

    @classmethod
    def is_worthy(
        cls,
        source_engine: str,
        content: str,
        is_novel: bool = True,
        is_flagged_important: bool = False,
        in_active_session: bool = True,
    ) -> bool:
        """Returns True if score meets or exceeds threshold."""
        score = cls.evaluate(
            source_engine, content, is_novel, is_flagged_important, in_active_session
        )
        return score >= cls.THRESHOLD
