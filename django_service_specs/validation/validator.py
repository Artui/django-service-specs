"""``Validator`` - JSON-like arguments in, validated values out."""

from __future__ import annotations

import abc
from collections.abc import Mapping
from typing import Any, ClassVar

from django_service_specs.parameters.parameters import Parameters
from django_service_specs.validation.validated import Validated
from django_service_specs.validation.validation_context import ValidationContext


class Validator(abc.ABC):
    """The kernel's validation contract.

    ``parameters()`` declares what the Validator takes, and ``validate()``
    turns JSON-like primitives into validated values or raises
    [`InvalidArguments`][django_service_specs.parameters.invalid_arguments.InvalidArguments].
    An adapter reads its library's own declaration into ``parameters()``, and
    must not query doing it: a transport describes a spec before any call.

    **Nominal on purpose.** An adapter subclasses this, and subclassing is the
    opt-in. A structural check on a method name is the gate that lets stock
    classes through by accident: an ``is_valid`` protocol matches a Django form
    and a DRF serializer, and a ``validate`` protocol matches a DRF serializer
    and a pydantic model class, none of which was written to this contract.

    No ``instance`` and no ``many``: the row a call acts on is target
    resolution, and a list is an array parameter. ``partial`` arrives in the
    [`ValidationContext`][django_service_specs.validation.validation_context.ValidationContext]
    rather than as a keyword, because it is the spec's statement about the
    call, not the Validator's: a partial call may leave out any field, and a
    Validator returns only the fields the caller sent, or refuses a partial
    call with ``ImproperlyConfigured`` when what it builds needs every field.
    Ignoring the flag is the one wrong answer, since the omitted fields would
    come back cleaned to blanks and an update would write them.

    ``supports_partial`` says which of the two a Validator does, so a spec
    learns it when it is declared rather than on its first call: a
    ``ServiceSpec`` declaring ``partial=True`` over a Validator whose
    ``supports_partial`` is ``False`` is refused when it is built. ``True``
    by default; ``DataclassValidator`` and ``PydanticValidator`` set it
    ``False``, since each builds every field, and a subclass of either that
    does handle a partial call sets it back. The refusal at the call stays,
    for a Validator called directly.

    **Sync-only.** A Validator may query - a uniqueness check does - so dispatch
    runs it in the executor on the async path, and it must not be ``async def``.

    ``validate()`` receives only the arguments its own ``parameters()``
    declare, already through the shape check. It returns the values the
    operation receives, keyed by name; a nested row may come back as whatever
    the library builds (a dataclass instance, a model instance), since the
    mutation helpers read either.

    ``validated()`` is the call's whole result, and what dispatch asks for: the
    values, the call's ``data``, and any value the Validator binds for the
    call. An adapter overrides it where its ``data`` is not the mapping
    ``validate()`` returns, as the dataclass adapter's is its instance, or
    where the library leaves an object the service may want; the rest need
    not touch it.
    """

    # A class attribute rather than a method: it describes what the class
    # can do with any call, and the spec reads it before there is one.
    supports_partial: ClassVar[bool] = True

    @abc.abstractmethod
    def parameters(self) -> Parameters:
        """What this Validator takes, as a declaration. Never queries."""

    @abc.abstractmethod
    def validate(self, arguments: Mapping[str, Any], context: ValidationContext) -> dict[str, Any]:
        """Validated values, or ``InvalidArguments``. May query; never ``async def``."""

    def validated(self, arguments: Mapping[str, Any], context: ValidationContext) -> Validated:
        """``validate()``'s values, as the call's ``data`` too, with nothing else bound.

        One ``validate()`` call, so a Validator that queries queries once. An
        override returns the same ``values`` its ``validate()`` would, and may
        hand an object as ``data`` and bind values in ``pool``.
        """
        values = self.validate(arguments, context)
        return Validated(values=values, data=values)
