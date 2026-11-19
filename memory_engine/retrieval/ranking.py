"""
Multi-layer retrieval cascade and candidate ranking for Diva Memory Engine v3.0.
Combines Structured SQL, FTS5 full-text matching, and Graph Spreading Activation.
"""

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from memory_engine.database.connection import DatabaseConnectionFactory
from memory_engine.governance.service import MemoryGovernanceService
from memory_engine.retrieval.activation import ActivationEngine
from memory_engine.retrieval.intent_router import (
    RetrievalIntent,
    RetrievalIntentRouter,
)
from memory_engine.types.enums import AccessAction, DomainPartition


class RetrievalEngine:
    """
    Subsystem 6: Retrieval Engine Stack.
    Fuses SQL relational filters, FTS5 BM25 search, and spreading activation into a ranked candidate list.
    """

    def __init__(
        self,
        factory: DatabaseConnectionFactory,
        governance: MemoryGovernanceService,
        activation_engine: ActivationEngine,
    ):
        self.factory = factory
        self.governance = governance
        self.activation_engine = activation_engine

    def retrieve(
        self,
        query_text: str,
        requesting_engine: str,
        domain_partition: DomainPartition,
        session_id: uuid.UUID = uuid.UUID("00000000-0000-0000-0000-000000000000"),
        intent: RetrievalIntent = RetrievalIntent.GENERAL,
        token_budget: Optional[int] = None,
        seed_memory_ids: Optional[List[str]] = None,
        entity_filter: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Executes multi-layer retrieval cascade, scales layer scores by intent weights,
        and optionally limits results to a token budget.
        """
        start_time = time.time()
        # Assert governance permission
        self.governance.assert_access(
            requesting_engine=requesting_engine,
            resource_type="MEMORY",
            domain_partition=domain_partition,
            access_mode=AccessAction.READ,
            actor_session=str(session_id),
        )

        candidates: Dict[str, Dict[str, Any]] = {}
        retrieval_methods_used: List[str] = []
        weights = RetrievalIntentRouter.get_layer_weights(intent)

        # =====================================================================
        # LAYER 1: STRUCTURED SQL RETRIEVAL
        # =====================================================================
        retrieval_methods_used.append("SQL")
        with self.factory.read_cursor() as cursor:
            query = """
                SELECT experience_id, experience_summary, permanent_importance,
                       diva_time_recorded, access_count, last_accessed_at, participants
                FROM experiences
                WHERE domain_partition = ?
                  AND validity_status = 'CURRENT'
            """
            params: List[Any] = [domain_partition.value]
            if entity_filter:
                query += " AND participants LIKE ?"
                params.append(f"%{entity_filter}%")

            query += " ORDER BY permanent_importance DESC, diva_time_recorded DESC LIMIT 50;"
            cursor.execute(query, params)
            sql_rows = cursor.fetchall()

            for rank, r in enumerate(sql_rows):
                exp_id = r["experience_id"]
                sql_score = max(0.1, 1.0 - (rank * 0.02))
                candidates[exp_id] = {
                    "memory_id": exp_id,
                    "summary": r["experience_summary"],
                    "importance": r["permanent_importance"],
                    "created_at": datetime.fromisoformat(r["diva_time_recorded"]),
                    "access_count": r["access_count"],
                    "sql_score": sql_score,
                    "fts_score": 0.0,
                    "graph_score": 0.0,
                }

        # =====================================================================
        # LAYER 2: FTS5 FULL-TEXT RETRIEVAL
        # =====================================================================
        query_tokens = " ".join([w for w in query_text.replace("'", " ").split() if len(w) > 2])
        if query_tokens:
            retrieval_methods_used.append("FTS5")
            try:
                with self.factory.read_cursor() as cursor:
                    # SQLite FTS5 query
                    cursor.execute(
                        """
                        SELECT memory_id, rank
                        FROM memories_fts
                        WHERE memories_fts MATCH ?
                        ORDER BY rank
                        LIMIT 50;
                        """,
                        (query_tokens,),
                    )
                    fts_rows = cursor.fetchall()

                    for r in fts_rows:
                        exp_id = r["memory_id"]
                        bm25_rank = r["rank"]
                        # Normalize BM25 score
                        fts_score = round(1.0 / (1.0 + abs(float(bm25_rank))), 4)
                        if exp_id in candidates:
                            candidates[exp_id]["fts_score"] = fts_score
                        else:
                            # Fetch basic info for candidate
                            cursor.execute(
                                """
                                SELECT experience_id, experience_summary, permanent_importance,
                                       diva_time_recorded, access_count
                                FROM experiences
                                WHERE experience_id = ? AND domain_partition = ?;
                                """,
                                (exp_id, domain_partition.value),
                            )
                            found = cursor.fetchone()
                            if found:
                                candidates[exp_id] = {
                                    "memory_id": exp_id,
                                    "summary": found["experience_summary"],
                                    "importance": found["permanent_importance"],
                                    "created_at": datetime.fromisoformat(found["diva_time_recorded"]),
                                    "access_count": found["access_count"],
                                    "sql_score": 0.0,
                                    "fts_score": fts_score,
                                    "graph_score": 0.0,
                                }
            except Exception:
                pass  # FTS error recovery

        # =====================================================================
        # LAYER 3: GRAPH SPREADING ACTIVATION
        # =====================================================================
        if seed_memory_ids:
            retrieval_methods_used.append("GRAPH")
            spread_scores = self.activation_engine.spreading_activation(
                seed_memory_ids=seed_memory_ids, max_hops=3, threshold=0.1
            )
            for mem_id, act_score in spread_scores.items():
                if mem_id in candidates:
                    candidates[mem_id]["graph_score"] = act_score
                else:
                    with self.factory.read_cursor() as cursor:
                        cursor.execute(
                            """
                            SELECT experience_id, experience_summary, permanent_importance,
                                   diva_time_recorded, access_count
                            FROM experiences
                            WHERE experience_id = ? AND domain_partition = ?;
                            """,
                            (mem_id, domain_partition.value),
                        )
                        found = cursor.fetchone()
                        if found:
                            candidates[mem_id] = {
                                "memory_id": mem_id,
                                "summary": found["experience_summary"],
                                "importance": found["permanent_importance"],
                                "created_at": datetime.fromisoformat(found["diva_time_recorded"]),
                                "access_count": found["access_count"],
                                "sql_score": 0.0,
                                "fts_score": 0.0,
                                "graph_score": act_score,
                            }

        # =====================================================================
        # CANDIDATE RANKING
        # =====================================================================
        now = datetime.now(timezone.utc)
        scored_results: List[Dict[str, Any]] = []

        for mem_id, data in candidates.items():
            act_score = self.activation_engine.calculate_base_level_activation(
                access_count=data["access_count"],
                created_at=data["created_at"],
                current_time=now,
            )
            unified_score = (
                weights["sql"] * data["sql_score"]
                + weights["fts"] * data["fts_score"]
                + weights["graph"] * data["graph_score"]
                + weights["activation"] * act_score
                + weights["importance"] * data["importance"]
            )
            scored_results.append({
                "memory_id": mem_id,
                "summary": data["summary"],
                "score": round(unified_score, 4),
                "sql_score": data["sql_score"],
                "fts_score": data["fts_score"],
                "graph_score": data["graph_score"],
                "activation_score": act_score,
            })

        scored_results.sort(key=lambda x: x["score"], reverse=True)

        if token_budget:
            final_results = RetrievalIntentRouter.assemble_token_budget(
                scored_results[:limit], token_budget=token_budget
            )
        else:
            final_results = scored_results[:limit]

        latency_ms = int((time.time() - start_time) * 1000)

        # Log retrieval event with specific intent
        retrieved_ids = [r["memory_id"] for r in final_results]
        with self.factory.write_transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO retrieval_events (
                    retrieval_id, requesting_engine, retrieval_intent, query_text,
                    retrieved_ids, retrieved_count, retrieval_methods, total_latency_ms,
                    session_id, retrieved_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    str(uuid.uuid4()),
                    requesting_engine,
                    intent.value,
                    query_text,
                    json.dumps(retrieved_ids),
                    len(final_results),
                    json.dumps(retrieval_methods_used),
                    latency_ms,
                    str(session_id),
                    now.isoformat(),
                ),
            )

        return final_results
