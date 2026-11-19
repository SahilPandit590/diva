"""
Enums and constants for Diva Memory Engine v3.0 (Hybrid Memory Architecture).
Enforces exact lifecycle dimension separation, epistemic hierarchy, and domain partitions.
"""

from enum import Enum, IntEnum


class DomainPartition(str, Enum):
    """Memory domain partition for strict cognitive/autonomous separation."""
    COGNITIVE = "COGNITIVE"
    AUTONOMOUS = "AUTONOMOUS"
    SHARED = "SHARED"


class RepresentationType(str, Enum):
    """What kind of memory record is this?"""
    RAW_EXPERIENCE = "RAW_EXPERIENCE"
    EPISODIC = "EPISODIC"
    SEMANTIC = "SEMANTIC"
    AUTOBIOGRAPHICAL = "AUTOBIOGRAPHICAL"
    RELATIONSHIP = "RELATIONSHIP"
    PROCEDURAL = "PROCEDURAL"
    GENERALIZED = "GENERALIZED"
    CONSOLIDATED = "CONSOLIDATED"
    REFLECTIVE = "REFLECTIVE"


class DevelopmentStatus(str, Enum):
    """Dimension 1: Knowledge development lifecycle state."""
    RAW = "RAW"
    ORGANIZED = "ORGANIZED"
    ASSOCIATED = "ASSOCIATED"
    PROPOSED = "PROPOSED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ACCEPTED = "ACCEPTED"
    DISPUTED = "DISPUTED"
    SUPERSEDED = "SUPERSEDED"
    ARCHIVED = "ARCHIVED"


class ValidityStatus(str, Enum):
    """Dimension 2: Real-world truth / validity status."""
    CURRENT = "CURRENT"
    HISTORICAL = "HISTORICAL"
    RETRACTED = "RETRACTED"
    REFUTED = "REFUTED"


class RetentionStatus(str, Enum):
    """Dimension 3: Storage retention state."""
    ACTIVE = "ACTIVE"
    CONSOLIDATED = "CONSOLIDATED"
    DEPENDENCY_LOCKED = "DEPENDENCY_LOCKED"
    ARCHIVAL_ELIGIBLE = "ARCHIVAL_ELIGIBLE"
    ARCHIVED = "ARCHIVED"


class EpistemicType(str, Enum):
    """
    Epistemic origin type of a claim.
    Ranked strictly: OBSERVATION (5) > INFERENCE (4) > REPORTED (3) > INTERPRETATION (2) > OPINION (1) > UNKNOWN (0)
    Summarization/consolidation can NEVER upgrade epistemic rank.
    """
    OBSERVATION = "OBSERVATION"
    INFERENCE = "INFERENCE"
    REPORTED = "REPORTED"
    INTERPRETATION = "INTERPRETATION"
    OPINION = "OPINION"
    UNKNOWN = "UNKNOWN"

    @property
    def rank(self) -> int:
        _RANKS = {
            EpistemicType.OBSERVATION: 5,
            EpistemicType.INFERENCE: 4,
            EpistemicType.REPORTED: 3,
            EpistemicType.INTERPRETATION: 2,
            EpistemicType.OPINION: 1,
            EpistemicType.UNKNOWN: 0,
        }
        return _RANKS[self]


class EvidenceStatus(str, Enum):
    """Corroboration status of a claim across evidence records."""
    UNVERIFIED = "UNVERIFIED"
    SUPPORTED = "SUPPORTED"
    CORROBORATED = "CORROBORATED"
    DISPUTED = "DISPUTED"
    REFUTED = "REFUTED"


class ClaimLifecycle(str, Enum):
    """Operational lifecycle state of a claim."""
    ACTIVE = "ACTIVE"
    HISTORICAL = "HISTORICAL"
    SUPERSEDED = "SUPERSEDED"
    RETRACTED = "RETRACTED"


