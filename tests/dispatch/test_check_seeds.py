"""``check_seeds``: a spec no call on a mount can run, refused before any call.

Each refusal is tested twice: what ``dispatch`` does with the spec today, so
the claim that every call fails is held, and the reader's refusal, by which
message came back.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, TypedDict

import pytest
from django.core.exceptions import ImproperlyConfigured
from pydantic import BaseModel, Field

from django_service_specs import check_seeds as exported
from django_service_specs.adapters.dataclass.dataclass_validator import DataclassValidator
from django_service_specs.adapters.pydantic.pydantic_validator import PydanticValidator
from django_service_specs.dispatch.check_call import check_call
from django_service_specs.dispatch.check_seeds import check_seeds
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.parameters import Parameter, Parameters
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.selector_kind import SelectorKind
from django_service_specs.types.unset import UNSET, UnsetType
from django_service_specs.validation.validation_context import ValidationContext
from django_service_specs.validation.validator import Validator
from tests.dispatch.utils import OPEN, PK, Titled, make_user
from tests.specs.utils import Foreign

pytestmark = pytest.mark.django_db

_SAMPLES = {"integer": 1, "string": "t"}
_SEEDED = DEFAULT_POOL_SEEDS.extend(tenant=lambda: "acme")
_NOTHING_FILLS = "which nothing fills"
_OPTIONAL = "declared as optional reads"
_POSITIONAL = "positional-only"
_DROPPED = "takes neither by name"


def _service(service: Callable[..., Any], **declared: Any) -> ServiceSpec:
    return ServiceSpec(service=service, atomic=False, permissions=OPEN, **declared)


def _retrieve(selector: Callable[..., Any], **declared: Any) -> SelectorSpec:
    return SelectorSpec(kind=SelectorKind.RETRIEVE, selector=selector, permissions=OPEN, **declared)


def _refusal(spec: Any, **keywords: Any) -> str:
    with pytest.raises(ImproperlyConfigured) as refused:
        check_seeds(spec, **keywords)
    return str(refused.value)


@dataclass
class _Titled:
    title: str
    note: str = ""


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


def test_it_is_exported_from_the_root() -> None:
    assert exported is check_seeds


class TestAParameterASeedOccupies:
    """What ``dispatch`` refuses before it reads the arguments, refused in its own words."""

    def test_a_read_a_registered_seed_occupies_is_refused_as_dispatch_refuses_it(self) -> None:
        spec = _service(
            lambda *, tenant: tenant, reads=Parameters.of(Parameter("tenant", "string"))
        )
        with pytest.raises(ImproperlyConfigured) as dispatched:
            check_call(spec, principal=make_user("ada"), arguments={}, pool_seeds=_SEEDED)
        assert _refusal(spec, pool_seeds=_SEEDED) == str(dispatched.value)
        assert "['tenant'], which a registered pool seed occupies" in str(dispatched.value)

    def test_without_the_seed_the_read_is_the_caller_s(self) -> None:
        read = Parameters.of(Parameter("tenant", "string", required=True))
        check_seeds(_service(lambda *, tenant: tenant, reads=read))

    def test_a_many_list_named_for_the_call_s_seat_carries_the_hint(self) -> None:
        spec = _service(
            lambda **_: None, many=True, many_argument="view", validator=DataclassValidator(_Titled)
        )
        assert "['view']" in _refusal(spec)
        assert "the call's own" in _refusal(spec)


_UNFILLED = [
    pytest.param(lambda: _service(lambda *, other: other), "other", id="service"),
    pytest.param(lambda: _retrieve(lambda *, pk: pk), "pk", id="selector"),
    pytest.param(
        lambda: _service(lambda *, instance: instance), "instance", id="instance-without-a-lookup"
    ),
    pytest.param(
        lambda: _service(lambda *, collection: collection),
        "collection",
        id="collection-without-a-lookup",
    ),
    pytest.param(lambda: _retrieve(lambda *, data: data), "data", id="selector-requiring-data"),
    pytest.param(
        lambda: _retrieve(lambda *, instance: instance),
        "instance",
        id="selector-requiring-instance",
    ),
    pytest.param(
        lambda: _service(lambda *, pk: pk, instance_selector_spec=_retrieve(_found, reads=PK)),
        "pk",
        id="the-service-is-handed-no-target-read",
    ),
    pytest.param(
        lambda: _service(
            lambda **_: None, instance_selector_spec=_retrieve(lambda *, other: other)
        ),
        "other",
        id="a-target-selector",
    ),
    pytest.param(
        lambda: _service(
            lambda **_: None,
            collection_selector_spec=SelectorSpec(
                kind=SelectorKind.LIST, selector=lambda *, other: [], permissions=OPEN
            ),
        ),
        "other",
        id="a-collection-selector",
    ),
    pytest.param(
        lambda: _service(
            lambda *, title: title, shapes=Parameters.of(Parameter("title", "string"))
        ),
        "title",
        id="a-shape-reaches-no-callable-by-name",
    ),
]


class TestARequiredKeywordNothingFills:
    @pytest.mark.parametrize(("build", "name"), _UNFILLED)
    def test_dispatch_fails_every_call_with_it(self, build: Callable[[], Any], name: str) -> None:
        spec = build()
        # Every declared argument sent, so only the keyword can fail the call.
        arguments = {param.name: _SAMPLES[param.type] for param in spec.parameters()}
        with pytest.raises(TypeError, match=name):
            dispatch(spec, principal=make_user("ada"), arguments=arguments)

    @pytest.mark.parametrize(("build", "name"), _UNFILLED)
    def test_it_is_refused(self, build: Callable[[], Any], name: str) -> None:
        refused = _refusal(build())
        assert f"requires the keyword(s) ['{name}'], {_NOTHING_FILLS}" in refused
        assert _OPTIONAL not in refused

    def test_the_seat_is_named(self) -> None:
        refused = _refusal(
            _service(lambda **_: None, instance_selector_spec=_retrieve(lambda *, other: other))
        )
        assert refused.startswith("ServiceSpec.instance_selector_spec.selector requires")

    @pytest.mark.parametrize(
        "build",
        [
            pytest.param(lambda: _retrieve(lambda *, pk: pk, reads=PK), id="a-read"),
            pytest.param(lambda: _service(lambda *, tenant: tenant), id="a-registered-seed"),
            pytest.param(
                lambda: _retrieve(lambda *, limit: limit, kwargs=_fills_limit), id="typed"
            ),
            pytest.param(
                lambda: _retrieve(lambda *, limit: limit, kwargs=_may_fill_limit), id="declinable"
            ),
            pytest.param(lambda: _retrieve(lambda *, other: other, kwargs=_untyped), id="untyped"),
            pytest.param(lambda: _retrieve(lambda *, pk=5: pk), id="a-default"),
            pytest.param(lambda: _service(lambda *tags, **rest: None), id="a-catch-all"),
            pytest.param(lambda: _service(lambda *, data: data), id="data-for-a-service"),
            pytest.param(
                lambda: _service(
                    lambda *, instance: instance, instance_selector_spec=_retrieve(lambda **_: 1)
                ),
                id="instance-with-a-lookup",
            ),
            pytest.param(
                lambda: _retrieve(
                    lambda *, user, progress, call_context, shapes, request, view: None
                ),
                id="every-pool-s-own",
            ),
            pytest.param(
                lambda: _service(lambda *, title: title, validator=Titled()), id="a-validator-field"
            ),
        ],
    )
    def test_a_keyword_something_fills_is_not(self, build: Callable[[], Any]) -> None:
        check_seeds(build(), pool_seeds=_SEEDED)

    def test_a_service_beside_a_validator_is_left_to_dispatch(self) -> None:
        """A Validator may return a value it does not declare, so its service is not judged.

        Dispatched to prove the value arrives: a keyword nothing declares that
        such a Validator fills runs today.
        """

        class _Computing(Validator):
            def parameters(self) -> Parameters:
                return Parameters.of(Parameter("title", "string", required=True))

            def validate(
                self, arguments: Mapping[str, Any], context: ValidationContext
            ) -> dict[str, Any]:
                return {"title": arguments["title"], "slug": arguments["title"].lower()}

        spec = _service(lambda *, title, slug: slug, validator=_Computing())
        check_seeds(spec)
        result = dispatch(spec, principal=make_user("ada"), arguments={"title": "Ada"})
        assert result.value == "ada"


class TestAPositionalOnlyParameter:
    def test_dispatch_fails_every_call_though_a_read_declares_it(self) -> None:
        spec = _retrieve(lambda pk, /: pk, reads=PK)
        with pytest.raises(TypeError):
            dispatch(spec, principal=make_user("ada"), arguments={"pk": 1})

    @pytest.mark.parametrize(
        "spec",
        [
            pytest.param(lambda: _retrieve(lambda pk, /: pk, reads=PK), id="a-read-declares-it"),
            pytest.param(lambda: _retrieve(lambda pk, /: pk, kwargs=_untyped), id="untyped"),
            pytest.param(
                lambda: _service(lambda pk, /, **_: pk, validator=DataclassValidator(_Titled)),
                id="beside-a-validator",
            ),
        ],
    )
    def test_it_is_refused_whatever_could_fill_it_by_name(self, spec: Callable[[], Any]) -> None:
        refused = _refusal(spec())
        assert f"the {_POSITIONAL} parameter(s) ['pk']" in refused
        assert _NOTHING_FILLS not in refused

    def test_one_with_a_default_is_not(self) -> None:
        check_seeds(_retrieve(lambda pk=5, /: {"pk": pk}))


def _read_without_a_default(*, number: str, limit: int) -> dict[str, Any]:
    return {"number": number, "limit": limit}


_NUMBER = Parameter("number", "string", required=True)


class TestAnOptionalReadTheCallableRequires:
    def test_dispatch_refuses_a_call_leaving_it_out(self) -> None:
        spec = _retrieve(
            _read_without_a_default, reads=Parameters.of(_NUMBER, Parameter("limit", "integer"))
        )
        with pytest.raises(InvalidArguments) as refused:
            dispatch(spec, principal=make_user("ada"), arguments={"number": "A"})
        assert set(refused.value.detail) == {"limit"}

    @pytest.mark.parametrize(
        "limit",
        [
            pytest.param(Parameter("limit", "integer"), id="optional"),
            # Not demanded by the shape check, and never applied.
            pytest.param(Parameter("limit", "integer", required=True, default=10), id="a-default"),
        ],
    )
    def test_it_is_refused(self, limit: Parameter) -> None:
        refused = _refusal(_retrieve(_read_without_a_default, reads=Parameters.of(_NUMBER, limit)))
        assert f"SelectorSpec.selector requires the keyword(s) ['limit'], {_OPTIONAL}" in refused
        assert _NOTHING_FILLS not in refused

    def test_on_a_service_with_no_validator_too(self) -> None:
        spec = _service(lambda *, limit: limit, reads=Parameters.of(Parameter("limit", "integer")))
        assert f"ServiceSpec.service requires the keyword(s) ['limit'], {_OPTIONAL}" in _refusal(
            spec
        )

    @pytest.mark.parametrize(
        ("limit", "keywords"),
        [
            pytest.param(Parameter("limit", "integer", required=True), {}, id="demanded"),
            pytest.param(Parameter("limit", "integer"), {"kwargs": _fills_limit}, id="typed"),
            pytest.param(Parameter("limit", "integer"), {"kwargs": _untyped}, id="untyped"),
        ],
    )
    def test_one_something_else_fills_is_not(
        self, limit: Parameter, keywords: dict[str, Any]
    ) -> None:
        check_seeds(
            _retrieve(_read_without_a_default, reads=Parameters.of(_NUMBER, limit), **keywords)
        )

    def test_a_reflected_read_a_seed_fills_is_not(self) -> None:
        spec = _retrieve(
            lambda *, tenant: tenant,
            reads=Parameters.of(Parameter("tenant", "string", reflected=True)),
        )
        check_seeds(spec, pool_seeds=_SEEDED)
        # Without the seed it is the caller's optional read, and refused.
        assert _OPTIONAL in _refusal(spec)


class _Aliased(BaseModel):
    title: str
    note: str = Field(default="", alias="noteText")


class TestAValidatorFieldTheServiceCannotReceive:
    def test_dispatch_drops_it(self) -> None:
        seen: list[Any] = []
        spec = _service(lambda *, title: seen.append(title), validator=DataclassValidator(_Titled))
        dispatch(spec, principal=make_user("ada"), arguments={"title": "a", "note": "lost"})
        assert seen == ["a"]

    def test_it_is_refused(self) -> None:
        refused = _refusal(_service(lambda *, title: title, validator=DataclassValidator(_Titled)))
        assert refused.startswith("ServiceSpec.validator declares the field(s) ['note'], which")
        assert _DROPPED in refused
        assert _NOTHING_FILLS not in refused
        assert "data alone" not in refused

    @pytest.mark.parametrize(
        ("service", "keywords"),
        [
            pytest.param(lambda *, title, user: title, {}, id="every-pool-s-own"),
            pytest.param(lambda *, title, tenant: title, {}, id="a-registered-seed"),
            pytest.param(
                lambda *, title, instance: title,
                {"instance_selector_spec": _retrieve(_found)},
                id="the-target",
            ),
            pytest.param(
                lambda *, title, pk: title,
                {"reads": Parameters.of(Parameter("pk", "integer", required=True))},
                id="a-read",
            ),
            pytest.param(lambda *, title, limit: title, {"kwargs": _fills_limit}, id="filled"),
            pytest.param(
                lambda *, title, limit: title, {"kwargs": _may_fill_limit}, id="declinable"
            ),
        ],
    )
    def test_a_keyword_a_declared_source_explains_leaves_the_fields_judged(
        self, service: Callable[..., Any], keywords: dict[str, Any]
    ) -> None:
        spec = _service(service, validator=DataclassValidator(_Titled), **keywords)
        assert "['note']" in _refusal(spec, pool_seeds=_SEEDED)

    @pytest.mark.parametrize(
        "service",
        [
            pytest.param(lambda *, title, note: note, id="by-name"),
            pytest.param(lambda *, data: data.note, id="through-data"),
            pytest.param(lambda **kwargs: kwargs["note"], id="through-kwargs"),
        ],
    )
    def test_a_field_the_service_receives_is_not(self, service: Callable[..., Any]) -> None:
        spec = _service(service, validator=DataclassValidator(_Titled))
        check_seeds(spec)
        result = dispatch(
            spec, principal=make_user("ada"), arguments={"title": "a", "note": "kept"}
        )
        assert result.value == "kept"

    def test_an_untyped_provider_may_fill_any_keyword_so_no_field_is_judged(self) -> None:
        spec = _service(
            lambda *, title, other: title, validator=DataclassValidator(_Titled), kwargs=_untyped
        )
        check_seeds(spec)
        assert "['note']" in _refusal(
            _service(lambda *, title: title, validator=DataclassValidator(_Titled))
        )

    def test_a_field_validated_under_its_alias_reaches_its_own_name_and_is_not(self) -> None:
        """``parameters()`` names the wire's key, and the value is returned under the field's.

        A service taking a keyword nothing declares may be handed a field
        under it, so no field is refused.
        """
        spec = _service(lambda *, title, note: note, validator=PydanticValidator(_Aliased))
        assert spec.validator is not None
        assert spec.validator.parameters().names() == {"title", "noteText"}
        check_seeds(spec)
        result = dispatch(
            spec, principal=make_user("ada"), arguments={"title": "a", "noteText": "kept"}
        )
        assert result.value == "kept"

    def test_a_field_named_like_a_seed_reaches_the_service_through_data_alone(self) -> None:
        @dataclass
        class _Tenanted:
            tenant: str

        refused = _refusal(
            _service(lambda *, tenant: tenant, validator=DataclassValidator(_Tenanted)),
            pool_seeds=_SEEDED,
        )
        assert "['tenant']" in refused
        assert "through data alone" in refused
        check_seeds(
            _service(lambda *, data, tenant: data, validator=DataclassValidator(_Tenanted)),
            pool_seeds=_SEEDED,
        )

    def test_a_many_spec_s_rows_need_the_list_or_data(self) -> None:
        many = {"many": True, "many_argument": "rows", "validator": DataclassValidator(_Titled)}
        assert "['rows']" in _refusal(_service(lambda: None, **many))
        check_seeds(_service(lambda *, rows: rows, **many))


def test_every_refusal_is_named_at_once() -> None:
    refused = _refusal(
        _service(
            lambda *, title: title,
            validator=DataclassValidator(_Titled),
            instance_selector_spec=_retrieve(lambda *, missing: missing),
        )
    )
    assert "['missing'], which nothing fills" in refused
    assert "['note']" in refused


def test_a_declaration_is_read_as_the_spec_it_compiles_to() -> None:
    assert "['other']" in _refusal(Foreign(_service(lambda *, other: other)))


def test_it_runs_no_query(django_assert_num_queries: Any) -> None:
    with django_assert_num_queries(0):
        check_seeds(_service(lambda *, data: data, validator=DataclassValidator(_Titled)))


def test_its_messages_name_each_offender_in_a_sorted_list() -> None:
    refused = _refusal(_service(lambda *, zed, alpha: None))
    assert re.search(r"\['alpha', 'zed'\]", refused)


def test_no_seed_resolves_and_no_provider_is_called() -> None:
    def _never(**_: Any) -> Any:
        raise AssertionError("ran")

    seeds = DEFAULT_POOL_SEEDS.extend(tenant=_never)
    check_seeds(_retrieve(lambda *, tenant: tenant, kwargs=_never), pool_seeds=seeds)
    check_seeds(
        _service(
            lambda *, data, tenant: data,
            validator=DataclassValidator(_Titled),
            input_data=_never,
            kwargs=_never,
        ),
        pool_seeds=seeds,
    )
