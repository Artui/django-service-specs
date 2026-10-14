from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar, get_origin, get_type_hints

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


def test_supports_partial_is_an_ordinary_attribute_an_instance_may_set() -> None:
    """Declared as a plain ``bool``, never a ``ClassVar``: an adapter whose
    answer depends on what it was built over sets it in ``__init__``, which a
    type checker refuses for a ``ClassVar``."""
    assert get_origin(get_type_hints(Validator)["supports_partial"]) is not ClassVar
    assert Validator.supports_partial is True


def test_an_instance_s_answer_outranks_its_class_s() -> None:
    validator = _Counting()
    validator.supports_partial = False

    assert validator.supports_partial is False
    assert _Counting().supports_partial is True
