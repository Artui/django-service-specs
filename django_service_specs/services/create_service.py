"""``CreateService`` - the typed shape of a service that creates from its arguments."""

from __future__ import annotations

from typing import Any, Protocol, TypeVar

InputT = TypeVar("InputT", contravariant=True)
ResultT = TypeVar("ResultT", covariant=True)


class CreateService(Protocol[InputT, ResultT]):
    """The structural shape of a service that takes validated input and no target.

    ``data`` is what the spec's
    [`Validator`][django_service_specs.validation.validator.Validator] returned,
    under the pool's reserved ``data`` seed. ``**extras`` absorbs whatever else
    the keyword pool delivers - ``user``, a registered seed, the spec's
    ``kwargs`` - without the service declaring each key. It is typed ``Any`` so
    a service conforms under every type checker.

    Nothing reads the Protocol at run time: dispatch binds a service from the
    keywords it declares whatever it is annotated with, so conforming is a
    claim checked by a type checker, through
    [`implements`][django_service_specs.services.implements.implements].

    Strictly typed extras stay possible on the service's own signature: declare
    them as a ``TypedDict`` whose keys are all ``NotRequired`` and annotate
    ``**extras: Unpack[YourExtras]``, so ``extras["tenant"]`` is typed in the
    body. ``NotRequired`` because the Protocol's caller may not supply them.
    The Protocol carries no type argument for the extras, since that
    cross-check is not portable across type checkers.
    """

    def __call__(self, *, data: InputT, **extras: Any) -> ResultT: ...
