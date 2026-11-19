"""
Database package for Diva Emotion Engine v1.0.0.
Provides SQLite WAL connection factory, schema definitions, and migration runner.
"""

from emotion_engine.database.connection import DatabaseConnectionFactory
from emotion_engine.database.migrations import MigrationRunner
from emotion_engine.database.schema import SCHEMA_SQL

__all__ = [
    "DatabaseConnectionFactory",
    "MigrationRunner",
    "SCHEMA_SQL",
]
