"""``Presenter`` - a value to JSON-like data, and nothing else."""

from __future__ import annotations

import abc
from typing import Any

from django_service_specs.output.output import Output


class Presenter(abc.ABC):
    """Turns one value an operation produced into JSON-like data.

    ``output()`` declares the result and ``present()`` renders one value. They
    are separate because describing the result is not optional where rendering
    is: an HTML transport hands the object to a template and never renders it,
    but its confirmation page still reads what the result declares.

    ``present`` takes **one** value. A list result is presented item by item by
    dispatch's ``present``, so a Presenter never has to guess whether it was
    handed a row or a collection of them.

    **Sync-only.** Presenting a row that reads a relation is a query, and the
    kernel cannot tell in advance whether the row was prefetched, so the async
    path runs every Presenter in the executor.
    """

    @abc.abstractmethod
    def output(self) -> Output:
        """What ``present`` returns, as a declaration. Never queries."""

    @abc.abstractmethod
    def present(self, value: Any) -> Any:
        """One value to JSON-like data. May query; never ``async def``."""
