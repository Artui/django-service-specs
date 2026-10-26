"""``Presenter`` - a value to JSON-like data, and nothing else."""

from __future__ import annotations

import abc
from collections.abc import Sequence
from typing import Any

from django_service_specs.output.output import Output
from django_service_specs.output.presentation_context import PresentationContext


class Presenter(abc.ABC):
    """Turns one value an operation produced into JSON-like data.

    ``output()`` declares the result and ``present()`` renders one value. They
    are separate because describing the result is not optional where rendering
    is: an HTML transport hands the object to a template and never renders it,
    but its confirmation page still reads what the result declares.

    ``present`` takes **one** value. A list result is handed to
    ``presented_rows()`` whole, which by default presents it item by item, so a
    Presenter never has to guess whether it was handed a row or a collection of
    them.

    ``presented()`` is what dispatch's ``present`` asks for a single value: one
    value and the call's [`PresentationContext`][django_service_specs.output.presentation_context.PresentationContext].
    By default it is ``present(value)``, so a Presenter that reads nothing of
    the call overrides ``present()`` alone. One whose library renders under a
    context - the principal, a request a transport registered as a seed -
    overrides ``presented()`` and reads it there. A method of its own rather
    than a keyword on ``present()``, so every Presenter written against
    ``present(value)`` is still one, and nothing reads a signature to decide
    whether to pass the context.

    ``presented_rows()`` is what it asks for a list: every row it presents at
    once - a transport serving one page has already sliced the result, so the
    page's rows - and the same context. By default it is ``presented()`` per
    row, so only a Presenter that batches something over the rows overrides
    it: one lookup for every row on the page rather than one per row, or a
    library whose list rendering takes the collection.

    **Sync-only.** Presenting a row that reads a relation is a query, and the
    kernel cannot tell in advance whether the row was prefetched, so the async
    path runs every Presenter in the executor. An ``async def`` ``present`` or
    ``presented`` is refused when the spec is built, and an answer from any of
    the three that is still to be awaited is refused where it is read.
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

    def presented_rows(
        self, values: Sequence[Any], context: PresentationContext | None
    ) -> list[Any]:
        """Every row of a list to JSON-like data, in one call: ``presented()`` per row.

        ``values`` is a tuple of the rows being presented, already evaluated,
        so it can be walked as often as a batched lookup needs. Return a
        list with one presented value per row, **in the order given**: a
        selector spec's affordances are added to each presented row by its
        position, so dispatch's ``present`` refuses an answer that is not a
        list or whose length differs from ``values``. ``context`` is the one
        every row of the result shares, as ``presented()`` receives it.
        """
        return [self.presented(value, context) for value in values]
