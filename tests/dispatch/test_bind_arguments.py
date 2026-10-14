from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import pytest
from typing_extensions import TypedDict

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
from tests.specs.utils import Foreign

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


def test_passthrough_is_refused_rather_than_run_as_ignore() -> None:
    with pytest.raises(ValueError, match=r"UnknownArguments\.PASSTHROUGH is refused"):
        bind_arguments(
            retrieve(),
            {"pk": 1, "tenant": "acme"},
            principal=PRINCIPAL,
            unknown_arguments=UnknownArguments.PASSTHROUGH,
        )


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


class _Both(Validator):
    """Declares two required strings and returns only those it was handed; records the context."""

    def __init__(self) -> None:
        self.contexts: list[ValidationContext] = []

    def parameters(self) -> Parameters:
        return Parameters.of(
            Parameter("title", "string", required=True), Parameter("body", "string", required=True)
        )

    def validate(self, arguments: Mapping[str, Any], context: ValidationContext) -> dict[str, Any]:
        self.contexts.append(context)
        return dict(arguments)


def test_a_partial_spec_binds_a_call_leaving_out_a_required_argument() -> None:
    validator = _Both()
    spec = ServiceSpec(service=lambda: None, validator=validator, partial=True)
    assert bind_arguments(spec, {"title": "T"}, principal=None) == {"title": "T"}
    assert validator.contexts[0].partial is True


def test_the_same_call_on_a_spec_that_is_not_partial_is_refused() -> None:
    spec = ServiceSpec(service=lambda: None, validator=_Both())
    with pytest.raises(InvalidArguments) as caught:
        bind_arguments(spec, {"title": "T"}, principal=None)
    assert caught.value.detail == {"body": ["This field is required."]}


def test_a_partial_spec_still_requires_its_target_s_pk() -> None:
    # ``partial`` relaxes the Validator's fields alone: a partial update still
    # says which row it updates.
    spec = ServiceSpec(
        service=service, validator=Recording(), instance_selector_spec=retrieve(), partial=True
    )
    with pytest.raises(InvalidArguments) as caught:
        bind_arguments(spec, {"title": "Kept"}, principal=PRINCIPAL)
    assert caught.value.detail == {"pk": ["This field is required."]}


class _ServerTitle(TypedDict):
    title: str


def _server_title() -> _ServerTitle:
    return {"title": "server's"}


class _Merged(Validator):
    """Declares a required title, and refuses its absence in words no shape check uses."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def parameters(self) -> Parameters:
        return Parameters.of(Parameter("title", "string", required=True))

    def validate(self, arguments: Mapping[str, Any], context: ValidationContext) -> dict[str, Any]:
        self.calls.append(dict(arguments))
        if "title" not in arguments:
            raise InvalidArguments({"title": ["The merged input has no title."]})
        return dict(arguments)


def test_a_field_input_data_fills_is_left_to_the_validator_which_runs_no_provider() -> None:
    # The shape check relaxes the field as dispatch's does, and this function
    # calls no provider, so the Validator is handed the caller's arguments
    # alone and is the one that refuses.
    validator = _Merged()
    spec = ServiceSpec(service=service, validator=validator, input_data=_server_title)
    with pytest.raises(InvalidArguments) as caught:
        bind_arguments(spec, {}, principal=PRINCIPAL)
    assert caught.value.detail == {"title": ["The merged input has no title."]}
    assert validator.calls == [{}]


# --- a read a kwargs provider fills -------------------------------------------------


class _ServerPk(TypedDict):
    pk: int


def _server_pk() -> _ServerPk:
    return {"pk": 1}


def test_a_selector_spec_s_read_its_kwargs_provider_fills_is_not_demanded() -> None:
    # The selector is called with the provider's value, which this function
    # does not call, so the checked arguments carry only what was sent.
    spec = SelectorSpec(kind=SelectorKind.RETRIEVE, selector=selector, reads=PK, kwargs=_server_pk)
    assert bind_arguments(spec, {}, principal=PRINCIPAL) == {}


def test_a_target_read_the_lookup_s_kwargs_provider_fills_is_not_demanded() -> None:
    target = SelectorSpec(
        kind=SelectorKind.RETRIEVE, selector=selector, reads=PK, kwargs=_server_pk
    )
    spec = ServiceSpec(service=service, instance_selector_spec=target)
    assert bind_arguments(spec, {}, principal=PRINCIPAL, target=ROW) == {}


def test_a_read_the_spec_s_kwargs_provider_fills_is_not_demanded() -> None:
    spec = ServiceSpec(service=service, reads=PK, kwargs=_server_pk, validator=Recording())
    assert bind_arguments(spec, {"title": "Dune"}, principal=PRINCIPAL) == {
        "title": "DUNE",
        "validated": True,
    }


def test_a_read_an_untyped_kwargs_provider_returns_stays_required() -> None:
    spec = ServiceSpec(service=service, reads=PK, kwargs=lambda: {"pk": 1})
    with pytest.raises(InvalidArguments) as caught:
        bind_arguments(spec, {}, principal=PRINCIPAL)
    assert caught.value.detail == {"pk": ["This field is required."]}


# --- the caller's value for a key a typed provider fills ---------------------------


def test_a_selector_spec_s_filled_read_the_caller_sends_is_checked_and_dropped() -> None:
    # What the selector is called with: the provider's value, never the caller's.
    spec = SelectorSpec(kind=SelectorKind.RETRIEVE, selector=selector, reads=PK, kwargs=_server_pk)
    with pytest.raises(InvalidArguments):
        bind_arguments(spec, {"pk": "x"}, principal=PRINCIPAL)
    assert bind_arguments(spec, {"pk": 2}, principal=PRINCIPAL) == {}


def test_a_filled_field_the_caller_sends_never_reaches_the_validator() -> None:
    validator = _Merged()
    spec = ServiceSpec(service=service, validator=validator, input_data=_server_title)
    with pytest.raises(InvalidArguments) as caught:
        bind_arguments(spec, {"title": "caller's"}, principal=PRINCIPAL)
    assert caught.value.detail == {"title": ["The merged input has no title."]}
    assert validator.calls == [{}]


def test_a_selector_source_binds_as_the_spec_it_compiles_to() -> None:
    with pytest.raises(InvalidArguments) as caught:
        bind_arguments(Foreign(retrieve()), {"pk": 1, "tenant": "acme"}, principal=PRINCIPAL)
    assert caught.value.detail == {"tenant": ["Unknown argument."]}


def test_a_service_source_reaches_the_validator_of_the_spec_it_compiles_to() -> None:
    validator = Recording()
    source = Foreign(ServiceSpec(service=service, validator=validator))

    assert bind_arguments(source, {"title": "Lathe"}, principal=PRINCIPAL) == {
        "title": "LATHE",
        "validated": True,
    }
