"""
Governance exceptions for Diva Memory Engine v3.0.
"""


class MemoryGovernanceError(Exception):
    """Base exception for all memory governance violations."""
    pass


class MemoryAccessDeniedError(MemoryGovernanceError):
    """Raised when an engine attempts an unauthorized read, write, or modification."""
    pass


class PartitionViolationError(MemoryGovernanceError):
    """Raised when an engine attempts cross-partition access (e.g. Cognitive reading Autonomous)."""
    pass


class EpistemicDowngradeError(MemoryGovernanceError):
    """Raised when an operation attempts to upgrade or downgrade epistemic types illegally (MEM-003)."""
    pass
