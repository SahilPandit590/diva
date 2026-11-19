"""
Knowledge Store Service for Diva Memory Engine v3.0.
Manages atomic claims, assessments, evidence references, contradiction detection (MEM-005),
superseding/versioning (MEM-006), and bitemporal queries.
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from memory_engine.database.connection import DatabaseConnectionFactory
from memory_engine.governance.service import MemoryGovernanceService
from memory_engine.jobs.outbox import emit_outbox_event_in_tx
from memory_engine.types.claim import (
    ClaimAssessment,
    ClaimRelationship,
    EvidenceReference,
    MemoryClaim,
    ProposedClaim,
)
from memory_engine.types.enums import (
    AccessAction,
    ClaimLifecycle,
    ClaimRelationshipType,
    DomainPartition,
    EpistemicType,
    EvidenceRole,
    EvidenceStatus,
)


class KnowledgeStoreService:
    """
    Manages propositional knowledge claims, evidence weighting, version history,
    and bitemporal historical reconstructions.
    """

    def __init__(
        self,
        factory: DatabaseConnectionFactory,
        governance: MemoryGovernanceService,
    ):
        self.factory = factory
        self.governance = governance

    def create_claim(
        self,
        proposal: ProposedClaim,
        session_id: uuid.UUID,
        domain_partition: DomainPartition,
        source_experience_id: Optional[uuid.UUID] = None,
        world_time_start: Optional[datetime] = None,
        world_time_end: Optional[datetime] = None,
        superseding_claim_id: Optional[uuid.UUID] = None,
    ) -> MemoryClaim:
        """
        Creates a new claim from a proposal.
        Enforces MEM-002: source_engine and provenance_hash must be non-null.
        Runs contradiction detection (MEM-005) against existing active claims.
        """
        self.governance.assert_access(
            requesting_engine=proposal.source_engine,
            resource_type="CLAIM",
            domain_partition=domain_partition,
            access_mode=AccessAction.WRITE,
            actor_session=str(session_id),
        )

        claim = self.governance.create_claim_from_proposal(
            proposal=proposal,
            session_id=session_id,
            domain_partition=domain_partition,
            source_experience_id=source_experience_id,
            world_time_start=world_time_start,
            world_time_end=world_time_end,
        )

        now_iso = claim.diva_time_recorded.isoformat()
        claim_dict = claim.model_dump(mode="json")

        with self.factory.write_transaction() as cursor:
            # 1. Insert claim into claims table
            cursor.execute(
                """
                INSERT INTO claims (
                    claim_id, subject_entity_id, predicate, object_value,
                    canonical_statement, epistemic_type, evidence_status,
                    lifecycle, domain_partition, source_engine, source_session_id,
                    source_experience_id, world_time_start, world_time_end,
                    diva_time_recorded, provenance_hash, version, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1);
                """,
                (
                    str(claim.claim_id),
                    str(claim.subject_entity_id) if claim.subject_entity_id else None,
                    claim.predicate,
                    claim.object_value,
                    claim.canonical_statement,
                    claim.epistemic_type.value,
                    claim.evidence_status.value,
                    claim.lifecycle.value,
                    claim.domain_partition.value,
                    claim.source_engine,
                    str(claim.source_session_id),
                    str(claim.source_experience_id) if claim.source_experience_id else None,
                    claim.world_time_start.isoformat() if claim.world_time_start else None,
                    claim.world_time_end.isoformat() if claim.world_time_end else None,
                    now_iso,
                    claim.provenance_hash,
                ),
            )

            # 2. Insert initial claim_versions record
            version_id = str(uuid.uuid4())
            cursor.execute(
                """
                INSERT INTO claim_versions (
                    version_id, claim_id, version_number, previous_version,
                    change_type, old_state, new_state, changed_by,
                    change_reason, changed_at
                ) VALUES (?, ?, 1, NULL, 'INITIAL_CREATION', '{}', ?, ?, 'Initial proposition creation', ?);
                """,
                (
                    version_id,
                    str(claim.claim_id),
                    json.dumps(claim_dict),
                    claim.source_engine,
                    now_iso,
                ),
            )

            # 3. Contradiction Detection Algorithm (MEM-005)
            # Find active claims with same subject and predicate but conflicting object_value.
            # Section 3.2: only flag contradiction when world_time ranges OVERLAP.
            # NULL world_time_start means "from the beginning of time" (open-ended past).
            # NULL world_time_end means "still current" (open-ended future → infinity).
            # Two intervals [A_start, A_end] and [B_start, B_end] overlap when:
            #   NOT (A_end < B_start OR B_end < A_start)
            # Treating NULL ends as ∞ and NULL starts as -∞.
            if claim.subject_entity_id:
                new_start = claim.world_time_start.isoformat() if claim.world_time_start else None
                new_end = claim.world_time_end.isoformat() if claim.world_time_end else None

                query = """
                    SELECT claim_id, object_value, canonical_statement, evidence_status,
                           version, world_time_start, world_time_end
                    FROM claims
                    WHERE subject_entity_id = ?
                      AND predicate = ?
                      AND object_value != ?
                      AND lifecycle = 'ACTIVE'
                      AND claim_id != ?
                """
                params = [
                    str(claim.subject_entity_id),
                    claim.predicate,
                    claim.object_value,
                    str(claim.claim_id),
                ]
                if superseding_claim_id:
                    query += " AND claim_id != ?"
                    params.append(str(superseding_claim_id))

                cursor.execute(query, params)
                conflicts = cursor.fetchall()

                for conflict in conflicts:
                    # World-time overlap check (Section 3.2)
                    # existing claim interval: [conflict.world_time_start, conflict.world_time_end]
                    # new claim interval:      [new_start, new_end]
                    # Both NULL = open-ended → always overlaps
                    ex_start = conflict["world_time_start"]  # may be None
                    ex_end = conflict["world_time_end"]      # may be None

                    # Overlap condition: NOT (new_end < ex_start OR ex_end < new_start)
                    # None end = ∞ → new_end < ex_start → False when new_end is None
                    # None start = -∞ → ex_end < new_start → False when new_start is None
                    no_overlap = (
                        (new_end is not None and ex_start is not None and new_end < ex_start)
                        or (ex_end is not None and new_start is not None and ex_end < new_start)
                    )
                    if no_overlap:
                        continue  # Different time periods — no contradiction

                    conflicting_id = conflict["claim_id"]
                    rel_id = str(uuid.uuid4())

                    # Insert CONTRADICTS relationship
                    cursor.execute(
                        """
                        INSERT INTO claim_relationships (
                            relationship_id, claim_id_source, claim_id_target,
                            relationship_type, confidence, established_by, established_at
                        ) VALUES (?, ?, ?, 'CONTRADICTS', 1.0, 'CONTRADICTION_DETECTOR', ?);
                        """,
                        (rel_id, str(claim.claim_id), conflicting_id, now_iso),
                    )

                    # Mark existing conflicting claim as DISPUTED
                    new_conf_version = conflict["version"] + 1
                    cursor.execute(
                        """
                        UPDATE claims
                        SET evidence_status = 'DISPUTED', version = ?
                        WHERE claim_id = ?;
                        """,
                        (new_conf_version, conflicting_id),
                    )
                    cursor.execute(
                        """
                        INSERT INTO claim_versions (
                            version_id, claim_id, version_number, change_type,
                            old_state, new_state, changed_by, change_reason, changed_at
                        ) VALUES (?, ?, ?, 'STATUS_UPDATE', ?, ?, 'CONTRADICTION_DETECTOR', 'Contradicting claim detected', ?);
                        """,
                        (
                            str(uuid.uuid4()),
                            conflicting_id,
                            new_conf_version,
                            json.dumps({"evidence_status": conflict["evidence_status"]}),
                            json.dumps({"evidence_status": "DISPUTED"}),
                            now_iso,
                        ),
                    )

                    # Mark this new claim as DISPUTED too
                    cursor.execute(
                        """
                        UPDATE claims SET evidence_status = 'DISPUTED' WHERE claim_id = ?;
                        """,
                        (str(claim.claim_id),),
                    )
                    claim = claim.model_copy(update={"evidence_status": EvidenceStatus.DISPUTED})

            # 4. Outbox and Audit
            emit_outbox_event_in_tx(
                cursor=cursor,
                event_name="memory.claim_created",
                event_payload={"claim_id": str(claim.claim_id), "predicate": claim.predicate},
                source_engine="KNOWLEDGE_STORE",
            )
            self.governance.log_audit_event_in_tx(
                cursor=cursor,
                event_type="CLAIM_CREATED",
                target_id=str(claim.claim_id),
                target_type="CLAIM",
                actor_engine=claim.source_engine,
                actor_session=str(session_id),
                new_state=claim_dict,
            )

        return claim

    def add_evidence(
        self,
        claim_id: uuid.UUID,
        relationship: EvidenceRole,
        weight: float = 1.0,
        source_memory_id: Optional[uuid.UUID] = None,
        source_claim_id: Optional[uuid.UUID] = None,
        added_by: str = "THOUGHT",
    ) -> EvidenceReference:
        """
        Adds evidential link and re-evaluates claim evidence_status.
        """
        evidence_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()

        with self.factory.write_transaction() as cursor:
            # Insert evidence reference
            cursor.execute(
                """
                INSERT INTO evidence_references (
                    evidence_id, claim_id, source_memory_id, source_claim_id,
                    relationship, weight, added_by, added_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    str(evidence_id),
                    str(claim_id),
                    str(source_memory_id) if source_memory_id else None,
                    str(source_claim_id) if source_claim_id else None,
                    relationship.value,
                    weight,
                    added_by,
                    now_iso,
                ),
            )

            # Recalculate evidence_status
            cursor.execute(
                """
                SELECT relationship, count(*) as cnt
                FROM evidence_references
                WHERE claim_id = ?
                GROUP BY relationship;
                """,
                (str(claim_id),),
            )
            counts = {row["relationship"]: row["cnt"] for row in cursor.fetchall()}

            new_status = EvidenceStatus.UNVERIFIED
            if counts.get("OPPOSES", 0) > 0:
                new_status = EvidenceStatus.DISPUTED
            elif counts.get("SUPPORTS", 0) >= 2:
                new_status = EvidenceStatus.CORROBORATED
            elif counts.get("SUPPORTS", 0) == 1:
                new_status = EvidenceStatus.SUPPORTED

            # Check previous status and version
            cursor.execute(
                "SELECT evidence_status, version FROM claims WHERE claim_id = ?;",
                (str(claim_id),),
            )
            curr = cursor.fetchone()
            if curr and curr["evidence_status"] != new_status.value:
                new_ver = curr["version"] + 1
                cursor.execute(
                    """
                    UPDATE claims
                    SET evidence_status = ?, version = ?
                    WHERE claim_id = ?;
                    """,
                    (new_status.value, new_ver, str(claim_id)),
                )
                cursor.execute(
                    """
                    INSERT INTO claim_versions (
                        version_id, claim_id, version_number, change_type,
                        old_state, new_state, changed_by, change_reason, changed_at
                    ) VALUES (?, ?, ?, 'EVIDENCE_ADDED', ?, ?, ?, 'Evidence recalculation', ?);
                    """,
                    (
                        str(uuid.uuid4()),
                        str(claim_id),
                        new_ver,
                        json.dumps({"evidence_status": curr["evidence_status"]}),
                        json.dumps({"evidence_status": new_status.value}),
                        added_by,
                        now_iso,
                    ),
                )

        return EvidenceReference(
            evidence_id=evidence_id,
            claim_id=claim_id,
            source_memory_id=source_memory_id,
            source_claim_id=source_claim_id,
            relationship=relationship,
            weight=weight,
            added_at=now,
        )

    def supersede_claim(
        self,
        original_claim_id: uuid.UUID,
        new_proposal: ProposedClaim,
        session_id: uuid.UUID,
        domain_partition: DomainPartition,
        reason: str = "Updated with more precise information",
        world_time_start: Optional[datetime] = None,
        world_time_end: Optional[datetime] = None,
    ) -> Tuple[MemoryClaim, MemoryClaim]:
        """
        Implements MEM-006: Submitting a corrected claim creates a SUPERSEDES relationship.
        Original claim transitions to SUPERSEDED, while original content remains completely unchanged.
        """
        # 1. Create the new correcting claim, suppressing contradiction with original_claim_id
        new_claim = self.create_claim(
            proposal=new_proposal,
            session_id=session_id,
            domain_partition=domain_partition,
            superseding_claim_id=original_claim_id,
            world_time_start=world_time_start,
            world_time_end=world_time_end,
        )

        now_iso = datetime.now(timezone.utc).isoformat()

        with self.factory.write_transaction() as cursor:
            # 2. Fetch original claim state
            cursor.execute(
                "SELECT * FROM claims WHERE claim_id = ?;",
                (str(original_claim_id),),
            )
            orig_row = cursor.fetchone()
            if not orig_row:
                raise ValueError(f"Claim {original_claim_id} does not exist.")

            orig_version = orig_row["version"] + 1

            # 3. Update original claim lifecycle to SUPERSEDED
            cursor.execute(
                """
                UPDATE claims
                SET lifecycle = 'SUPERSEDED', version = ?
                WHERE claim_id = ?;
                """,
                (orig_version, str(original_claim_id)),
            )

            # 4. Insert version record for original claim
            cursor.execute(
                """
                INSERT INTO claim_versions (
                    version_id, claim_id, version_number, change_type,
                    old_state, new_state, changed_by, change_reason, changed_at
                ) VALUES (?, ?, ?, 'LIFECYCLE_CHANGE', ?, ?, ?, ?, ?);
                """,
                (
                    str(uuid.uuid4()),
                    str(original_claim_id),
                    orig_version,
                    json.dumps({"lifecycle": orig_row["lifecycle"]}),
                    json.dumps({"lifecycle": "SUPERSEDED"}),
                    new_proposal.source_engine,
                    reason,
                    now_iso,
                ),
            )

            # 5. Insert SUPERSEDES relationship in claim_relationships
            cursor.execute(
                """
                INSERT INTO claim_relationships (
                    relationship_id, claim_id_source, claim_id_target,
                    relationship_type, confidence, established_by, established_at
                ) VALUES (?, ?, ?, 'SUPERSEDES', 1.0, ?, ?);
                """,
                (
                    str(uuid.uuid4()),
                    str(new_claim.claim_id),
                    str(original_claim_id),
                    new_proposal.source_engine,
                    now_iso,
                ),
            )

        updated_orig = self.get_claim(original_claim_id)
        assert updated_orig is not None
        return new_claim, updated_orig

    def get_claim(self, claim_id: uuid.UUID) -> Optional[MemoryClaim]:
        """Fetch a single claim by its UUID."""
        with self.factory.read_cursor() as cursor:
            cursor.execute(
                "SELECT * FROM claims WHERE claim_id = ?;",
                (str(claim_id),),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return MemoryClaim(
                claim_id=uuid.UUID(row["claim_id"]),
                subject_entity_id=uuid.UUID(row["subject_entity_id"]) if row["subject_entity_id"] else None,
                predicate=row["predicate"],
                object_value=row["object_value"],
                canonical_statement=row["canonical_statement"],
                epistemic_type=EpistemicType(row["epistemic_type"]),
                evidence_status=EvidenceStatus(row["evidence_status"]),
                lifecycle=ClaimLifecycle(row["lifecycle"]),
                domain_partition=DomainPartition(row["domain_partition"]),
                source_engine=row["source_engine"],
                source_session_id=uuid.UUID(row["source_session_id"]),
                source_experience_id=uuid.UUID(row["source_experience_id"]) if row["source_experience_id"] else None,
                world_time_start=datetime.fromisoformat(row["world_time_start"]) if row["world_time_start"] else None,
                world_time_end=datetime.fromisoformat(row["world_time_end"]) if row["world_time_end"] else None,
                diva_time_recorded=datetime.fromisoformat(row["diva_time_recorded"]),
                provenance_hash=row["provenance_hash"],
                version=row["version"],
            )

    def query_bitemporal_world_time(
        self,
        world_target_time: datetime,
        subject_entity_id: Optional[uuid.UUID] = None,
        domain_partition: DomainPartition = DomainPartition.COGNITIVE,
    ) -> List[MemoryClaim]:
        """
        Query A: "What was true in the real world at time T?"
        Matches claims where world_time_start <= T and (world_time_end is NULL or > T)
        and lifecycle != 'RETRACTED' / 'REFUTED'.
        """
        t_iso = world_target_time.isoformat()
        with self.factory.read_cursor() as cursor:
            query = """
                SELECT * FROM claims
                WHERE domain_partition = ?
                  AND lifecycle != 'RETRACTED'
                  AND lifecycle != 'REFUTED'
                  AND (world_time_start IS NULL OR world_time_start <= ?)
                  AND (world_time_end IS NULL OR world_time_end > ?)
            """
            params: List[Any] = [domain_partition.value, t_iso, t_iso]
            if subject_entity_id:
                query += " AND subject_entity_id = ?"
                params.append(str(subject_entity_id))

            cursor.execute(query, params)
            rows = cursor.fetchall()

        return [
            MemoryClaim(
                claim_id=uuid.UUID(r["claim_id"]),
                subject_entity_id=uuid.UUID(r["subject_entity_id"]) if r["subject_entity_id"] else None,
                predicate=r["predicate"],
                object_value=r["object_value"],
                canonical_statement=r["canonical_statement"],
                epistemic_type=EpistemicType(r["epistemic_type"]),
                evidence_status=EvidenceStatus(r["evidence_status"]),
                lifecycle=ClaimLifecycle(r["lifecycle"]),
                domain_partition=DomainPartition(r["domain_partition"]),
                source_engine=r["source_engine"],
                source_session_id=uuid.UUID(r["source_session_id"]),
                source_experience_id=uuid.UUID(r["source_experience_id"]) if r["source_experience_id"] else None,
                world_time_start=datetime.fromisoformat(r["world_time_start"]) if r["world_time_start"] else None,
                world_time_end=datetime.fromisoformat(r["world_time_end"]) if r["world_time_end"] else None,
                diva_time_recorded=datetime.fromisoformat(r["diva_time_recorded"]),
                provenance_hash=r["provenance_hash"],
                version=r["version"],
            )
            for r in rows
        ]

    def query_bitemporal_diva_time(
        self,
        diva_target_time: datetime,
        subject_entity_id: Optional[uuid.UUID] = None,
        domain_partition: DomainPartition = DomainPartition.COGNITIVE,
    ) -> List[Dict[str, Any]]:
        """
        Query B: "What did Diva believe at her internal time T_diva?"
        Reconstructs state by taking the latest version of claims recorded on or before T_diva.
        """
        t_iso = diva_target_time.isoformat()
        with self.factory.read_cursor() as cursor:
            query = """
                WITH latest_ver AS (
                    SELECT cv.claim_id, MAX(cv.version_number) as max_v
                    FROM claim_versions cv
                    JOIN claims c ON c.claim_id = cv.claim_id
                    WHERE cv.changed_at <= ?
                      AND c.domain_partition = ?
                    GROUP BY cv.claim_id
                )
                SELECT c.claim_id, c.subject_entity_id, c.predicate, c.canonical_statement,
                       cv.new_state, cv.changed_at
                FROM latest_ver lv
                JOIN claims c ON c.claim_id = lv.claim_id
                JOIN claim_versions cv ON cv.claim_id = lv.claim_id AND cv.version_number = lv.max_v
            """
            params: List[Any] = [t_iso, domain_partition.value]
            if subject_entity_id:
                query += " WHERE c.subject_entity_id = ?"
                params.append(str(subject_entity_id))

            cursor.execute(query, params)
            rows = cursor.fetchall()

        results = []
        for r in rows:
            state = json.loads(r["new_state"])
            results.append({
                "claim_id": r["claim_id"],
                "predicate": r["predicate"],
                "canonical_statement": r["canonical_statement"],
                "effective_state": state,
                "as_of_time": r["changed_at"],
            })
        return results
