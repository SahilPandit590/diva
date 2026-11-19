"""
Database migration runner and seed data for Diva Memory Engine v3.0.
"""

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import List, Tuple

from memory_engine.database.connection import DatabaseConnectionFactory
from memory_engine.types.enums import AccessAction, DomainPartition


SEED_POLICIES: List[Tuple[str, str, str, str, List[str], List[str]]] = [
    # (policy_id, target_resource, resource_type, domain_partition, permitted_engines, access_modes)
    (
        "00000000-0000-0000-0000-000000000001",
        "experiences:*",
        "MEMORY",
        "COGNITIVE",
        [
            "PERCEPTION",
            "THOUGHT",
            "COGNITIVE_INTEGRATION",
            "LEARNING",
            "EMOTION",
            "SOCIAL_COGNITION",
            "MOTIVATION",
            "INTERACTION",
            "FEEDBACK",
        ],
        ["READ", "WRITE"],
    ),
    (
        "00000000-0000-0000-0000-000000000002",
        "claims:*",
        "CLAIM",
        "COGNITIVE",
        [
            "THOUGHT",
            "PERCEPTION",
            "USER",
            "LEARNING",
            "FEEDBACK",
            "MEMORY_DEVELOPMENT",
            "COGNITIVE_INTEGRATION",
            "SOCIAL_COGNITION",
            "EMOTION",
        ],
        ["READ", "WRITE", "DEVELOP"],
    ),
    (
        "00000000-0000-0000-0000-000000000003",
        "appraisals:emotion",
        "MEMORY",
        "COGNITIVE",
        ["EMOTION"],
        ["READ", "WRITE"],
    ),
    (
        "00000000-0000-0000-0000-000000000004",
        "appraisals:social",
        "MEMORY",
        "COGNITIVE",
        ["SOCIAL_COGNITION"],
        ["READ", "WRITE"],
    ),
    (
        "00000000-0000-0000-0000-000000000005",
        "knowledge:*",
        "CLAIM",
        "COGNITIVE",
        ["LEARNING"],
        ["READ", "DEVELOP"],
    ),
    (
        "00000000-0000-0000-0000-000000000006",
        "goals:*",
        "CLAIM",
        "COGNITIVE",
        ["MOTIVATION"],
        ["READ"],
    ),
    (
        "00000000-0000-0000-0000-000000000007",
        "continuity:*",
        "MEMORY",
        "COGNITIVE",
        ["COGNITIVE_INTEGRATION"],
        ["READ", "WRITE"],
    ),
    (
        "00000000-0000-0000-0000-000000000008",
        "*",
        "ALL",
        "AUTONOMOUS",
        ["AUTONOMOUS", "AUTONOMOUS_ACTIVITY"],
        ["READ", "WRITE"],
    ),
    (
        "00000000-0000-0000-0000-000000000009",
        "*",
        "ALL",
        "COGNITIVE",
        ["MEMORY_GOVERNANCE", "MEMORY_CONSOLIDATION"],
        ["READ", "WRITE", "UPDATE", "DELETE", "DEVELOP", "AUDIT"],
    ),
    (
        "00000000-0000-0000-0000-00000000000a",
        "feedback:*",
        "CLAIM",
        "COGNITIVE",
        ["FEEDBACK"],
        ["READ", "DEVELOP"],
    ),
    (
        "00000000-0000-0000-0000-00000000000b",
        "experiences:interaction",
        "MEMORY",
        "COGNITIVE",
        ["INTERACTION"],
        ["READ", "WRITE"],
    ),
    (
        "00000000-0000-0000-0000-00000000000c",
        "shared:*",
        "ALL",
        "SHARED",
        ["AUTONOMOUS_ACTIVITY"],
        ["READ"],
    ),
    (
        "00000000-0000-0000-0000-00000000000d",
        "shared:*",
        "ALL",
        "SHARED",
        ["PERCEPTION", "THOUGHT", "EMOTION", "LEARNING", "INTERACTION"],
        ["READ"],
    ),
    (
        "00000000-0000-0000-0000-00000000000e",
        "development:*",
        "ALL",
        "COGNITIVE",
        ["MEMORY_DEVELOPMENT"],
        ["READ", "WRITE", "DEVELOP"],
    ),
]


class MigrationRunner:
    """
    Manages database migrations and seed policy insertion for Diva Memory Engine v3.0.
    """

    def __init__(self, factory: DatabaseConnectionFactory):
        self.factory = factory

    def get_current_version(self) -> int:
        """Return the highest applied schema version, or 0 if none."""
        with self.factory.read_cursor() as cursor:
            # Check if schema_versions table exists
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_versions';"
            )
            if not cursor.fetchone():
                return 0
            cursor.execute("SELECT MAX(version_id) FROM schema_versions;")
            row = cursor.fetchone()
            return row[0] if row and row[0] is not None else 0

    def apply_migrations(self) -> int:
        """
        Applies pending migrations up to the current specification.
        Returns the number of migrations applied.
        """
        current_version = self.get_current_version()
        applied = 0

        if current_version < 1:
            self._apply_v1_migration()
            applied += 1

        return applied

    def _apply_v1_migration(self) -> None:
        """Applies schema version 1 and seeds 14 default access policies."""
        self.factory.initialize_schema()
        now_iso = datetime.now(timezone.utc).isoformat()

        with self.factory.write_transaction() as cursor:
            # Seed 14 access policies
            for policy in SEED_POLICIES:
                pid, target, rtype, part, engines, modes = policy
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO access_policies (
                        policy_id, target_resource, resource_type, domain_partition,
                        permitted_engines, access_modes, created_by, created_at, active
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1);
                    """,
                    (
                        pid,
                        target,
                        rtype,
                        part,
                        json.dumps(engines),
                        json.dumps(modes),
                        "SYSTEM_MIGRATION_V1",
                        now_iso,
                    ),
                )

            # Record migration in schema_versions
            migration_name = "v1_initial_14_domains"
            checksum = hashlib.sha256(migration_name.encode("utf-8")).hexdigest()
            cursor.execute(
                """
                INSERT INTO schema_versions (version_name, applied_at, migration_sql, checksum)
                VALUES (?, ?, ?, ?);
                """,
                (migration_name, now_iso, "INITIAL_DDL_APPLIED", checksum),
            )
