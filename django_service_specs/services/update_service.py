"""``UpdateService`` - the typed shape of a service that changes the row it resolved."""

from __future__ import annotations

from typing import Any, Protocol, TypeVar

InputT = TypeVar("InputT", contravariant=True)
InstanceT = TypeVar("InstanceT", contravariant=True)
ResultT = TypeVar("ResultT", covariant=True)


class UpdateService(Protocol[InputT, InstanceT, ResultT]):
    """The structural shape of a service that acts on a resolved row with validated input.

    ``instance`` is the row the spec's ``instance_selector_spec`` resolved, under
    the pool's reserved ``instance`` seed, and ``data`` what the spec's
    [`Validator`][django_service_specs.validation.validator.Validator] returned.

    See [`CreateService`][django_service_specs.services.create_service.CreateService]
    for ``**extras`` and strictly typed extras.
    """

    def __call__(self, *, instance: InstanceT, data: InputT, **extras: Any) -> ResultT: ...
