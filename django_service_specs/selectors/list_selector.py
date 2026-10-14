"""``ListSelector`` - the typed shape of a ``LIST`` selector."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Protocol, TypeVar

ResultT = TypeVar("ResultT", covariant=True)


class ListSelector(Protocol[ResultT]):
    """The structural shape of the ``selector`` of a ``LIST`` ``SelectorSpec``.

    It returns the rows, a queryset or any other iterable; a queryset is what
    the spec's shaping (``extend_queryset`` and its peers) can act on. Every
    keyword arrives through ``**extras``.

    See [`CreateService`][django_service_specs.services.create_service.CreateService]
    for ``**extras`` and strictly typed extras.
    """

    def __call__(self, **extras: Any) -> Iterable[ResultT]: ...
