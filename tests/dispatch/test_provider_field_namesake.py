from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import pytest
from asgiref.sync import async_to_sync
from django.db.models import QuerySet
from typing_extensions import TypedDict

from django_service_specs.dispatch.adispatch import adispatch
from django_service_specs.dispatch.check_seeds import check_seeds
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.dispatch.provider_reached import provider_reached
from django_service_specs.parameters.parameters import Parameter, Parameters
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS
from django_service_specs.schema.spec_caller_input_schema import spec_caller_input_schema
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.server_owned_keys import server_owned_keys
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.selector_kind import SelectorKind
from django_service_specs.validation.validation_context import ValidationContext
from django_service_specs.validation.validator import Validator
from tests.dispatch.utils import OPEN, PK, Record, make_user
from tests.dispatch_app.models import Note

pytestmark = pytest.mark.django_db

ENTRIES = pytest.mark.parametrize(
    "entry", [dispatch, async_to_sync(adispatch)], ids=["sync", "async"]
)
BODY = 5
PROVIDED = 999
FILLED = 1


class _Team(TypedDict):
    team_id: int


def _team() -> _Team:
    return {"team_id": PROVIDED}


def _filled_team() -> _Team:
    return {"team_id": FILLED}


class Spread(Validator):
    """A serializer's shape in kernel terms: the body validated, spread as values and as data."""

    def __init__(self, *, required: bool = True) -> None:
        self._parameters = Parameters.of(
            Parameter("team_id", "integer", required=required),
            Parameter("title", "string", required=True),
        )
        self.calls: list[dict[str, Any]] = []

    def parameters(self) -> Parameters:
        return self._parameters

    def validate(self, arguments: Mapping[str, Any], context: ValidationContext) -> dict[str, Any]:
        self.calls.append(dict(arguments))
        return dict(arguments)


