"""``unreceived_fields``: the Validator fields a service is never handed, answered rather than refused.

Each answer is tested beside what ``dispatch`` does with the spec, so the
claim that a field's value is validated and then reaches the service by no
route is held, and so is the claim that a field the service does receive is
never answered.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, TypedDict

import pytest
from pydantic import BaseModel, Field

from django_service_specs import unreceived_fields as exported
from django_service_specs.adapters.dataclass.dataclass_validator import DataclassValidator
from django_service_specs.adapters.pydantic.pydantic_validator import PydanticValidator
from django_service_specs.dispatch.check_seeds import check_seeds
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.dispatch.unreceived_fields import unreceived_fields
from django_service_specs.parameters.parameters import Parameter, Parameters
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.selector_kind import SelectorKind
from django_service_specs.types.unset import UNSET, UnsetType
from django_service_specs.validation.validation_context import ValidationContext
from django_service_specs.validation.validator import Validator
from tests.dispatch.utils import OPEN, make_user
from tests.specs.utils import Foreign

pytestmark = pytest.mark.django_db

_SEEDED = DEFAULT_POOL_SEEDS.extend(tenant=lambda: "acme")


def _service(service: Callable[..., Any], **declared: Any) -> ServiceSpec:
    return ServiceSpec(service=service, atomic=False, permissions=OPEN, **declared)


@dataclass
class _Titled:
    title: str
    note: str = ""


@dataclass
class _Tenanted:
    tenant: str


class _Aliased(BaseModel):
    title: str
    note: str = Field(default="", alias="noteText")


class _Fills(TypedDict):
    limit: int


def _fills_limit() -> _Fills:
    return {"limit": 5}


class _MayFill(TypedDict):
    limit: int | UnsetType


def _may_fill_limit() -> _MayFill:
    return {"limit": UNSET}


def _untyped() -> dict[str, Any]:
    return {}


def _found(**_: Any) -> int:
    return 1


class _Confirmed(Validator):
    """Checks that ``password`` and ``confirm`` agree and returns ``password`` alone, on purpose."""

    def parameters(self) -> Parameters:
        return Parameters.of(
            Parameter("password", "string", required=True),
            Parameter("confirm", "string", required=True),
        )

    def validate(self, arguments: Mapping[str, Any], context: ValidationContext) -> dict[str, Any]:
        if arguments["password"] != arguments["confirm"]:
            raise ValueError("The two passwords differ.")
        return {"password": arguments["password"]}


def test_it_is_exported_from_the_root() -> None:
    assert exported is unreceived_fields


def test_dispatch_drops_it() -> None:
    seen: list[Any] = []
    spec = _service(lambda *, title: seen.append(title), validator=DataclassValidator(_Titled))
    dispatch(spec, principal=make_user("ada"), arguments={"title": "a", "note": "lost"})
    assert seen == ["a"]


def test_a_field_the_service_never_takes_is_answered() -> None:
    spec = _service(lambda *, title: title, validator=DataclassValidator(_Titled))
    assert unreceived_fields(spec) == {"note"}


def test_a_field_consumed_on_purpose_is_answered_and_the_spec_runs() -> None:
    """Why this is an answer: the spec runs as meant, and ``check_seeds`` does not refuse it."""
    spec = _service(lambda *, password: len(password), validator=_Confirmed())
    assert unreceived_fields(spec) == {"confirm"}
    check_seeds(spec)
    result = dispatch(
        spec, principal=make_user("ada"), arguments={"password": "pw", "confirm": "pw"}
    )
    assert result.value == 2


@pytest.mark.parametrize(
    ("service", "keywords"),
    [
        pytest.param(lambda *, title, user: title, {}, id="every-pool-s-own"),
        pytest.param(lambda *, title, tenant: title, {}, id="a-registered-seed"),
        pytest.param(
            lambda *, title, instance: title,
            {
                "instance_selector_spec": SelectorSpec(
                    kind=SelectorKind.RETRIEVE, selector=_found, permissions=OPEN
                )
            },
            id="the-target",
        ),
        pytest.param(
            lambda *, title, pk: title,
            {"reads": Parameters.of(Parameter("pk", "integer", required=True))},
            id="a-read",
        ),
        pytest.param(lambda *, title, limit: title, {"kwargs": _fills_limit}, id="filled"),
        pytest.param(lambda *, title, limit: title, {"kwargs": _may_fill_limit}, id="declinable"),
    ],
)
def test_a_keyword_a_declared_source_explains_leaves_the_fields_answered(
    service: Callable[..., Any], keywords: dict[str, Any]
) -> None:
    spec = _service(service, validator=DataclassValidator(_Titled), **keywords)
    assert unreceived_fields(spec, pool_seeds=_SEEDED) == {"note"}


@pytest.mark.parametrize(
    "service",
    [
        pytest.param(lambda *, title, note: note, id="by-name"),
        pytest.param(lambda *, data: data.note, id="through-data"),
        pytest.param(lambda **kwargs: kwargs["note"], id="through-kwargs"),
    ],
)
def test_a_field_the_service_receives_is_not(service: Callable[..., Any]) -> None:
    spec = _service(service, validator=DataclassValidator(_Titled))
    assert unreceived_fields(spec) == frozenset()
    result = dispatch(spec, principal=make_user("ada"), arguments={"title": "a", "note": "kept"})
    assert result.value == "kept"


def test_an_untyped_provider_may_fill_any_keyword_so_no_field_is_answered() -> None:
    spec = _service(
        lambda *, title, other: title, validator=DataclassValidator(_Titled), kwargs=_untyped
    )
    assert unreceived_fields(spec) == frozenset()
    without = _service(lambda *, title: title, validator=DataclassValidator(_Titled))
    assert unreceived_fields(without) == {"note"}


def test_a_field_validated_under_its_alias_reaches_its_own_name_and_is_not() -> None:
    """``parameters()`` names the wire's key, and the value is returned under the field's.

    A service taking a keyword nothing declares may be handed a field under
    it, so no field is answered.
    """
    spec = _service(lambda *, title, note: note, validator=PydanticValidator(_Aliased))
    assert spec.validator is not None
    assert spec.validator.parameters().names() == {"title", "noteText"}
    assert unreceived_fields(spec) == frozenset()
    result = dispatch(
        spec, principal=make_user("ada"), arguments={"title": "a", "noteText": "kept"}
    )
    assert result.value == "kept"


class TestAFieldNamedLikeASeed:
    """The name in the pool is the seed's, so the field reaches the service through ``data`` alone."""

    def test_a_service_taking_it_by_name_only_is_answered(self) -> None:
        seen: list[Any] = []
        spec = _service(
            lambda *, tenant: seen.append(tenant), validator=DataclassValidator(_Tenanted)
        )
        dispatch(spec, principal=make_user("ada"), arguments={"tenant": "sent"}, pool_seeds=_SEEDED)
        assert seen == ["acme"]
        assert unreceived_fields(spec, pool_seeds=_SEEDED) == {"tenant"}

    @pytest.mark.parametrize(
        "service",
        [
            pytest.param(lambda *, data, tenant: data.tenant, id="through-data"),
            pytest.param(lambda **kw: kw["data"].tenant, id="through-kwargs"),
        ],
    )
    def test_a_service_handed_data_is_not(self, service: Callable[..., Any]) -> None:
        spec = _service(service, validator=DataclassValidator(_Tenanted))
        result = dispatch(
            spec, principal=make_user("ada"), arguments={"tenant": "sent"}, pool_seeds=_SEEDED
        )
        assert result.value == "sent"
        assert unreceived_fields(spec, pool_seeds=_SEEDED) == frozenset()


