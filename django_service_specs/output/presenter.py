from __future__ import annotations

import abc
from collections.abc import Sequence
from typing import Any

from django_service_specs.output.output import Output
from django_service_specs.output.presentation_context import PresentationContext


class Presenter(abc.ABC):
    """Turns one value an operation produced into JSON-like data."""

    @abc.abstractmethod
    def output(self) -> Output:
        """What ``present`` returns, as a declaration. Never queries."""

    @abc.abstractmethod
    def present(self, value: Any) -> Any:
        """One value to JSON-like data. May query; never ``async def``."""

    def presented(self, value: Any, context: PresentationContext | None) -> Any:
        """One value to JSON-like data, for the call ``context`` describes: ``present(value)``."""
        return self.present(value)

    def presented_rows(
        self, values: Sequence[Any], context: PresentationContext | None
    ) -> list[Any]:
        """Every row of a list to JSON-like data, in one call: ``presented()`` per row."""
        return [self.presented(value, context) for value in values]
