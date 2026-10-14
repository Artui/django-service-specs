"""``Validator`` - JSON-like arguments in, validated values out."""

from __future__ import annotations

import abc
from collections.abc import Mapping
from typing import Any

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.parameters.invalid_arguments import InvalidArguments
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

    No ``instance`` and no ``many`` keyword: the row a call acts on is target
    resolution, and a ``many`` spec's list is handed to ``validated_many()``,
    a method of its own. ``partial`` arrives in the
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
    ``False`` as a class attribute, since each builds every field, and a
    subclass of either that does handle a partial call sets it back. An
    adapter whose answer depends on what it was built over sets it on the
    instance in ``__init__`` instead, and the spec reads the instance. The
    refusal at the call stays, for a Validator called directly.

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

    ``validated_many()`` is what dispatch asks of a ``many`` spec instead: the
    whole list at once. By default it is ``validated()`` on each row, which
    serves a Validator whose library validates one row at a time. An adapter
    whose library validates a list as one, running list-level checks and
    binding one object for the call, overrides it.
    """

    # An attribute rather than a method: it describes what the Validator can
    # do with any call, and the spec reads it before there is one. Not a
    # ``ClassVar``, so an instance may answer for itself: one adapter class
    # wraps libraries that differ here, and only ``__init__`` knows which.
    supports_partial: bool = True

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

    def validated_many(
        self,
        rows: Mapping[int, Mapping[str, Any]],
        context: ValidationContext,
        *,
        many_argument: str,
    ) -> Validated:
        """A ``many`` call's rows, validated as one call: what dispatch asks of a ``many`` spec.

        ``rows`` maps each row's index in the caller's list to its arguments,
        already through the shape check, with the spec's ``input_data`` merged
        over each and only the keys ``parameters()`` declares, as on a single
        call. A row the shape check refused is not among them, so the indices
        may have gaps: an override validating a list maps its library's
        positions back through ``list(rows)``, and a list-level verdict it
        reaches sees only the rows handed to it.

        Returns the call's ``Validated``: ``values`` holds the rows' values as
        a list under ``many_argument`` and nothing else, since a row's fields
        are never spread into the service's keywords; ``data`` is the list a
        service declaring ``data`` receives; ``pool`` is what the Validator
        binds once for the whole call.

        Refuses with ``InvalidArguments`` whose ``detail`` is the list's own
        node: each failing row's tree under its ``int`` index, and a message
        about the list as a whole under ``non_field_errors``. Dispatch puts
        the shape check's refusals beside it and raises the whole under
        ``many_argument``, so every failing row is reported at once.

        By default, ``validated()`` on each row in order, every refusal
        collected before any is raised, and each row's ``data`` and values in
        a list. A value a row binds is refused with ``ImproperlyConfigured``:
        the service runs once for every row, so a value bound for one has
        nowhere to go. An override that binds for the call binds once.
        """
        errors: dict[Any, Any] = {}
        values: list[dict[str, Any]] = []
        data: list[Any] = []
        for index, row in rows.items():
            try:
                validated = self.validated(row, context)
            except InvalidArguments as refused:
                errors[index] = refused.detail
                continue
            # Refused rather than dropped, as a bound value with no name of its
            # own is: test_by_default_a_value_one_row_binds_is_refused.
            if validated.pool:
                raise ImproperlyConfigured(
                    f"The Validator bound the key(s) {sorted(validated.pool)} for row {index} of "
                    "a many call. A many spec's service is called once for every row, so a "
                    "value bound for one row has nowhere to go; bind nothing per row, or "
                    "override validated_many() to bind once for the call."
                )
            values.append(validated.values)
            data.append(validated.data)
        if errors:
            raise InvalidArguments(errors)
        return Validated(values={many_argument: values}, data=data)
