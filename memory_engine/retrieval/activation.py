"""
ACT-R memory activation and spreading activation algorithms for Diva Memory Engine v3.0.
Calculates base-level activation B(M, t) and NetworkX spreading activation across associations.
"""

import math
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple
import networkx as nx

from memory_engine.database.connection import DatabaseConnectionFactory
from memory_engine.types.enums import MemoryRelationshipType


# Relationship type propagation weights
RELATIONSHIP_PROPAGATION_WEIGHTS: Dict[str, float] = {
    "CAUSED_BY": 0.9,
    "CAUSED": 0.9,
    "PART_OF": 0.8,
    "DEVELOPED_FROM": 0.8,
    "INSTANCE_OF": 0.7,
    "SIMILAR_TO": 0.6,
    "ASSOCIATED_WITH": 0.4,
    "EXPERIENCED_BEFORE": 0.3,
    "EXPERIENCED_AFTER": 0.3,
    "CONTRADICTS": -0.3,  # Negative activation suppression
}


class ActivationEngine:
    """
    Computes ACT-R base-level activation and spreading activation across memory graphs.
    """

    def __init__(self, factory: DatabaseConnectionFactory, decay_rate: float = 0.5):
        self.factory = factory
        self.decay_rate = decay_rate
        self._graph: nx.DiGraph = nx.DiGraph()

    def calculate_base_level_activation(
        self, access_count: int, created_at: datetime, current_time: Optional[datetime] = None
    ) -> float:
        """
        Computes base-level activation B(M, t) using the Anderson (2004) approximation:
          B(M, t) = ln(n / (1 - d)) - d * ln(L)
        where n = access_count (minimum 1), L = lifetime in seconds (minimum 1.0), d = decay (0.5).
        """
        now = current_time or datetime.now(timezone.utc)
        lifetime_sec = max(1.0, (now - created_at).total_seconds())
        n = max(1, access_count)
        d = self.decay_rate

        # B(M, t) = ln(n / (1 - d)) - d * ln(L)
        base = math.log(n / (1.0 - d)) - (d * math.log(lifetime_sec))
        # Normalize into non-negative score [0.0, 1.0] using sigmoid
        score = 1.0 / (1.0 + math.exp(-base * 0.5))
        return round(score, 4)

    def refresh_graph_projection(self) -> None:
        """Loads memory_relationships from database into in-memory NetworkX DiGraph."""
        graph = nx.DiGraph()
        with self.factory.read_cursor() as cursor:
            cursor.execute(
                """
                SELECT source_memory_id, target_memory_id, relationship_type, confidence
                FROM memory_relationships
                WHERE superseded = 0;
                """
            )
            rows = cursor.fetchall()

        for r in rows:
            rel_type = r["relationship_type"]
            weight = r["confidence"] * RELATIONSHIP_PROPAGATION_WEIGHTS.get(rel_type, 0.4)
            graph.add_edge(
                r["source_memory_id"],
                r["target_memory_id"],
                rel_type=rel_type,
                weight=weight,
            )

        self._graph = graph

    def spreading_activation(
        self, seed_memory_ids: List[str], max_hops: int = 3, threshold: float = 0.1
    ) -> Dict[str, float]:
        """
        Spreading activation algorithm starting from seed_memory_ids.
        Returns dictionary of {memory_id: activation_score}.
        """
        if not self._graph:
            self.refresh_graph_projection()

        activations: Dict[str, float] = {}
        for s in seed_memory_ids:
            if s in self._graph:
                activations[s] = 1.0

        current_frontier = set(seed_memory_ids)
        decay = 0.5

        for _ in range(max_hops):
            next_frontier: Set[str] = set()
            for node in current_frontier:
                if node not in self._graph:
                    continue
                curr_act = activations.get(node, 0.0)
                for neighbor in self._graph.neighbors(node):
                    edge_data = self._graph.get_edge_data(node, neighbor)
                    weight = edge_data.get("weight", 0.4) if edge_data else 0.4
                    propagated = curr_act * weight * decay

                    prev_act = activations.get(neighbor, 0.0)
                    new_act = max(prev_act, propagated)
                    if new_act >= threshold:
                        activations[neighbor] = new_act
                        next_frontier.add(neighbor)
            current_frontier = next_frontier
            if not current_frontier:
                break

        return {k: round(v, 4) for k, v in activations.items() if v >= threshold}

    def compute_pagerank(
        self, alpha: float = 0.85, max_iter: int = 100
    ) -> Dict[str, float]:
        """
        Section 4.4: Compute PageRank importance scores for all nodes in the memory graph.
        Calls refresh_graph_projection() if the graph is empty.
        Returns {memory_id: pagerank_score} dict.
        """
        if len(self._graph) == 0:
            self.refresh_graph_projection()
        if len(self._graph) == 0:
            return {}
        try:
            ranks = nx.pagerank(self._graph, alpha=alpha, max_iter=max_iter)
            return {node: round(score, 6) for node, score in ranks.items()}
        except nx.PowerIterationFailedConvergence:
            # Fall back to unweighted ranks if convergence fails
            ranks = nx.pagerank(self._graph, alpha=alpha, max_iter=500, tol=1e-4)
            return {node: round(score, 6) for node, score in ranks.items()}

    def detect_communities(self) -> List[Set[str]]:
        """
        Section 4.4: Detect communities in the memory graph using Louvain method.
        Operates on the undirected view of the DiGraph.
        Returns a list of sets, each set containing memory_ids in one community.
        """
        if len(self._graph) == 0:
            self.refresh_graph_projection()
        if len(self._graph) == 0:
            return []
        undirected = self._graph.to_undirected()
        try:
            communities = list(nx.community.louvain_communities(undirected, seed=42))
            return [set(c) for c in communities]
        except Exception:
            # If Louvain unavailable, fall back to connected components
            return [set(c) for c in nx.connected_components(undirected)]
