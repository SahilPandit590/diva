"""
Incremental Consolidation Loop for Diva Memory Engine v3.0.
Implements Section 3.8: Prevents monolithic history rewriting by processing in small, continuous batches.
"""

import json
import uuid
from typing import Any, Dict, List, Tuple

from memory_engine.consolidation.seven_gate import SevenGateConsolidator
from memory_engine.database.connection import DatabaseConnectionFactory
from memory_engine.types.enums import DomainPartition


class IncrementalConsolidator:
    """
    Subsystem 7: Incremental Consolidation.
    Identifies clusters of related active experiences and consolidates them via the 7-Gate Protocol.
    """

    def __init__(
        self,
        factory: DatabaseConnectionFactory,
        seven_gate: SevenGateConsolidator,
    ):
        self.factory = factory
        self.seven_gate = seven_gate

    def run_incremental_cycle(
        self,
        domain_partition: DomainPartition = DomainPartition.COGNITIVE,
        min_cluster_size: int = 2,
        batch_limit: int = 20,
    ) -> List[Tuple[uuid.UUID, List[uuid.UUID]]]:
        """
        Executes one incremental consolidation cycle.
        Returns list of (created_representation_id, [source_memory_ids]).
        """
        # Step 1: Identify eligible active experiences
        with self.factory.read_cursor() as cursor:
            cursor.execute(
                """
                SELECT experience_id, experience_summary, participants, permanent_importance
                FROM experiences
                WHERE domain_partition = ?
                  AND retention_status = 'ACTIVE'
                  AND permanent_importance >= 0.3
                ORDER BY permanent_importance DESC, diva_time_recorded ASC
                LIMIT ?;
                """,
                (domain_partition.value, batch_limit),
            )
            rows = cursor.fetchall()

        if len(rows) < min_cluster_size:
            return []

        # Step 2: Cluster experiences sharing at least one common entity participant
        clusters: Dict[str, List[Dict[str, Any]]] = {}
        for row in rows:
            parts = json.loads(row["participants"])
            if not parts:
                # Group under generic key if no specific entity
                key = "general"
            else:
                key = parts[0]

            if key not in clusters:
                clusters[key] = []
            clusters[key].append(row)

        consolidated_results: List[Tuple[uuid.UUID, List[uuid.UUID]]] = []

        # Step 3: Run 7-Gate Consolidation for clusters meeting minimum size
        for key, exp_cluster in clusters.items():
            if len(exp_cluster) < min_cluster_size:
                continue

            source_ids = [uuid.UUID(e["experience_id"]) for e in exp_cluster]
            summaries = [e["experience_summary"] for e in exp_cluster]
            joint_summary = f"Consolidated synthesis: {' | '.join(summaries[:3])}"

            success, repr_id, _ = self.seven_gate.consolidate(
                source_memory_ids=source_ids,
                consolidated_summary=joint_summary,
                consolidated_claims=[{"cluster_key": key, "event_count": len(source_ids)}],
                domain_partition=domain_partition,
                initiating_engine="MEMORY_GOVERNANCE",
            )

            if success and repr_id:
                consolidated_results.append((repr_id, source_ids))

        return consolidated_results
