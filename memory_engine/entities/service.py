"""
Entity and Association Graph Service for Diva Memory Engine v3.0.
Manages canonical entities, aliases, temporal attributes, and memory-to-memory relationships.
Section 3.3: 4-step entity resolution pipeline (exact canonical → exact alias → fuzzy alias → semantic).
"""

import hashlib
import json
import uuid
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

from memory_engine.database.connection import DatabaseConnectionFactory
from memory_engine.governance.service import MemoryGovernanceService
from memory_engine.types.entity import (
    Entity,
    EntityAlias,
    EntityAttribute,
    MemoryRelationship,
)
from memory_engine.types.enums import (
    AccessAction,
    AliasType,
    DomainPartition,
    EntityStatus,
    EntityType,
    EpistemicType,
    MemoryRelationshipType,
)


class EntityAssociationService:
    """
    Subsystem 4: Entity & Association Graph.
    Resolves entities across memories, maintains aliases, and tracks typed relationships.
    """

    def __init__(
        self,
        factory: DatabaseConnectionFactory,
        governance: MemoryGovernanceService,
    ):
        self.factory = factory
        self.governance = governance

    def create_or_get_entity(
        self,
        canonical_name: str,
        entity_type: EntityType = EntityType.UNKNOWN,
        domain_partition: DomainPartition = DomainPartition.COGNITIVE,
        aliases: Optional[List[str]] = None,
        source_engine: str = "PERCEPTION",
    ) -> Entity:
        """
        Creates a new entity or returns existing one matching canonical_name in partition.
        """
        norm_name = canonical_name.strip()
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()

        # Check existing entity
        with self.factory.read_cursor() as cursor:
            cursor.execute(
                """
                SELECT entity_id, canonical_name, entity_type, domain_partition,
                       first_observed_at, last_observed_at, observation_count, status, provenance_hash
                FROM entities
                WHERE canonical_name = ? AND domain_partition = ? AND status = 'ACTIVE';
                """,
                (norm_name, domain_partition.value),
            )
            row = cursor.fetchone()
            if row:
                return Entity(
                    entity_id=uuid.UUID(row["entity_id"]),
                    canonical_name=row["canonical_name"],
                    entity_type=EntityType(row["entity_type"]),
                    domain_partition=DomainPartition(row["domain_partition"]),
                    first_observed_at=datetime.fromisoformat(row["first_observed_at"]),
                    last_observed_at=datetime.fromisoformat(row["last_observed_at"]),
                    observation_count=row["observation_count"],
                    status=EntityStatus(row["status"]),
                )

        entity_id = uuid.uuid4()
        prov_raw = f"{norm_name}|{entity_type.value}|{now_iso}"
        prov_hash = hashlib.sha256(prov_raw.encode("utf-8")).hexdigest()

        with self.factory.write_transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO entities (
                    entity_id, canonical_name, entity_type, domain_partition,
                    first_observed_at, last_observed_at, observation_count,
                    status, provenance_hash
                ) VALUES (?, ?, ?, ?, ?, ?, 1, 'ACTIVE', ?);
                """,
                (
                    str(entity_id),
                    norm_name,
                    entity_type.value,
                    domain_partition.value,
                    now_iso,
                    now_iso,
                    prov_hash,
                ),
            )

            # Insert aliases if provided
            if aliases:
                for alias in aliases:
                    alias_clean = alias.strip()
                    if alias_clean:
                        cursor.execute(
                            """
                            INSERT OR IGNORE INTO entity_aliases (
                                alias_id, entity_id, alias_text, alias_type,
                                confidence, source_engine, established_at, superseded
                            ) VALUES (?, ?, ?, 'NICKNAME', 1.0, ?, ?, 0);
                            """,
                            (
                                str(uuid.uuid4()),
                                str(entity_id),
                                alias_clean,
                                source_engine,
                                now_iso,
                            ),
                        )

            self.governance.log_audit_event_in_tx(
                cursor=cursor,
                event_type="ENTITY_CREATED",
                target_id=str(entity_id),
                target_type="ENTITY",
                actor_engine=source_engine,
                actor_session="00000000-0000-0000-0000-000000000000",
                new_state={"canonical_name": norm_name, "type": entity_type.value},
            )

        return Entity(
            entity_id=entity_id,
            canonical_name=norm_name,
            entity_type=entity_type,
            domain_partition=domain_partition,
            first_observed_at=now,
            last_observed_at=now,
            observation_count=1,
            status=EntityStatus.ACTIVE,
        )

    def resolve_entity(
        self, mention_text: str, domain_partition: DomainPartition
    ) -> Optional[Entity]:
        """
        Resolves an entity by canonical name or alias.
        """
        mention_clean = mention_text.strip()
        with self.factory.read_cursor() as cursor:
            # 1. Exact canonical name lookup
            cursor.execute(
                """
                SELECT entity_id, canonical_name, entity_type, domain_partition,
                       first_observed_at, last_observed_at, observation_count, status
                FROM entities
                WHERE canonical_name = ? AND domain_partition = ? AND status = 'ACTIVE';
                """,
                (mention_clean, domain_partition.value),
            )
            row = cursor.fetchone()
            if row:
                return Entity(
                    entity_id=uuid.UUID(row["entity_id"]),
                    canonical_name=row["canonical_name"],
                    entity_type=EntityType(row["entity_type"]),
                    domain_partition=DomainPartition(row["domain_partition"]),
                    first_observed_at=datetime.fromisoformat(row["first_observed_at"]),
                    last_observed_at=datetime.fromisoformat(row["last_observed_at"]),
                    observation_count=row["observation_count"],
                    status=EntityStatus(row["status"]),
                )

            # 2. Alias lookup
            cursor.execute(
                """
                SELECT e.entity_id, e.canonical_name, e.entity_type, e.domain_partition,
                       e.first_observed_at, e.last_observed_at, e.observation_count, e.status
                FROM entity_aliases a
                JOIN entities e ON e.entity_id = a.entity_id
                WHERE a.alias_text = ? AND e.domain_partition = ? AND a.superseded = 0;
                """,
                (mention_clean, domain_partition.value),
            )
            row = cursor.fetchone()
            if row:
                return Entity(
                    entity_id=uuid.UUID(row["entity_id"]),
                    canonical_name=row["canonical_name"],
                    entity_type=EntityType(row["entity_type"]),
                    domain_partition=DomainPartition(row["domain_partition"]),
                    first_observed_at=datetime.fromisoformat(row["first_observed_at"]),
                    last_observed_at=datetime.fromisoformat(row["last_observed_at"]),
                    observation_count=row["observation_count"],
                    status=EntityStatus(row["status"]),
                )

            # 3. Fuzzy alias lookup — Section 3.3 Step 2
            # Load all active aliases in this partition and find best edit-distance match.
            # Levenshtein distance ≤ 2 approximated via SequenceMatcher ratio.
            cursor.execute(
                """
                SELECT a.alias_text, a.alias_id, e.entity_id, e.canonical_name,
                       e.entity_type, e.domain_partition, e.first_observed_at,
                       e.last_observed_at, e.observation_count, e.status
                FROM entity_aliases a
                JOIN entities e ON e.entity_id = a.entity_id
                WHERE e.domain_partition = ? AND a.superseded = 0;
                """,
                (domain_partition.value,),
            )
            alias_rows = cursor.fetchall()

        best_entity_row = None
        best_confidence = 0.0
        mention_lower = mention_clean.lower()

        for arow in alias_rows:
            alias_lower = arow["alias_text"].lower()
            len_diff = abs(len(mention_lower) - len(alias_lower))
            if len_diff > 2:
                continue
            ratio = SequenceMatcher(None, mention_lower, alias_lower).ratio()
            # ratio ≥ 0.85 roughly corresponds to Levenshtein distance ≤ 2 for short strings
            if ratio >= 0.85 and ratio > best_confidence:
                best_confidence = ratio
                best_entity_row = arow

        if best_entity_row:
            entity = Entity(
                entity_id=uuid.UUID(best_entity_row["entity_id"]),
                canonical_name=best_entity_row["canonical_name"],
                entity_type=EntityType(best_entity_row["entity_type"]),
                domain_partition=DomainPartition(best_entity_row["domain_partition"]),
                first_observed_at=datetime.fromisoformat(best_entity_row["first_observed_at"]),
                last_observed_at=datetime.fromisoformat(best_entity_row["last_observed_at"]),
                observation_count=best_entity_row["observation_count"],
                status=EntityStatus(best_entity_row["status"]),
            )
            self._register_fuzzy_alias(
                entity_id=entity.entity_id,
                alias_text=mention_clean,
                confidence=round(best_confidence, 4),
            )
            return entity

        return None

    def _register_fuzzy_alias(
        self,
        entity_id: uuid.UUID,
        alias_text: str,
        confidence: float,
    ) -> None:
        """
        Registers a fuzzy-matched alias with sub-1.0 confidence (Section 3.3).
        Uses INSERT OR IGNORE to avoid duplicates.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        with self.factory.write_transaction() as cursor:
            cursor.execute(
                """
                INSERT OR IGNORE INTO entity_aliases (
                    alias_id, entity_id, alias_text, alias_type,
                    confidence, source_engine, established_at, superseded
                ) VALUES (?, ?, ?, 'ALIAS', ?, 'ENTITY_RESOLUTION', ?, 0);
                """,
                (
                    str(uuid.uuid4()),
                    str(entity_id),
                    alias_text,
                    confidence,
                    now_iso,
                ),
            )

    def link_memories(
        self,
        source_id: uuid.UUID,
        target_id: uuid.UUID,
        relationship_type: MemoryRelationshipType,
        confidence: float = 1.0,
        established_by: str = "MEMORY_DEVELOPMENT",
    ) -> MemoryRelationship:
        """Creates a typed relationship edge between two memories in memory_relationships."""
        rel_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()

        with self.factory.write_transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO memory_relationships (
                    relationship_id, source_memory_id, target_memory_id,
                    relationship_type, confidence, established_by,
                    established_at, superseded
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 0);
                """,
                (
                    str(rel_id),
                    str(source_id),
                    str(target_id),
                    relationship_type.value,
                    confidence,
                    established_by,
                    now_iso,
                ),
            )

        return MemoryRelationship(
            relationship_id=rel_id,
            source_memory_id=source_id,
            target_memory_id=target_id,
            relationship_type=relationship_type,
            confidence=confidence,
            established_by=established_by,
            established_at=now,
        )

    def merge_entities(
        self,
        source_entity_id: uuid.UUID,
        target_entity_id: uuid.UUID,
        actor_engine: str = "MEMORY_GOVERNANCE",
        actor_session: str = "00000000-0000-0000-0000-000000000000",
    ) -> None:
        """
        Scenario 11: Merges source entity into target entity.
        - Sets source entity status='MERGED', merged_into=target_entity_id.
        - Updates entity_aliases to point to target_entity_id.
        - Updates experiences.participants where source_entity_id is mentioned.
        - Logs ENTITY_MERGED audit event.
        """
        src_str = str(source_entity_id)
        tgt_str = str(target_entity_id)

        with self.factory.write_transaction() as cursor:
            # 1. Update source entity record
            cursor.execute(
                """
                UPDATE entities
                SET status = 'MERGED', merged_into = ?
                WHERE entity_id = ?;
                """,
                (tgt_str, src_str),
            )

            # 2. Get source canonical name and add as alias for target if not already present
            cursor.execute(
                "SELECT canonical_name FROM entities WHERE entity_id = ?;",
                (src_str,),
            )
            src_row = cursor.fetchone()
            if src_row:
                now_iso = datetime.now(timezone.utc).isoformat()
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO entity_aliases (
                        alias_id, entity_id, alias_text, alias_type,
                        confidence, source_engine, established_at, superseded
                    ) VALUES (?, ?, ?, 'ALIAS', 1.0, ?, ?, 0);
                    """,
                    (
                        str(uuid.uuid4()),
                        tgt_str,
                        src_row["canonical_name"],
                        actor_engine,
                        now_iso,
                    ),
                )

            # 3. Update existing aliases of source to point to target
            cursor.execute(
                """
                UPDATE entity_aliases
                SET entity_id = ?
                WHERE entity_id = ?;
                """,
                (tgt_str, src_str),
            )

            # 4. Update experiences.participants containing source entity
            cursor.execute(
                "SELECT experience_id, participants FROM experiences WHERE participants LIKE ?;",
                (f"%{src_str}%",),
            )
            exp_rows = cursor.fetchall()
            for erow in exp_rows:
                parts = json.loads(erow["participants"])
                if src_str in parts:
                    parts = [tgt_str if p == src_str else p for p in parts]
                    # Deduplicate in case target was already in list
                    parts = list(dict.fromkeys(parts))
                    cursor.execute(
                        "UPDATE experiences SET participants = ? WHERE experience_id = ?;",
                        (json.dumps(parts), erow["experience_id"]),
                    )

            # 5. Log audit event
            self.governance.log_audit_event_in_tx(
                cursor=cursor,
                event_type="ENTITY_MERGED",
                target_id=src_str,
                target_type="ENTITY",
                actor_engine=actor_engine,
                actor_session=actor_session,
                old_state={"status": "ACTIVE"},
                new_state={"status": "MERGED", "merged_into": tgt_str},
            )

