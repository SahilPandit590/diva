"""
Retrieval Intent Router and Greedy Token Budget Assembly for Diva Memory Engine v3.0.
Implements Sections 3.5, 3.6, and 3.7.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class RetrievalIntent(str, Enum):
    """Retrieval query intents determining layer weighting and filtering strategies."""
    FACTUAL = "FACTUAL"
    EPISODIC = "EPISODIC"
    TEMPORAL = "TEMPORAL"
    ASSOCIATIVE = "ASSOCIATIVE"
    AUTOBIOGRAPHICAL = "AUTOBIOGRAPHICAL"
    REFLECTIVE = "REFLECTIVE"
    RELATIONSHIP = "RELATIONSHIP"
    CONTRADICTION = "CONTRADICTION"
    GENERAL = "GENERAL"


# Layer weight mappings per intent (weights sum to 1.0)
INTENT_LAYER_WEIGHTS: Dict[RetrievalIntent, Dict[str, float]] = {
    RetrievalIntent.FACTUAL: {
        "sql": 0.45,
        "fts": 0.45,
        "graph": 0.00,
        "activation": 0.05,
        "importance": 0.05,
    },
    RetrievalIntent.EPISODIC: {
        "sql": 0.35,
        "fts": 0.30,
        "graph": 0.15,
        "activation": 0.15,
        "importance": 0.05,
    },
    RetrievalIntent.TEMPORAL: {
        "sql": 0.90,
        "fts": 0.00,
        "graph": 0.00,
        "activation": 0.05,
        "importance": 0.05,
    },
    RetrievalIntent.ASSOCIATIVE: {
        "sql": 0.00,
        "fts": 0.25,
        "graph": 0.50,
        "activation": 0.20,
        "importance": 0.05,
    },
    RetrievalIntent.AUTOBIOGRAPHICAL: {
        "sql": 0.30,
        "fts": 0.30,
        "graph": 0.20,
        "activation": 0.10,
        "importance": 0.10,
    },
    RetrievalIntent.REFLECTIVE: {
        "sql": 0.20,
        "fts": 0.40,
        "graph": 0.20,
        "activation": 0.10,
        "importance": 0.10,
    },
    RetrievalIntent.RELATIONSHIP: {
        "sql": 0.40,
        "fts": 0.30,
        "graph": 0.20,
        "activation": 0.05,
        "importance": 0.05,
    },
    RetrievalIntent.CONTRADICTION: {
        "sql": 0.80,
        "fts": 0.20,
        "graph": 0.00,
        "activation": 0.00,
        "importance": 0.00,
    },
    RetrievalIntent.GENERAL: {
        "sql": 0.25,
        "fts": 0.35,
        "graph": 0.20,
        "activation": 0.15,
        "importance": 0.05,
    },
}


class RetrievalIntentRouter:
    """
    Directs retrieval query planning, layer weight scaling, and token budget assembly.
    """

    @staticmethod
    def get_layer_weights(intent: RetrievalIntent) -> Dict[str, float]:
        """Returns the layer weight dictionary for a given retrieval intent."""
        return INTENT_LAYER_WEIGHTS.get(intent, INTENT_LAYER_WEIGHTS[RetrievalIntent.GENERAL])

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Heuristic token estimation: ~1 token per 4 characters."""
        return max(1, len(text) // 4)

    @staticmethod
    def assemble_token_budget(
        ranked_candidates: List[Dict[str, Any]],
        token_budget: int = 2048,
        min_remaining: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Greedy Knapsack assembly: Includes top-ranked candidates until token budget is exhausted.
        """
        assembled: List[Dict[str, Any]] = []
        remaining = token_budget

        for cand in ranked_candidates:
            summary = cand.get("summary", "")
            cost = RetrievalIntentRouter.estimate_tokens(summary)

            if cost <= remaining:
                cand_copy = dict(cand)
                cand_copy["estimated_tokens"] = cost
                assembled.append(cand_copy)
                remaining -= cost

            if remaining < min_remaining:
                break

        return assembled

    @staticmethod
    def generate_hyde_projection(query_text: str) -> str:
        """
        Hypothetical Document Embedding (HyDE) projection (Section 3.7).
        Generates an ephemeral query expansion string.
        CRITICAL INVARIANT: HyDE expansions are NEVER persisted to database or treated as evidence.
        """
        # Deterministic template-based expansion for local zero-latency execution
        return f"Information and context directly resolving query: '{query_text}'. Details and factual records."
