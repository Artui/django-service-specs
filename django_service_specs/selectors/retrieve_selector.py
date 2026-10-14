"""``RetrieveSelector`` - the typed shape of a ``RETRIEVE`` selector."""

from __future__ import annotations

from typing import Any, Protocol, TypeVar

ResultT = TypeVar("ResultT", covariant=True)


class RetrieveSelector(Protocol[ResultT]):
    """The structural shape of the ``selector`` of a ``RETRIEVE`` ``SelectorSpec``.

    It returns the one row, or ``None`` for a row that is not there, which
    dispatch answers as not-found unless the spec declares ``allow_none``. A
    selector returning a queryset, which dispatch collapses to its one row,
    binds ``ResultT`` to the queryset's type. The lookup the spec ``reads`` -
    typically ``pk`` - arrives through ``**extras`` with every other keyword.

    See [`CreateService`][django_service_specs.services.create_service.CreateService]
    for ``**extras`` and strictly typed extras.
    """

    def __call__(self, **extras: Any) -> ResultT | None: ...
