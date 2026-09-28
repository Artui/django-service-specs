"""``Validator`` - JSON-like arguments in, validated values out."""

from __future__ import annotations

import abc
from collections.abc import Mapping
from typing import Any

from django_service_specs.parameters.parameters import Parameters
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

    No ``partial``, no ``instance``, no ``many``. Those are one HTTP
    framework's update and list semantics: off HTTP, what an update may omit is
    a property of the declared parameters, the row it acts on is target
    resolution, and a list is an array parameter.

    **Sync-only.** A Validator may query - a uniqueness check does - so dispatch
    runs it in the executor on the async path, and it must not be ``async def``.

    ``validate()`` receives only the arguments its own ``parameters()``
    declare, already through the shape check. It returns the values the
    operation receives, keyed by name; a nested row may come back as whatever
    the library builds (a dataclass instance, a model instance), since the
    mutation helpers read either.
    """

    @abc.abstractmethod
    def parameters(self) -> Parameters:
        """What this Validator takes, as a declaration. Never queries."""

    @abc.abstractmethod
    def validate(self, arguments: Mapping[str, Any], context: ValidationContext) -> dict[str, Any]:
        """Validated values, or ``InvalidArguments``. May query; never ``async def``."""
