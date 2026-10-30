from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar, get_origin, get_type_hints

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.parameters import Parameter, Parameters
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.validation.validated import Validated
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


class _Strict(_Counting):
    """``_Counting``, refusing an empty title."""

    def validate(self, arguments: Mapping[str, Any], context: ValidationContext) -> dict[str, Any]:
        if not arguments["title"].strip():
            raise InvalidArguments({"title": ["Blank."]})
        return super().validate(arguments, context)


def test_by_default_a_list_is_validated_row_by_row_under_its_name() -> None:
    validator = _Counting()
    context = ValidationContext(principal="ada")

    validated = validator.validated_many(
        {0: {"title": " a "}, 2: {"title": "b"}}, context, many_argument="items"
    )

    assert validated.values == {"items": [{"title": "a"}, {"title": "b"}]}
    assert validated.data == [{"title": "a"}, {"title": "b"}]
    assert dict(validated.pool) == {}
    assert validator.calls == [({"title": " a "}, context), ({"title": "b"}, context)]


def test_by_default_every_failing_row_is_refused_at_once_under_its_index() -> None:
    validator = _Strict()

    with pytest.raises(InvalidArguments) as refused:
        validator.validated_many(
            {1: {"title": " "}, 3: {"title": "ok"}, 4: {"title": ""}},
            ValidationContext(principal="ada"),
            many_argument="items",
        )

    assert refused.value.detail == {1: {"title": ["Blank."]}, 4: {"title": ["Blank."]}}


def test_by_default_a_value_one_row_binds_is_refused() -> None:
    """A row's own bound value has nowhere to go on a call that runs once."""

    class Binding(_Counting):
        def validated(self, arguments: Mapping[str, Any], context: ValidationContext) -> Validated:
            return Validated(values=dict(arguments), data=dict(arguments), pool={"form": 1})

    with pytest.raises(ImproperlyConfigured) as refused:
        Binding().validated_many(
            {3: {"title": "a"}}, ValidationContext(principal="ada"), many_argument="items"
        )
    assert str(refused.value).startswith(
        "The Validator bound the key(s) ['form'] for row 3 of a many call."
    )


class _Bare(Validator):
    """A Validator defining only what the ABC requires, as a third party's would."""

    def parameters(self) -> Parameters:
        return Parameters.of()

    def validate(self, arguments: Mapping[str, Any], context: ValidationContext) -> dict[str, Any]:
        return dict(arguments)


def test_a_validator_that_does_not_define_unsendable_answers_the_empty_default() -> None:
    """The ABC carries it, so a reader needs no ``getattr`` fallback."""
    assert _Bare().unsendable == frozenset()
    assert type(_Bare().unsendable) is frozenset


class _RequiresUser(_Bare):
    """Requires a ``user`` field its ``parameters()`` leaves out."""

    @property
    def unsendable(self) -> frozenset[str]:
        return frozenset({"user"})


def test_a_property_override_is_what_a_reader_holding_the_spec_s_seat_sees() -> None:
    spec = ServiceSpec(service=print, validator=_RequiresUser())

    assert spec.validator is not None
    assert spec.validator.unsendable == frozenset({"user"})


class _RequiresUserByClass(_Bare):
    unsendable = frozenset({"user"})


def test_a_class_attribute_override_is_what_a_reader_sees() -> None:
    seat: Validator = _RequiresUserByClass()

    assert seat.unsendable == frozenset({"user"})


def test_an_instance_cannot_assign_unsendable() -> None:
    """A property with no setter, unlike ``supports_partial``: a subclass
    answers for its instances, in a property or a class attribute."""
    validator: Any = _Bare()

    with pytest.raises(AttributeError):
        validator.unsendable = frozenset({"user"})
