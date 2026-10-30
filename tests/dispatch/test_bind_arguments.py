from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest
from django import forms
from django.core.exceptions import ImproperlyConfigured
from typing_extensions import TypedDict

from django_service_specs.adapters.dataclass.dataclass_validator import DataclassValidator
from django_service_specs.adapters.forms.form_validator import FormValidator
from django_service_specs.authorization.principal_unavailable import PrincipalUnavailable
from django_service_specs.authorization.unrestricted import Unrestricted
from django_service_specs.dispatch.bind_arguments import bind_arguments
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.parameters import Parameter, Parameters
from django_service_specs.pool.null_progress import null_progress
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS, PoolSeeds
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.selector_kind import SelectorKind
from django_service_specs.types.unknown_arguments import UnknownArguments
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


def test_a_read_an_untyped_kwargs_provider_may_fill_is_not_demanded() -> None:
    # A provider whose return names no keys may fill any read its values
    # reach, so the shape check relaxes them as dispatch does; dispatch
    # refuses the read at its seat if the provider leaves it out.
    spec = ServiceSpec(service=service, reads=PK, kwargs=lambda: {"pk": 1})
    assert bind_arguments(spec, {}, principal=PRINCIPAL) == {}


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


def test_the_validator_s_call_context_is_the_dict_passed_or_a_fresh_one() -> None:
    validator = Recording()
    spec = ServiceSpec(service=print, validator=validator)
    context: dict[str, Any] = {}
    bind_arguments(spec, {"title": "t"}, principal=PRINCIPAL, call_context=context)
    bind_arguments(spec, {"title": "t"}, principal=PRINCIPAL)
    bind_arguments(spec, {"title": "t"}, principal=PRINCIPAL)
    first, second, third = (handed.call_context for _, handed in validator.calls)
    assert first is context
    assert second == third == {}
    assert second is not third


