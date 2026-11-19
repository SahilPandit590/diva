"""
Deterministic pattern detection algorithms (Development Path A) for Diva Memory Engine v3.0.
Detects temporal co-occurrence and sequential ordering without requiring an LLM.
"""

import json
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple

from memory_engine.database.connection import DatabaseConnectionFactory
from memory_engine.entities.service import EntityAssociationService
from memory_engine.types.enums import DomainPartition, MemoryRelationshipType


class PatternDetector:
    """
    Subsystem 5: Pattern Detection.
    Executes deterministic frequency and temporal sequence mining across episodic memories.
    """

    def __init__(
        self,
        factory: DatabaseConnectionFactory,
        entities: EntityAssociationService,
    ):
        self.factory = factory
        self.entities = entities

    def detect_co_occurrence_patterns(
        self,
        domain_partition: DomainPartition = DomainPartition.COGNITIVE,
        min_co_occurrences: int = 2,
        limit_experiences: int = 100,
    ) -> List[Tuple[str, str, int]]:
        """
        Builds a sparse co-occurrence matrix of entities appearing together across recent experiences.
        Returns list of (entity_a, entity_b, co_occurrence_count) meeting threshold.
        """
        with self.factory.read_cursor() as cursor:
            cursor.execute(
                """
                SELECT experience_id, participants
                FROM experiences
                WHERE domain_partition = ?
                ORDER BY diva_time_recorded DESC
                LIMIT ?;
                """,
                (domain_partition.value, limit_experiences),
            )
            rows = cursor.fetchall()

        co_counts: Dict[Tuple[str, str], int] = defaultdict(int)

        for row in rows:
            participants = json.loads(row["participants"])
            if len(participants) < 2:
                continue

            # Sort IDs to normalize pair key
            sorted_parts = sorted(set(participants))
            for i in range(len(sorted_parts)):
                for j in range(i + 1, len(sorted_parts)):
                    pair = (sorted_parts[i], sorted_parts[j])
                    co_counts[pair] += 1

        results = []
        for (ent_a, ent_b), count in co_counts.items():
            if count >= min_co_occurrences:
                results.append((ent_a, ent_b, count))

        return results

    def organize_temporal_sequences(
        self,
        entity_id: uuid.UUID,
        domain_partition: DomainPartition = DomainPartition.COGNITIVE,
    ) -> int:
        """
        Sorts experiences involving entity_id chronologically and establishes EXPERIENCED_BEFORE links.
        Returns the number of relationships established.
        """
        with self.factory.read_cursor() as cursor:
            cursor.execute(
                """
                SELECT experience_id, world_time_start, diva_time_recorded
                FROM experiences
                WHERE domain_partition = ?
                  AND participants LIKE ?
                ORDER BY COALESCE(world_time_start, diva_time_recorded) ASC;
                """,
                (domain_partition.value, f"%{entity_id}%"),
            )
            rows = cursor.fetchall()

        if len(rows) < 2:
            return 0

        links_created = 0
        for i in range(len(rows) - 1):
            src_id = uuid.UUID(rows[i]["experience_id"])
            tgt_id = uuid.UUID(rows[i + 1]["experience_id"])

            # Check if relationship already exists
            with self.factory.read_cursor() as cursor:
                cursor.execute(
                    """
                    SELECT count(*) FROM memory_relationships
                    WHERE source_memory_id = ? AND target_memory_id = ?
                      AND relationship_type = 'EXPERIENCED_BEFORE' AND superseded = 0;
                    """,
                    (str(src_id), str(tgt_id)),
                )
                if cursor.fetchone()[0] == 0:
                    self.entities.link_memories(
                        source_id=src_id,
                        target_id=tgt_id,
                        relationship_type=MemoryRelationshipType.EXPERIENCED_BEFORE,
                        confidence=1.0,
                        established_by="TEMPORAL_SEQUENCE_DETECTOR",
                    )
                    links_created += 1

        return links_created