class TeamSelector:
    """A target selector taking ``team_id`` beside its reads, recording what it is handed."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **pool: Any) -> QuerySet[Note]:
        self.calls.append(pool)
        return Note.objects.filter(pk=pool["pk"]) if "pk" in pool else Note.objects.all()


def _a(**declaration: Any) -> ServiceSpec:
    return ServiceSpec(
        service=Record(), permissions=OPEN, validator=Spread(), kwargs=_team, **declaration
    )


def _a2() -> ServiceSpec:
    return ServiceSpec(
        service=Record(), permissions=OPEN, validator=Spread(required=False), kwargs=_team
    )


def _b() -> ServiceSpec:
    return _a(input_data=_filled_team)


def _d(*, required: bool = True) -> ServiceSpec:
    target = SelectorSpec(
        kind=SelectorKind.RETRIEVE, selector=TeamSelector(), reads=PK, kwargs=_team
    )
    return ServiceSpec(
        service=Record(),
        permissions=OPEN,
        validator=Spread(required=required),
        instance_selector_spec=target,
    )


def _e() -> ServiceSpec:
    target = SelectorSpec(kind=SelectorKind.LIST, selector=TeamSelector(), kwargs=_team)
    return ServiceSpec(
        service=Record(), permissions=OPEN, validator=Spread(), collection_selector_spec=target
    )


def _on_a_read() -> ServiceSpec:
    target = SelectorSpec(
        kind=SelectorKind.RETRIEVE, selector=TeamSelector(), reads=PK, kwargs=_team
    )
    return ServiceSpec(
        service=Record(),
        permissions=OPEN,
        reads=Parameters.of(Parameter("team_id", "integer", required=True)),
        instance_selector_spec=target,
    )


SHAPES: dict[str, Callable[[], ServiceSpec]] = {
    "A": _a,
    "A2": _a2,
    "B": _b,
    "D": _d,
    "D2": lambda: _d(required=False),
    "E": _e,
}


@pytest.mark.parametrize("shape", list(SHAPES.values()), ids=list(SHAPES))
def test_check_seeds_accepts_a_provider_key_named_like_a_validator_field(
    shape: Callable[[], ServiceSpec],
) -> None:
    spec = shape()
    check_seeds(spec, pool_seeds=DEFAULT_POOL_SEEDS)
    assert "team_id" in spec.parameters().names()


def test_check_seeds_accepts_a_target_provider_key_a_read_declares() -> None:
    spec = _on_a_read()
    check_seeds(spec, pool_seeds=DEFAULT_POOL_SEEDS)
    assert spec.parameters().names() == {"pk", "team_id"}


@pytest.mark.parametrize(
    "shape",
    [_a, _a2, lambda: _d(), lambda: _d(required=False), _e, _on_a_read],
    ids=["A", "A2", "D", "D2", "E", "on-a-read"],
)
def test_a_required_parameter_is_never_server_owned(shape: Callable[[], ServiceSpec]) -> None:
    spec = shape()
    required = {param.name for param in spec.parameters() if param.required}
    assert "team_id" not in server_owned_keys(spec)
    assert not required & server_owned_keys(spec)


@pytest.mark.parametrize("shape", [_a, lambda: _d()], ids=["A", "D"])
def test_the_caller_schema_still_asks_for_the_field(shape: Callable[[], ServiceSpec]) -> None:
    spec = shape()
    schema = spec_caller_input_schema(spec)
    assert "team_id" in schema["properties"]
    assert "team_id" in schema["required"]
    assert "team_id" not in provider_reached(spec)


def test_input_data_still_owns_the_field_it_fills() -> None:
    # B: ``kwargs``' key is left out, ``input_data``'s is the server's.
    assert "team_id" in server_owned_keys(_b())


def test_a_many_row_field_is_no_top_level_name_to_leave_out() -> None:
    spec = ServiceSpec(
        service=Record(),
        permissions=OPEN,
        many=True,
        reads=Parameters.of(Parameter("team_id", "integer", required=True)),
        validator=Spread(),
        kwargs=_team,
    )
    assert "team_id" in server_owned_keys(spec)


@ENTRIES
@pytest.mark.parametrize(
    ("shape", "data_value"),
    [(_a, BODY), (_a2, BODY), (_b, FILLED)],
    ids=["A", "A2", "B"],
)
def test_the_keyword_is_the_provider_s_and_data_the_caller_s(
    entry: Any, shape: Callable[[], ServiceSpec], data_value: int
) -> None:
    spec = shape()
    entry(spec, principal=make_user("ada"), arguments={"team_id": BODY, "title": "t"})
    assert isinstance(spec.service, Record)
    [call] = spec.service.calls
    assert call["team_id"] == PROVIDED
    assert call["data"] == {"team_id": data_value, "title": "t"}


@ENTRIES
def test_a_target_provider_feeds_its_selector_and_the_validator_takes_the_caller_s(
    entry: Any,
) -> None:
    ada = make_user("ada")
    note = Note.objects.create(owner=ada, title="n")
    spec = _d()
    target = spec.instance_selector_spec
    assert target is not None and isinstance(target.selector, TeamSelector)
    assert isinstance(spec.validator, Spread) and isinstance(spec.service, Record)
    entry(spec, principal=ada, arguments={"pk": note.pk, "team_id": BODY, "title": "t"})
    [selected] = target.selector.calls
    assert (selected["pk"], selected["team_id"]) == (note.pk, PROVIDED)
    assert spec.validator.calls == [{"team_id": BODY, "title": "t"}]
    [call] = spec.service.calls
    assert (call["team_id"], call["data"]["team_id"], call["instance"]) == (BODY, BODY, note)


@ENTRIES
def test_a_target_provider_named_like_a_read_leaves_the_read_the_caller_s(entry: Any) -> None:
    ada = make_user("ada")
    note = Note.objects.create(owner=ada, title="n")
    spec = _on_a_read()
    target = spec.instance_selector_spec
    assert target is not None and isinstance(target.selector, TeamSelector)
    assert isinstance(spec.service, Record)
    entry(spec, principal=ada, arguments={"pk": note.pk, "team_id": BODY})
    [selected] = target.selector.calls
    assert selected["team_id"] == PROVIDED
    [call] = spec.service.calls
    assert call["team_id"] == BODY