def test_a_many_spec_s_rows_need_the_list_or_data() -> None:
    many = {"many": True, "many_argument": "rows", "validator": DataclassValidator(_Titled)}
    assert unreceived_fields(_service(lambda: None, **many)) == {"rows"}
    assert unreceived_fields(_service(lambda *, rows: rows, **many)) == frozenset()


@pytest.mark.parametrize(
    "spec",
    [
        pytest.param(
            SelectorSpec(kind=SelectorKind.LIST, selector=lambda: [], permissions=OPEN),
            id="a-selector-spec",
        ),
        pytest.param(_service(lambda: None), id="no-validator"),
    ],
)
def test_a_spec_with_no_fields_is_answered_with_none(spec: Any) -> None:
    assert unreceived_fields(spec) == frozenset()


def test_a_declaration_is_read_as_the_spec_it_compiles_to() -> None:
    spec = _service(lambda *, title: title, validator=DataclassValidator(_Titled))
    assert unreceived_fields(Foreign(spec)) == {"note"}


def test_it_runs_no_query_and_resolves_no_seed(django_assert_num_queries: Any) -> None:
    def _never(**_: Any) -> Any:
        raise AssertionError("ran")

    def _never_fills() -> _Fills:
        raise AssertionError("ran")

    spec = _service(
        lambda *, title, tenant, limit: title,
        validator=DataclassValidator(_Titled),
        input_data=_never,
        kwargs=_never_fills,
    )
    with django_assert_num_queries(0):
        assert unreceived_fields(spec, pool_seeds=DEFAULT_POOL_SEEDS.extend(tenant=_never)) == {
            "note"
        }
