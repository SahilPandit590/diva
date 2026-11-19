"""
Background job handlers for Diva Memory Engine v3.0.
Processes asynchronous jobs: FTS5 indexing, entity linking, and pattern mining.
"""

import json
import uuid
from typing import Any, Dict

from memory_engine.database.connection import DatabaseConnectionFactory
from memory_engine.entities.service import EntityAssociationService
from memory_engine.types.enums import DomainPartition


class JobHandlers:
    """
    Executes specific background jobs registered in background_jobs table.
    """

    def __init__(
        self,
        factory: DatabaseConnectionFactory,
        entities: EntityAssociationService,
    ):
        self.factory = factory
        self.entities = entities

    def handle_fts5_indexing(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Updates the memories_fts projection table for full-text search.
        FTS5 content sync runs asynchronously to keep synchronous intake latency minimal.
        """
        memory_id = input_data["memory_id"]
        summary = input_data.get("summary", "")
        statements = input_data.get("statements", "")
        entity_names = input_data.get("entities", "")

        with self.factory.write_transaction() as cursor:
            # Delete prior row if exists to prevent duplicate FTS entries
            cursor.execute("DELETE FROM memories_fts WHERE memory_id = ?;", (memory_id,))
            cursor.execute(
                """
                INSERT INTO memories_fts (
                    memory_id, experience_summary, canonical_statements, entity_names
                ) VALUES (?, ?, ?, ?);
                """,
                (memory_id, summary, statements, entity_names),
            )

        return {"indexed_memory_id": memory_id, "status": "SUCCESS"}

    def handle_entity_linking(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Scans text for known entity aliases and links them to the experience.
        """
        experience_id = input_data["experience_id"]
        text = input_data.get("text", "")
        linked_entities = []

        # Find known aliases in text
        with self.factory.read_cursor() as cursor:
            cursor.execute(
                """
                SELECT a.alias_text, a.entity_id, e.canonical_name
                FROM entity_aliases a
                JOIN entities e ON e.entity_id = a.entity_id
                WHERE a.superseded = 0 AND e.status = 'ACTIVE';
                """
            )
            aliases = cursor.fetchall()

        for a in aliases:
            if a["alias_text"].lower() in text.lower():
                linked_entities.append(a["entity_id"])

        if linked_entities:
            with self.factory.write_transaction() as cursor:
                cursor.execute(
                    "SELECT participants FROM experiences WHERE experience_id = ?;",
                    (experience_id,),
                )
                row = cursor.fetchone()
                if row:
                    curr_parts = set(json.loads(row["participants"]))
                    curr_parts.update(linked_entities)
                    cursor.execute(
                        "UPDATE experiences SET participants = ? WHERE experience_id = ?;",
                        (json.dumps(sorted(list(curr_parts))), experience_id),
                    )

        return {"linked_count": len(linked_entities), "entity_ids": linked_entities}
