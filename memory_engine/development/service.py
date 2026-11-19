"""
Memory Development Service for Diva Memory Engine v3.0.
Coordinates the Hybrid Memory Development protocol: Kind A (independent), Kind B (collaborative),
and Kind C (integration) operations.
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from memory_engine.database.connection import DatabaseConnectionFactory
from memory_engine.development.bounded_runner import BoundedDevelopmentRunner
from memory_engine.development.lifecycle import DevelopmentFSM
from memory_engine.development.patterns import PatternDetector
from memory_engine.governance.exceptions import EpistemicDowngradeError
from memory_engine.governance.service import MemoryGovernanceService
from memory_engine.jobs.outbox import emit_outbox_event_in_tx
from memory_engine.knowledge.store import KnowledgeStoreService
from memory_engine.types.claim import MemoryClaim, ProposedClaim, ProposedRelationship
from memory_engine.types.development import (
    DevelopmentRequest,
    DevelopmentResult,
)
from memory_engine.types.enums import (
    AccessAction,
    ClaimRelationshipType,
    DevelopmentOperationType,
    DevelopmentResultStatus,
    DevelopmentStatus,
    DomainPartition,
)


class MemoryDevelopmentService:
    """
    Subsystem 5: Memory Development Engine.
    Executes independent pattern discovery and mediates multi-engine collaborative development.
    """

    def __init__(
        self,
        factory: DatabaseConnectionFactory,
        governance: MemoryGovernanceService,
        knowledge: KnowledgeStoreService,
        patterns: PatternDetector,
    ):
        self.factory = factory
        self.governance = governance
        self.knowledge = knowledge
        self.patterns = patterns
        self.runner = BoundedDevelopmentRunner(factory)

    def request_development(
        self,
        operation_type: DevelopmentOperationType,
        development_objective: str,
        initiating_subsystem: str = "MEMORY_DEVELOPMENT",
        target_memory_ids: Optional[List[uuid.UUID]] = None,
        target_claim_ids: Optional[List[uuid.UUID]] = None,
        requesting_engine: Optional[str] = None,
        target_engine: Optional[str] = None,
        parent_operation_id: Optional[uuid.UUID] = None,
        current_depth: int = 0,
        processing_depth: Optional[int] = None,
        max_processing_depth: int = 5,
        priority: int = 5,
    ) -> DevelopmentRequest:
        """
        Kind B Initiation: Creates and registers a DevelopmentRequest in development_requests table.
        Emits 'memory.development_requested' outbox event.
        """
        depth = processing_depth if processing_depth is not None else current_depth
        request = self.runner.validate_and_prepare_request(
            operation_type=operation_type,
            initiating_subsystem=initiating_subsystem,
            development_objective=development_objective,
            target_memory_ids=target_memory_ids,
            target_claim_ids=target_claim_ids,
            requesting_engine=requesting_engine or target_engine,
            parent_operation_id=parent_operation_id,
            current_depth=depth,
            max_processing_depth=max_processing_depth,
            priority=priority,
        )

        now_iso = request.requested_at.isoformat()
        with self.factory.write_transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO development_requests (
                    request_id, operation_type, initiating_subsystem, requesting_engine,
                    target_memory_ids, target_claim_ids, development_objective,
                    evidence_requirements, parent_operation_id, processing_depth,
                    max_processing_depth, resource_budget, idempotency_key,
                    priority, status, requested_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, '[]', ?, ?, ?, ?, ?, ?, 'PENDING', ?);
                """,
                (
                    str(request.request_id),
                    request.operation_type.value,
                    request.initiating_subsystem,
                    request.requesting_engine,
                    json.dumps([str(m) for m in request.target_memory_ids]),
                    json.dumps([str(c) for c in request.target_claim_ids]),
                    request.development_objective,
                    str(request.parent_operation_id) if request.parent_operation_id else None,
                    request.processing_depth,
                    request.max_processing_depth,
                    request.resource_budget.model_dump_json(),
                    request.idempotency_key,
                    request.priority,
                    now_iso,
                ),
            )

            emit_outbox_event_in_tx(
                cursor=cursor,
                event_name="memory.development_requested",
                event_payload={
                    "request_id": str(request.request_id),
                    "operation_type": request.operation_type.value,
                    "target_engine": requesting_engine,
                },
                source_engine="MEMORY_DEVELOPMENT",
            )

        return request

    def submit_development_proposal(
        self,
        request_id: uuid.UUID,
        originating_engine: str,
        proposed_claims: Optional[List[ProposedClaim]] = None,
        proposed_relationships: Optional[List[ProposedRelationship]] = None,
        supporting_evidence_ids: Optional[List[uuid.UUID]] = None,
        opposing_evidence_ids: Optional[List[uuid.UUID]] = None,
        rationale: str = "",
    ) -> uuid.UUID:
        """
        Kind B Response: Specialized engine submits candidate claims/relationships for review.
        External engines do NOT supply database UUIDs (MEM-002, MEM-003).
        """
        proposal_id = uuid.uuid4()
        now_iso = datetime.now(timezone.utc).isoformat()

        claims_json = json.dumps([c.model_dump(mode="json") for c in (proposed_claims or [])])
        rels_json = json.dumps([r.model_dump(mode="json") for r in (proposed_relationships or [])])
        sup_json = json.dumps([str(s) for s in (supporting_evidence_ids or [])])
        opp_json = json.dumps([str(o) for o in (opposing_evidence_ids or [])])

        with self.factory.write_transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO development_proposals (
                    proposal_id, request_id, originating_engine, result_status,
                    proposed_claims, proposed_relations, supporting_evidence,
                    opposing_evidence, unresolved_questions, rationale, produced_at
                ) VALUES (?, ?, ?, 'PROPOSED', ?, ?, ?, ?, '[]', ?, ?);
                """,
                (
                    str(proposal_id),
                    str(request_id),
                    originating_engine,
                    claims_json,
                    rels_json,
                    sup_json,
                    opp_json,
                    rationale,
                    now_iso,
                ),
            )

        return proposal_id

    def review_development_proposal(
        self,
        proposal_id: uuid.UUID,
        decision: str,  # "ACCEPT" | "REJECT" | "DEFER"
        reviewing_engine: str = "MEMORY_GOVERNANCE",
        decision_reason: str = "Validation criteria verified",
        session_id: uuid.UUID = uuid.UUID("00000000-0000-0000-0000-000000000000"),
        domain_partition: DomainPartition = DomainPartition.COGNITIVE,
    ) -> List[MemoryClaim]:
        """
        Kind C Integration: Memory Governance reviews candidate proposal.
        If ACCEPT: assigns permanent database UUIDs, creates claims, and records review.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        review_id = uuid.uuid4()

        with self.factory.read_cursor() as cursor:
            cursor.execute(
                "SELECT * FROM development_proposals WHERE proposal_id = ?;",
                (str(proposal_id),),
            )
            prop = cursor.fetchone()
            if not prop:
                raise ValueError(f"Proposal {proposal_id} does not exist.")

        created_claims: List[MemoryClaim] = []

        # MEM-015-B: Specialized engines (Emotion, Social Cognition) produce INTERPRETATION only, never OBSERVATION
        proposed_claims_data = json.loads(prop["proposed_claims"])
        if prop["originating_engine"] in ("EMOTION", "SOCIAL_COGNITION"):
            for c_data in proposed_claims_data:
                if c_data.get("epistemic_type") == "OBSERVATION":
                    decision = "REJECT"
                    decision_reason = "EPISTEMIC_UPGRADE_FORBIDDEN"
                    break

        if decision == "ACCEPT":
            for c_data in proposed_claims_data:
                p_claim = ProposedClaim(**c_data)
                claim = self.knowledge.create_claim(
                    proposal=p_claim,
                    session_id=session_id,
                    domain_partition=domain_partition,
                )
                created_claims.append(claim)

            # Insert proposed relationships
            proposed_rels_data = json.loads(prop["proposed_relations"])
            for r_data in proposed_rels_data:
                p_rel = ProposedRelationship(**r_data)
                with self.factory.write_transaction() as cursor:
                    cursor.execute(
                        """
                        INSERT OR IGNORE INTO claim_relationships (
                            relationship_id, claim_id_source, claim_id_target,
                            relationship_type, confidence, established_by,
                            established_at, superseded
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, 0);
                        """,
                        (
                            str(uuid.uuid4()),
                            str(p_rel.claim_id_source),
                            str(p_rel.claim_id_target),
                            p_rel.relationship_type.value,
                            p_rel.confidence,
                            reviewing_engine,
                            now_iso,
                        ),
                    )

        resulting_ids = [str(c.claim_id) for c in created_claims]

        with self.factory.write_transaction() as cursor:
            # 1. Update proposal status
            cursor.execute(
                "UPDATE development_proposals SET result_status = ? WHERE proposal_id = ?;",
                ("ACCEPTED" if decision == "ACCEPT" else "REJECTED", str(proposal_id)),
            )

            # 2. Record review
            cursor.execute(
                """
                INSERT INTO development_reviews (
                    review_id, proposal_id, reviewing_engine, decision,
                    decision_reason, reviewed_at, resulting_records
                ) VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    str(review_id),
                    str(proposal_id),
                    reviewing_engine,
                    decision,
                    decision_reason,
                    now_iso,
                    json.dumps(resulting_ids),
                ),
            )

            # 3. Create derivation links for accepted claims (MEM-016-A)
            if decision == "ACCEPT":
                sup_ids = json.loads(prop["supporting_evidence"])
                for claim in created_claims:
                    for sid in sup_ids:
                        cursor.execute(
                            """
                            INSERT INTO derivation_links (
                                link_id, derived_id, derived_type, source_id,
                                source_type, derivation_method, derived_at, deriving_engine
                            ) VALUES (?, ?, 'CLAIM', ?, 'EXPERIENCE', 'DEVELOPMENT', ?, ?);
                            """,
                            (
                                str(uuid.uuid4()),
                                str(claim.claim_id),
                                str(sid),
                                now_iso,
                                prop["originating_engine"],
                            ),
                        )

            # 4. Emit outbox event
            emit_outbox_event_in_tx(
                cursor=cursor,
                event_name="memory.development_accepted" if decision == "ACCEPT" else "memory.development_rejected",
                event_payload={
                    "proposal_id": str(proposal_id),
                    "created_claim_ids": resulting_ids,
                    "decision": decision,
                },
                source_engine=reviewing_engine,
            )

        if decision == "REJECT" and decision_reason == "EPISTEMIC_UPGRADE_FORBIDDEN":
            raise EpistemicDowngradeError("EPISTEMIC_UPGRADE_FORBIDDEN: Generative engines cannot submit OBSERVATION claims")

        return created_claims

    def execute_independent_pattern_detection(
        self,
        domain_partition: DomainPartition = DomainPartition.COGNITIVE,
        min_co_occurrences: int = 2,
    ) -> List[Tuple[str, str, int]]:
        """
        Kind A: Executes deterministic co-occurrence discovery without external engines.
        """
        return self.patterns.detect_co_occurrence_patterns(
            domain_partition=domain_partition,
            min_co_occurrences=min_co_occurrences,
        )

    @staticmethod
    def calculate_development_priority(
        permanent_importance: float,
        recurrence: float,
        uncertainty: float,
        dependency: float,
        w1: float = 0.4,
        w2: float = 0.2,
        w3: float = 0.2,
        w4: float = 0.2,
        max_recurrence: float = 10.0,
    ) -> float:
        """
        Section 1.9 & Scenario 17:
        Calculates Development Priority P_dev ∈ [0.0, 1.0]:
          P_dev(M) = w1 * I_perm + w2 * R(M) + w3 * U(M) + w4 * D(M)
        where R(M) is normalized recurrence (recurrence / max_recurrence if > 1.0).
        """
        # Normalize recurrence to [0.0, 1.0] if given as raw count
        norm_r = recurrence / max_recurrence if recurrence > 1.0 else recurrence
        norm_r = min(1.0, max(0.0, norm_r))

        norm_i = min(1.0, max(0.0, permanent_importance))
        norm_u = min(1.0, max(0.0, uncertainty))
        norm_d = min(1.0, max(0.0, dependency))

        p_dev = (w1 * norm_i) + (w2 * norm_r) + (w3 * norm_u) + (w4 * norm_d)
        return round(p_dev, 4)
