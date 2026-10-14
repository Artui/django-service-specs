"""Helpers shared by the model write service tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django.db import connection
from django.test.utils import CaptureQueriesContext


def savepoints_during(call: Callable[[], Any]) -> list[str]:
    """The ``SAVEPOINT`` statements ``call`` issues, inside the test's own transaction.

    An ``atomic`` block nested in one opens a savepoint, so a service opening a
    transaction of its own shows here. Call an async service through
    ``async_to_sync`` from a sync test: its ORM hops come back to this thread
    and its connection, which the capture watches.
    """
    with CaptureQueriesContext(connection) as queries:
        call()
    return [q["sql"] for q in queries.captured_queries if "SAVEPOINT" in q["sql"].upper()]
