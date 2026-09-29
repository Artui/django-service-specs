from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import pytest

from django_service_specs.adapters.dataclass.dataclass_validator import DataclassValidator
from django_service_specs.dispatch.bind_arguments import bind_arguments
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.parameter import Parameter
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.validation.unknown_arguments import UnknownArguments
from django_service_specs.validation.validation_context import ValidationContext
from django_service_specs.validation.validator import Validator

PRINCIPAL = object()
ROW = object()
PK = Parameters.of(Parameter("pk", "integer", required=True))


class Recording(Validator):
    """Declares a title and a nested author, and records what it was given.

    Its verdict refuses one title by name, with a message no shape check
    produces, so a test can tell which of the two steps answered.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, Any], ValidationContext]] = []

    def parameters(self) -> Parameters:
        return Parameters.of(
            Parameter("title", "string", required=True),
            Parameter(
                "author",
                "object",
                fields=Parameters.of(Parameter("name", "string", required=True)),
            ),
        )

    def validate(self, arguments: Mapping[str, Any], context: ValidationContext) -> dict[str, Any]:
        self.calls.append((dict(arguments), context))
        if arguments["title"] == "Taken":
            raise InvalidArguments({"title": ["A book with this title already exists."]})
        return {"title": arguments["title"].upper(), "validated": True}


def selector(**kwargs: Any) -> None: ...


def service(**kwargs: Any) -> None: ...


def retrieve(reads: Parameters = PK) -> SelectorSpec:
    return SelectorSpec(kind=SelectorKind.RETRIEVE, selector=selector, reads=reads)


# --- a selector spec ----------------------------------------------------------------


def test_a_selector_spec_returns_its_checked_arguments() -> None:
    spec = SelectorSpec(
        kind=SelectorKind.LIST,
        selector=selector,
        reads=Parameters.of(Parameter("q", "string"), Parameter("limit", "integer")),
    )
    assert bind_arguments(spec, {"q": "earth"}, principal=PRINCIPAL) == {"q": "earth"}


def test_a_selector_spec_refuses_what_its_reads_do_not_declare() -> None:
    with pytest.raises(InvalidArguments) as caught:
        bind_arguments(retrieve(), {"pk": 1, "tenant": "acme"}, principal=PRINCIPAL)
    assert caught.value.detail == {"tenant": ["Unknown argument."]}


def test_the_policy_reaches_the_shape_check() -> None:
    bound = bind_arguments(
        retrieve(),
        {"pk": 1, "tenant": "acme"},
        principal=PRINCIPAL,
        unknown_arguments=UnknownArguments.IGNORE,
    )
    assert bound == {"pk": 1}


# --- a service spec -------------------------------------------------------------------


def test_a_service_spec_with_no_validator_checks_its_target_reads_and_returns_nothing() -> None:
    # Every argument it takes is its target selector's, and none reaches the
    # service, so the bind's value is empty even when the check passes.
    spec = ServiceSpec(service=service, instance_selector_spec=retrieve())
    assert bind_arguments(spec, {"pk": 1}, principal=PRINCIPAL, target=ROW) == {}
    with pytest.raises(InvalidArguments) as caught:
        bind_arguments(spec, {}, principal=PRINCIPAL, target=ROW)
    assert caught.value.detail == {"pk": ["This field is required."]}


def test_the_validator_gets_only_its_own_arguments_and_the_context() -> None:
    validator = Recording()
    spec = ServiceSpec(service=service, validator=validator, instance_selector_spec=retrieve())
    bound = bind_arguments(
        spec,
        {"pk": 1, "title": "Lathe", "author": {"name": "Le Guin"}},
        principal=PRINCIPAL,
        target=ROW,
    )
    assert bound == {"title": "LATHE", "validated": True}
    assert validator.calls == [
        (
            {"title": "Lathe", "author": {"name": "Le Guin"}},
            ValidationContext(principal=PRINCIPAL, target=ROW),
        )
    ]


def test_the_target_defaults_to_none_for_a_create() -> None:
    validator = Recording()
    bind_arguments(
        ServiceSpec(service=service, validator=validator), {"title": "Lathe"}, principal=PRINCIPAL
    )
    assert validator.calls[0][1] == ValidationContext(principal=PRINCIPAL, target=None)


def test_the_validator_sees_the_cleaned_copy_under_ignore() -> None:
    validator = Recording()
    spec = ServiceSpec(service=service, validator=validator)
    bind_arguments(
        spec,
        {"title": "Lathe", "author": {"name": "Le Guin", "tenant": "acme"}, "tenant": "acme"},
        principal=PRINCIPAL,
        unknown_arguments=UnknownArguments.IGNORE,
    )
    assert validator.calls[0][0] == {"title": "Lathe", "author": {"name": "Le Guin"}}


def test_the_shape_check_answers_before_the_validator_runs() -> None:
    # "Taken" is the one title the validator refuses, so a malformed author
    # beside it proves which step answered: the shape check's message comes
    # back and the validator is never called.
    validator = Recording()
    spec = ServiceSpec(service=service, validator=validator)
    with pytest.raises(InvalidArguments) as caught:
        bind_arguments(spec, {"title": "Taken", "author": {}}, principal=PRINCIPAL)
    assert caught.value.detail == {"author": {"name": ["This field is required."]}}
    assert validator.calls == []


def test_the_validators_refusal_reaches_the_caller() -> None:
    validator = Recording()
    spec = ServiceSpec(service=service, validator=validator)
    with pytest.raises(InvalidArguments) as caught:
        bind_arguments(spec, {"title": "Taken"}, principal=PRINCIPAL)
    assert caught.value.detail == {"title": ["A book with this title already exists."]}
    assert len(validator.calls) == 1


@dataclass
class _Scores:
    scores: list[int | None]


def test_a_null_element_the_validator_takes_reaches_it() -> None:
    # The shape check answers first, so an element it could not see as nullable
    # was refused before the Validator that accepts it was ever asked.
    spec = ServiceSpec(service=service, validator=DataclassValidator(_Scores))
    bound = bind_arguments(spec, {"scores": [1, None]}, principal=PRINCIPAL)
    assert bound == {"scores": [1, None]}
