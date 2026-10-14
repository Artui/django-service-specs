from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django_service_specs.parameters.parameters import Parameter, Parameters
from django_service_specs.validation.validation_context import ValidationContext
from django_service_specs.validation.validator import Validator


class _Counting(Validator):
    """A Validator that states only the two abstract methods, and counts its calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, Any], ValidationContext]] = []

    def parameters(self) -> Parameters:
        return Parameters.of(Parameter("title", "string", required=True))

    def validate(self, arguments: Mapping[str, Any], context: ValidationContext) -> dict[str, Any]:
        self.calls.append((dict(arguments), context))
        return {"title": arguments["title"].strip()}


def test_by_default_the_validated_mapping_is_the_call_s_data_and_nothing_is_bound() -> None:
    validator = _Counting()
    context = ValidationContext(principal="ada", partial=True)

    validated = validator.validated({"title": " Dune "}, context)

    assert validated.values == {"title": "Dune"}
    # The same object, so a service taking ``data`` and one taking ``title``
    # read one validation rather than two.
    assert validated.data is validated.values
    assert dict(validated.pool) == {}
    # ``validate()`` runs once, handed the arguments and the context as they came.
    assert validator.calls == [({"title": " Dune "}, context)]