class EvidenceRole(str, Enum):
    """Role of an evidence reference relative to a claim."""
    SUPPORTS = "SUPPORTS"
    OPPOSES = "OPPOSES"
    CONTEXTUALIZES = "CONTEXTUALIZES"


class ClaimRelationshipType(str, Enum):
    """Typed directional edge between two claims."""
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    DERIVED_FROM = "DERIVED_FROM"
    CORRECTS = "CORRECTS"
    GENERALIZES = "GENERALIZES"
    SPECIALIZES = "SPECIALIZES"
    SUPERSEDES = "SUPERSEDES"
    ASSOCIATED_WITH = "ASSOCIATED_WITH"
    CO_OCCURS_WITH = "CO_OCCURS_WITH"


class MemoryRelationshipType(str, Enum):
    """Typed directional edge between experiences/representations."""
    EXPERIENCED_BEFORE = "EXPERIENCED_BEFORE"
    EXPERIENCED_AFTER = "EXPERIENCED_AFTER"
    ASSOCIATED_WITH = "ASSOCIATED_WITH"
    CAUSED_BY = "CAUSED_BY"
    CAUSED = "CAUSED"
    PART_OF = "PART_OF"
    INSTANCE_OF = "INSTANCE_OF"
    CONTRADICTS = "CONTRADICTS"
    SIMILAR_TO = "SIMILAR_TO"
    DEVELOPED_FROM = "DEVELOPED_FROM"


class EntityType(str, Enum):
    """Categories of recognized entities."""
    PERSON = "PERSON"
    ORGANIZATION = "ORGANIZATION"
    LOCATION = "LOCATION"
    CONCEPT = "CONCEPT"
    SYSTEM = "SYSTEM"
    UNKNOWN = "UNKNOWN"


class EntityStatus(str, Enum):
    """Lifecycle status of an entity record."""
    ACTIVE = "ACTIVE"
    MERGED = "MERGED"
    INACTIVE = "INACTIVE"


class AliasType(str, Enum):
    """Type of entity alias or handle."""
    NICKNAME = "NICKNAME"
    HANDLE = "HANDLE"
    ABBREVIATION = "ABBREVIATION"
    FORMAL_NAME = "FORMAL_NAME"
    SYSTEM_ID = "SYSTEM_ID"


class DevelopmentOperationType(str, Enum):
    """Types of development operations supported by Hybrid Memory Engine."""
    DEDUPLICATION = "DEDUPLICATION"
    ENTITY_LINKING = "ENTITY_LINKING"
    PATTERN_DETECTION = "PATTERN_DETECTION"
    CONTRADICTION_CHECK = "CONTRADICTION_CHECK"
    GENERALIZATION = "GENERALIZATION"
    CAUSAL_INVESTIGATION = "CAUSAL_INVESTIGATION"
    EMOTIONAL_REAPPRAISAL = "EMOTIONAL_REAPPRAISAL"
    SOCIAL_INTERPRETATION = "SOCIAL_INTERPRETATION"
    PROCEDURAL_EXTRACTION = "PROCEDURAL_EXTRACTION"
    CONSOLIDATION = "CONSOLIDATION"


class DevelopmentResultStatus(str, Enum):
    """Outcome status of a development review or execution."""
    ACCEPTED = "ACCEPTED"
    PROPOSED = "PROPOSED"
    REJECTED = "REJECTED"
    DEFERRED = "DEFERRED"


class JobStatus(str, Enum):
    """Background job processing status."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    DEAD_LETTER = "DEAD_LETTER"  # Exhausted all retry attempts; Section 3.11


class AccessAction(str, Enum):
    """Permitted action types in Memory Governance access policies."""
    READ = "READ"
    WRITE = "WRITE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    DEVELOP = "DEVELOP"
    AUDIT = "AUDIT"
    ARCHIVE = "ARCHIVE"  # Retention / cold-archival operations


class AccessEffect(str, Enum):
    """Effect of an evaluated access policy."""
    ALLOW = "ALLOW"
    DENY = "DENY"
