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
    """The kernel's validation contract."""

    supports_partial: bool = True

    @property
    def unsendable(self) -> frozenset[str]:
        """The required fields ``parameters()`` leaves out, which no caller can send."""
        return frozenset()

    @abc.abstractmethod
    def parameters(self) -> Parameters:
        """What this Validator takes, as a declaration."""

    @abc.abstractmethod
    def validate(self, arguments: Mapping[str, Any], context: ValidationContext) -> dict[str, Any]:
        """Validated values, or ``InvalidArguments``. May query; never ``async def``."""

    def validated(self, arguments: Mapping[str, Any], context: ValidationContext) -> Validated:
        """``validate()``'s values, as the call's ``data`` too, with nothing else bound."""
        values = self.validate(arguments, context)
        return Validated(values=values, data=values)

    def validated_many(
        self,
        rows: Mapping[int, Mapping[str, Any]],
        context: ValidationContext,
        *,
        many_argument: str,
    ) -> Validated:
        """A ``many`` call's rows, validated as one call: what dispatch asks of a ``many`` spec."""
        errors: dict[Any, Any] = {}
        values: list[dict[str, Any]] = []
        data: list[Any] = []
        for index, row in rows.items():
            try:
                validated = self.validated(row, context)
            except InvalidArguments as refused:
                errors[index] = refused.detail
                continue
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
