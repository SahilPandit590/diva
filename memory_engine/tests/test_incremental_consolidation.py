"""
Unit tests for Incremental Consolidation Loop (Section 3.8).
"""

import uuid
import pytest
from memory_engine.consolidation.incremental import IncrementalConsolidator
from memory_engine.consolidation.seven_gate import SevenGateConsolidator
from memory_engine.database.connection import DatabaseConnectionFactory
from memory_engine.database.migrations import MigrationRunner
from memory_engine.entities.service import EntityAssociationService
from memory_engine.governance.service import MemoryGovernanceService
from memory_engine.intake.pipeline import MemoryIntakeService
from memory_engine.jobs.scheduler import BackgroundJobScheduler
from memory_engine.types.enums import DomainPartition, EntityType


@pytest.fixture
def consol_stack():
    factory = DatabaseConnectionFactory(":memory:")
    runner = MigrationRunner(factory)
    runner.apply_migrations()
    governance = MemoryGovernanceService(factory)
    scheduler = BackgroundJobScheduler(factory)
    entities = EntityAssociationService(factory, governance)
    intake = MemoryIntakeService(factory, governance, scheduler)
    seven_gate = SevenGateConsolidator(factory, governance)
    loop = IncrementalConsolidator(factory, seven_gate)
    yield loop, intake, entities, factory
    factory.close()


def test_incremental_consolidation_cycle(consol_stack):
    """Verifies that an incremental cycle clusters active memories, consolidates, and updates retention."""
    loop, intake, entities, factory = consol_stack
    session_id = uuid.uuid4()

    # Pre-register common entity
    project = entities.create_or_get_entity("Project Pegasus", EntityType.CONCEPT)

    # Ingest 3 related experiences with this entity
    for i in range(3):
        intake.submit_input(
            source_engine="PERCEPTION",
            channel="TEXT",
            domain_partition=DomainPartition.COGNITIVE,
            session_id=session_id,
            raw_content=f"Project Pegasus milestone {i}: Architecture module verification succeeded.",
            participants=[project.entity_id],
            importance_flag=True,
        )

    # Run incremental consolidation cycle
    results = loop.run_incremental_cycle(
        domain_partition=DomainPartition.COGNITIVE,
        min_cluster_size=2,
    )

    assert len(results) >= 1
    repr_id, source_ids = results[0]
    assert repr_id is not None
    assert len(source_ids) == 3

    # Verify source memories are now CONSOLIDATED
    with factory.read_cursor() as cursor:
        placeholders = ",".join("?" for _ in source_ids)
        cursor.execute(
            f"SELECT count(*) FROM experiences WHERE experience_id IN ({placeholders}) AND retention_status = 'CONSOLIDATED';",
            tuple(str(s) for s in source_ids),
        )
        assert cursor.fetchone()[0] == 3
