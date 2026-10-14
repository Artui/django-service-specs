"""``DeleteService`` - the typed shape of a service that removes the row it resolved."""

from __future__ import annotations

from typing import Any, Protocol, TypeVar

InputT = TypeVar("InputT", contravariant=True)
InstanceT = TypeVar("InstanceT", contravariant=True)
ResultT = TypeVar("ResultT", covariant=True)


class DeleteService(Protocol[InputT, InstanceT, ResultT]):
    """The structural shape of a service that acts on a resolved row, input optional.

    ``instance`` is the row the spec's ``instance_selector_spec`` resolved. Most
    deletes return ``None``.

    ``data`` has a default in the Protocol, so a service that reads no input
    conforms without declaring it: bind ``InputT`` to
    [`NoInput`][django_service_specs.types.no_input.NoInput] and leave ``data``
    out. A delete that does take input - a reason, a confirmation - binds
    ``InputT`` to its input type and declares ``data`` with a default of its
    own, ``data: ReasonInput | None = None``: declared without one it does not
    conform, since the Protocol's caller may leave ``data`` out.

    See [`CreateService`][django_service_specs.services.create_service.CreateService]
    for ``**extras`` and strictly typed extras.
    """

    def __call__(self, *, instance: InstanceT, data: InputT = ..., **extras: Any) -> ResultT: ...
