from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal

from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone
from django.utils.dateparse import parse_datetime

_JSON_TYPES: Final = ("string", "number", "integer", "boolean")
"""What a formatter may declare it produces.

Scalars only, and the omission of ``array`` and ``object`` is deliberate. A
container is described by the schema of its members, and ``schema`` cannot
carry member schemas by design, so a formatter producing one could only ever
advertise ``{"type": "object"}``, which is true and tells a reader nothing.
The transforms this exists for - a formatted timestamp, money with its
currency, a duration, a quantity with its unit - all produce scalars.
"""

_TIMESTAMP_FORMAT: Final = "%d %b %Y %H:%M"
"""Day-month-year, so no reader has to guess which of the first two numbers is
the month. ``strftime`` codes rather than Django's own format characters: the
value reaching a formatter is what the presenter returned, which for a
date-time is usually its ISO-8601 string, so the standard library's parse and
format pair is the one that round-trips it.
"""

_EXAMPLE_MOMENT: Final = datetime(2026, 1, 31, 14, 5, 9)
"""The instant every ``timestamp()`` example is rendered from.

A day past the twelfth and an hour past noon, so an example distinguishes
day-first from month-first and 24-hour from 12-hour. Naive on purpose: an
example is a shape, and a zone in it would read as a promise about which zone
the field is rendered in, which is exactly what this refuses to claim.
"""


@dataclass(frozen=True, slots=True)
class ValueFormatter:
    """One field's value, transformed for an agent audience, plus what that yields."""

    render: Callable[[Any], Any]
    """The transform, applied to the presented value.

    Called with what the presenter returned, not with a model attribute: the
    projection runs after presenting, so a date-time a
    [`DataclassPresenter`][django_service_specs.adapters.dataclass.dataclass_presenter.DataclassPresenter]
    presented arrives as its ISO-8601 string, and a decimal as its string.
    Never called with ``None``; see
    [`apply`][django_service_specs.types.value_formatter.ValueFormatter.apply].
    """

    produces: Literal["string", "number", "integer", "boolean"]
    """The JSON type ``render`` returns. Written into the schema by the kernel."""

    schema: Mapping[str, Any] | None = None
    """Extra JSON Schema keywords, merged over the written type.

    For saying what the produced value *looks like*: ``description``,
    ``examples``, ``format``. May not contain ``type``.
    """

    def __post_init__(self) -> None:
        if self.produces not in _JSON_TYPES:
            raise ImproperlyConfigured(
                f"ValueFormatter(produces={self.produces!r}) is not a JSON type. "
                f"Use one of {', '.join(_JSON_TYPES)}."
            )
        if self.schema is not None and "type" in self.schema:
            raise ImproperlyConfigured(
                "ValueFormatter(schema=...) may not set 'type' - produces= is what "
                "declares it, so a formatter cannot contradict its own advertisement. "
                f"Set produces={self.schema['type']!r} instead."
            )

    def apply(self, value: Any) -> Any:
        """``render(value)``, except that ``None`` passes straight through."""
        return None if value is None else self.render(value)

    def json_schema(self) -> dict[str, Any]:
        """The declared type, with ``schema`` merged over it."""
        return {**(self.schema or {}), "type": self.produces}

    @classmethod
    def timestamp(cls, fmt: str | None = None) -> ValueFormatter:
        """A date-time as a formatted local string, with an example of the shape."""

        resolved = fmt or _TIMESTAMP_FORMAT

        def render(value: Any) -> Any:
            return _local_datetime(value, resolved)

        return cls(render, "string", {"examples": [_EXAMPLE_MOMENT.strftime(resolved)]})


def _local_datetime(value: Any, fmt: str) -> Any:
    """``value`` as a ``fmt``-formatted string in the active zone, or unchanged."""
    moment = value if isinstance(value, datetime) else _parsed(value)
    if moment is None:
        return value
    if timezone.is_aware(moment):
        moment = timezone.localtime(moment)
    return moment.strftime(fmt)


def _parsed(value: Any) -> datetime | None:
    """``value`` read as a date-time string, or ``None`` if it is not one."""
    if not isinstance(value, str):
        return None
    try:
        return parse_datetime(value)
    except ValueError:
        return None
