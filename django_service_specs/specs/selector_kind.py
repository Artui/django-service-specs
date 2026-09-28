"""``SelectorKind`` - whether a selector returns a collection or one row."""

from __future__ import annotations

from enum import Enum


class SelectorKind(str, Enum):
    """The shape a selector spec returns.

    ``LIST`` returns a collection, a queryset when it can be shaped. ``RETRIEVE``
    returns one row: a queryset is materialized with ``.first()``, and a missing
    row is reported as not found unless the spec allows ``None``.

    Inheriting from ``str`` keeps the value JSON-serializable while still
    behaving as a proper enum for ``is`` / ``==``.
    """

    LIST = "list"
    RETRIEVE = "retrieve"