class _Kept(forms.Form):
    """Takes ``seen``, which ``form_kwargs`` returns, and keeps it for the test."""

    title = forms.CharField()

    def __init__(self, *args: Any, seen: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.seen = seen

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean() or {}
        return {**cleaned, "seen": self.seen}


def test_a_form_s_form_kwargs_is_handed_the_context_s_request_and_view() -> None:
    """The Validator's own pool carries the two values off dispatch as it does on it."""
    request, view = object(), object()
    spec = ServiceSpec(
        service=service,
        validator=FormValidator(
            _Kept, form_kwargs=lambda *, request, view: {"seen": (request, view)}
        ),
    )
    bound = bind_arguments(
        spec,
        {"title": "Lathe"},
        principal=PRINCIPAL,
        call_context={"request": request, "view": view},
    )
    assert bound["seen"] == (request, view)


# --- the call's seeds ----------------------------------------------------------------
#
# Each rule runs with the seeds and without them: without, the function is the
# one it was before it took any, and the without case says what that was.

SEEDED = "tenant-of-the-principal"
"""What ``TENANT_SEEDS`` resolves: a value no caller here ever sends."""
TENANT_SEEDS = DEFAULT_POOL_SEEDS.extend(tenant=lambda *, user: SEEDED)
SEEDS = pytest.mark.parametrize("seeds", [TENANT_SEEDS, None], ids=["seeds", "no-seeds"])
REQUIRED = ["This field is required."]
UNKNOWN = ["Unknown argument."]


def _tenant(**kwargs: Any) -> Parameters:
    return Parameters.of(Parameter("tenant", "string", **kwargs))


def scope_of(*, tenant: str) -> dict[str, Any]:
    """A ``form_kwargs`` scoping its form by the registered seed."""
    return {"seen": tenant}


@pytest.mark.django_db
@SEEDS
def test_a_form_kwargs_naming_a_registered_seed_is_handed_it(seeds: PoolSeeds | None) -> None:
    spec = ServiceSpec(
        service=lambda **kwargs: kwargs["seen"],
        permissions=[Unrestricted()],
        validator=FormValidator(_Kept, form_kwargs=scope_of),
    )
    if seeds is None:
        # Without the seeds there is no ``tenant`` in the pool to hand it.
        with pytest.raises(TypeError, match="tenant"):
            bind_arguments(spec, {"title": "Lathe"}, principal=PRINCIPAL)
        return
    bound = bind_arguments(spec, {"title": "Lathe"}, principal=PRINCIPAL, pool_seeds=seeds)
    assert bound["seen"] == SEEDED
    # The value dispatch hands the form for the same call.
    ran = dispatch(spec, principal=PRINCIPAL, arguments={"title": "Lathe"}, pool_seeds=seeds)
    assert ran.value == SEEDED


def _reflected(seat: str) -> ServiceSpec | SelectorSpec:
    """A spec declaring a required ``tenant`` read off a callable's signature, at ``seat``."""
    reads = _tenant(required=True, reflected=True)
    if seat == "selector-spec":
        return SelectorSpec(kind=SelectorKind.LIST, selector=lambda *, tenant: [], reads=reads)
    return ServiceSpec(service=lambda *, tenant: None, reads=reads)


SEATS = pytest.mark.parametrize("seat", ["selector-spec", "service"])


@SEEDS
@SEATS
def test_a_reflected_read_a_registered_seed_fills_is_not_demanded(
    seeds: PoolSeeds | None, seat: str
) -> None:
    spec = _reflected(seat)
    if seeds is None:
        # As test_bind_arguments_still_demands_a_required_reflected_read holds.
        with pytest.raises(InvalidArguments) as caught:
            bind_arguments(spec, {}, principal=PRINCIPAL)
        assert caught.value.detail == {"tenant": REQUIRED}
        return
    assert bind_arguments(spec, {}, principal=PRINCIPAL, pool_seeds=seeds) == {}


@SEEDS
@SEATS
def test_the_caller_s_value_for_it_is_refused_under_reject_as_dispatch_refuses_it(
    seeds: PoolSeeds | None, seat: str
) -> None:
    spec = _reflected(seat)
    if seeds is None:
        returned = {"tenant": "t"} if seat == "selector-spec" else {}
        assert bind_arguments(spec, {"tenant": "t"}, principal=PRINCIPAL) == returned
        return
    with pytest.raises(InvalidArguments) as caught:
        bind_arguments(spec, {"tenant": "t"}, principal=PRINCIPAL, pool_seeds=seeds)
    assert caught.value.detail == {"tenant": UNKNOWN}


def test_the_caller_s_value_for_it_is_dropped_under_ignore() -> None:
    # A selector spec's, since it returns what it checked; without the seeds
    # the value is kept, as the REJECT test's no-seeds case shows.
    spec = _reflected("selector-spec")
    bound = bind_arguments(
        spec,
        {"tenant": "t"},
        principal=PRINCIPAL,
        pool_seeds=TENANT_SEEDS,
        unknown_arguments=UnknownArguments.IGNORE,
    )
    assert bound == {}


class _Tenanted(Validator):
    """Declares a ``tenant`` field, as a registered seed is named, and returns it."""

    def __init__(self) -> None:
        self.contexts: list[ValidationContext] = []

    def parameters(self) -> Parameters:
        return _tenant(required=True)

    def validate(self, arguments: Mapping[str, Any], context: ValidationContext) -> dict[str, Any]:
        self.contexts.append(context)
        return dict(arguments)


@SEEDS
def test_a_validator_field_named_like_a_registered_seed_is_validated_and_returned(
    seeds: PoolSeeds | None,
) -> None:
    validator = _Tenanted()
    spec = ServiceSpec(service=service, validator=validator)
    bound = bind_arguments(spec, {"tenant": "caller's"}, principal=PRINCIPAL, pool_seeds=seeds)
    assert bound == {"tenant": "caller's"}
    # The seed keeps its own value beside the field, as in dispatch's pool.
    ambient = validator.contexts[0].ambient
    assert ambient.get("tenant") == (None if seeds is None else SEEDED)


@SEEDS
def test_an_unmarked_read_named_like_a_registered_seed_is_refused_only_with_the_seeds(
    seeds: PoolSeeds | None,
) -> None:
    spec = SelectorSpec(kind=SelectorKind.LIST, selector=selector, reads=_tenant())
    if seeds is None:
        assert bind_arguments(spec, {"tenant": "t"}, principal=PRINCIPAL) == {"tenant": "t"}
        return
    with pytest.raises(ImproperlyConfigured, match="registered pool seed occupies"):
        bind_arguments(spec, {"tenant": "t"}, principal=PRINCIPAL, pool_seeds=seeds)


# An explicit registry, even one holding no seed, is dispatch's: the call's
# ``request`` and ``view`` are seeds of every pool it builds. ``None`` is the
# function as it was, which checks a read of either name as declared.
REGISTRIES = pytest.mark.parametrize(
    "seeds", [DEFAULT_POOL_SEEDS, PoolSeeds(), None], ids=["default", "empty", "none"]
)


@REGISTRIES
def test_a_reflected_read_named_request_is_the_call_s_with_any_registry(
    seeds: PoolSeeds | None,
) -> None:
    spec = SelectorSpec(
        kind=SelectorKind.LIST,
        selector=lambda *, request: [],
        reads=Parameters.of(Parameter("request", "string", required=True, reflected=True)),
    )
    if seeds is None:
        with pytest.raises(InvalidArguments) as demanded:
            bind_arguments(spec, {}, principal=PRINCIPAL)
        assert demanded.value.detail == {"request": REQUIRED}
        return
    assert bind_arguments(spec, {}, principal=PRINCIPAL, pool_seeds=seeds) == {}
    with pytest.raises(InvalidArguments) as refused:
        bind_arguments(spec, {"request": "r"}, principal=PRINCIPAL, pool_seeds=seeds)
    assert refused.value.detail == {"request": UNKNOWN}


@REGISTRIES
def test_an_unmarked_read_named_request_is_refused_with_any_registry(
    seeds: PoolSeeds | None,
) -> None:
    spec = SelectorSpec(
        kind=SelectorKind.LIST,
        selector=selector,
        reads=Parameters.of(Parameter("request", "string")),
    )
    if seeds is None:
        assert bind_arguments(spec, {"request": "r"}, principal=PRINCIPAL) == {"request": "r"}
        return
    with pytest.raises(ImproperlyConfigured, match="registered pool seed occupies"):
        bind_arguments(spec, {"request": "r"}, principal=PRINCIPAL, pool_seeds=seeds)


@pytest.mark.django_db
def test_the_validator_s_ambient_is_the_one_dispatch_hands_it() -> None:
    bound, ran = Recording(), Recording()
    bind_arguments(
        ServiceSpec(service=service, validator=bound),
        {"title": "t"},
        principal=PRINCIPAL,
        pool_seeds=TENANT_SEEDS,
    )
    dispatch(
        ServiceSpec(service=service, permissions=[Unrestricted()], validator=ran),
        principal=PRINCIPAL,
        arguments={"title": "t"},
        pool_seeds=TENANT_SEEDS,
    )
    ((_, off), (_, on)) = bound.calls + ran.calls
    assert (
        dict(off.ambient)
        == dict(on.ambient)
        == {
            "user": PRINCIPAL,
            "progress": null_progress,
            "tenant": SEEDED,
        }
    )


@REGISTRIES
def test_the_validator_s_ambient_is_dispatch_s_with_any_registry(
    seeds: PoolSeeds | None,
) -> None:
    validator = Recording()
    spec = ServiceSpec(service=service, validator=validator)
    bind_arguments(spec, {"title": "t"}, principal=PRINCIPAL, pool_seeds=seeds)
    ((_, context),) = validator.calls
    expected = {} if seeds is None else {"user": PRINCIPAL, "progress": null_progress}
    assert dict(context.ambient) == expected


def test_a_seed_resolver_reads_the_dict_the_validator_is_handed() -> None:
    validator = Recording()
    seen: list[Any] = []

    def tenant(*, request: Any) -> str:
        seen.append(request)
        return SEEDED

    request = object()
    context: dict[str, Any] = {"request": request}
    spec = ServiceSpec(service=service, validator=validator)
    seeds = DEFAULT_POOL_SEEDS.extend(tenant=tenant)
    bind_arguments(
        spec, {"title": "t"}, principal=PRINCIPAL, pool_seeds=seeds, call_context=context
    )
    ((_, handed),) = validator.calls
    assert seen == [request]
    assert handed.call_context is context
    assert handed.ambient["tenant"] == SEEDED


DORMANT = SimpleNamespace(is_authenticated=True, is_active=False)


@SEEDS
def test_a_deactivated_principal_resolves_no_seed(seeds: PoolSeeds | None) -> None:
    resolved: list[Any] = []
    validator = Recording()
    spec = ServiceSpec(service=service, validator=validator)
    if seeds is None:
        # Bound as before: the function never authorized, and resolves nothing.
        bind_arguments(spec, {"title": "t"}, principal=DORMANT)
        assert len(validator.calls) == 1
        return
    recording = DEFAULT_POOL_SEEDS.extend(tenant=lambda *, user: resolved.append(user))
    with pytest.raises(PrincipalUnavailable):
        bind_arguments(spec, {"title": "t"}, principal=DORMANT, pool_seeds=recording)
    assert resolved == []
    assert validator.calls == []
