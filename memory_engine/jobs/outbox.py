"""
Transactional outbox manager and publisher for Diva Memory Engine v3.0.
Ensures at-least-once asynchronous event delivery with atomic database commits.
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from memory_engine.database.connection import DatabaseConnectionFactory


def emit_outbox_event_in_tx(
    cursor: Any,
    event_name: str,
    event_payload: Dict[str, Any],
    source_engine: str,
) -> str:
    """
    Appends an event to outbox_events within an ongoing transaction.
    Guarantees event is committed if and only if the business transaction succeeds.
    """
    outbox_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()
    cursor.execute(
        """
        INSERT INTO outbox_events (
            outbox_id, event_name, event_payload, source_engine,
            created_at, published, publish_attempts
        ) VALUES (?, ?, ?, ?, ?, 0, 0);
        """,
        (outbox_id, event_name, json.dumps(event_payload), source_engine, now_iso),
    )
    return outbox_id


class OutboxWorker:
    """
    Worker process that drains unpublished outbox_events and dispatches to subscribers.
    """

    def __init__(self, factory: DatabaseConnectionFactory):
        self.factory = factory
        self._subscribers: Dict[str, List[Callable[[str, Dict[str, Any]], None]]] = {}

    def subscribe(
        self, event_name: str, handler: Callable[[str, Dict[str, Any]], None]
    ) -> None:
        """Register a handler callback for an event name."""
        if event_name not in self._subscribers:
            self._subscribers[event_name] = []
        self._subscribers[event_name].append(handler)

    def process_pending_events(self, batch_size: int = 50) -> int:
        """
        Processes a batch of unpublished events.
        Dispatches to subscribers and marks published on success.
        Returns the count of events successfully published.
        """
        with self.factory.read_cursor() as cursor:
            cursor.execute(
                """
                SELECT outbox_id, event_name, event_payload, source_engine, publish_attempts
                FROM outbox_events
                WHERE published = 0
                ORDER BY created_at ASC
                LIMIT ?;
                """,
                (batch_size,),
            )
            events = cursor.fetchall()

        published_count = 0
        now_iso = datetime.now(timezone.utc).isoformat()

        for event in events:
            outbox_id = event["outbox_id"]
            name = event["event_name"]
            payload = json.loads(event["event_payload"])
            attempts = event["publish_attempts"] + 1

            try:
                # Dispatch to subscribers
                handlers = self._subscribers.get(name, [])
                for handler in handlers:
                    handler(name, payload)

                # Mark published
                with self.factory.write_transaction() as cursor:
                    cursor.execute(
                        """
                        UPDATE outbox_events
                        SET published = 1,
                            published_at = ?,
                            publish_attempts = ?
                        WHERE outbox_id = ?;
                        """,
                        (now_iso, attempts, outbox_id),
                    )
                published_count += 1
            except Exception:
                # Record failed attempt
                with self.factory.write_transaction() as cursor:
                    cursor.execute(
                        """
                        UPDATE outbox_events
                        SET publish_attempts = ?
                        WHERE outbox_id = ?;
                        """,
                        (attempts, outbox_id),
                    )

        return published_count
