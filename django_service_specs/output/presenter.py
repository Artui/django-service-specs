"""``Presenter`` - a value to JSON-like data, and nothing else."""

from __future__ import annotations

import abc
from typing import Any

from django_service_specs.output.output import Output
from django_service_specs.output.presentation_context import PresentationContext


class Presenter(abc.ABC):
    """Turns one value an operation produced into JSON-like data.

    ``output()`` declares the result and ``present()`` renders one value. They
    are separate because describing the result is not optional where rendering
    is: an HTML transport hands the object to a template and never renders it,
    but its confirmation page still reads what the result declares.

    ``present`` takes **one** value. A list result is presented item by item by
    dispatch's ``present``, so a Presenter never has to guess whether it was
    handed a row or a collection of them.

    ``presented()`` is what dispatch's ``present`` asks for: one value and the
    call's [`PresentationContext`][django_service_specs.output.presentation_context.PresentationContext].
    By default it is ``present(value)``, so a Presenter that reads nothing of
    the call overrides ``present()`` alone. One whose library renders under a
    context - the principal, a request a transport registered as a seed -
    overrides ``presented()`` and reads it there. A method of its own rather
    than a keyword on ``present()``, so every Presenter written against
    ``present(value)`` is still one, and nothing reads a signature to decide
    whether to pass the context.

    **Sync-only.** Presenting a row that reads a relation is a query, and the
    kernel cannot tell in advance whether the row was prefetched, so the async
    path runs every Presenter in the executor. An ``async def`` ``present`` or
    ``presented`` is refused when the spec is built.
    """

    @abc.abstractmethod
    def output(self) -> Output:
        """What ``present`` returns, as a declaration. Never queries."""

    @abc.abstractmethod
    def present(self, value: Any) -> Any:
        """One value to JSON-like data. May query; never ``async def``."""

    def presented(self, value: Any, context: PresentationContext | None) -> Any:
        """One value to JSON-like data, for the call ``context`` describes: ``present(value)``.

        ``context`` is ``None`` for a result dispatch did not build, such as
        a ``DispatchResult`` a transport constructed itself.
        """
        return self.present(value)
