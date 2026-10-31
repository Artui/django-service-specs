"""``check_seeds``: a declaration that cannot hold on a mount as written, refused before any call.

Each refusal is tested twice: what ``dispatch`` does with the spec today, so
the claim about which calls fail is held, and the reader's refusal, by which
message came back.
"""

from __future__ import annotations

import functools
import inspect
import re
import typing
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Optional, TypedDict, TypeVar, Union

import pytest
import typing_extensions
from django.core.exceptions import ImproperlyConfigured

from django_service_specs import check_seeds as exported
from django_service_specs.adapters.dataclass.dataclass_validator import DataclassValidator
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
from tests.pool.utils import passthrough
from tests.specs.utils import Foreign

pytestmark = pytest.mark.django_db

_SAMPLES = {"integer": 1, "string": "t"}
_SEEDED = DEFAULT_POOL_SEEDS.extend(tenant=lambda: "acme")
_NOTHING_FILLS = "which nothing fills"
_OPTIONAL = "declared as optional reads"
_POSITIONAL = "positional-only"


def _service(service: Callable[..., Any], **declared: Any) -> ServiceSpec:
    # A selector spec nested in a ServiceSpec declares no permissions: the
    # service's authorize, so the nested one is the derivation without them.
    for role in ("instance", "collection", "output"):
        nested = declared.get(f"{role}_selector_spec")
        if nested is not None:
            declared[f"{role}_selector_spec"] = nested.derive(permissions=None)
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

    @pytest.mark.parametrize("where", ["reads", "shapes"])
    def test_a_selector_spec_s_own_named_for_the_call_s_seat_is_refused_as_dispatch_refuses_it(
        self, where: str
    ) -> None:
        """Built, since a selector spec is also built where its parameters are no call's, and refused here."""
        spec = SelectorSpec(
            kind=SelectorKind.LIST,
            selector=lambda **_: [],
            permissions=OPEN,
            **{where: Parameters.of(Parameter("view", "string"))},
        )
        with pytest.raises(ImproperlyConfigured) as dispatched:
            check_call(spec, principal=make_user("ada"), arguments={})
        assert _refusal(spec) == str(dispatched.value)
        assert "'request' and 'view' are the call's own, read off its context." in _refusal(spec)

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

    @pytest.mark.parametrize("role", ["instance", "collection"])
    def test_the_seat_is_named(self, role: str) -> None:
        kind = SelectorKind.RETRIEVE if role == "instance" else SelectorKind.LIST
        target = SelectorSpec(kind=kind, selector=lambda *, other: other, permissions=OPEN)
        refused = _refusal(_service(lambda **_: None, **{f"{role}_selector_spec": target}))
        assert refused.startswith(f"ServiceSpec.{role}_selector_spec.selector requires")

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


_NO_ITEMS = "with no items"
# The words django-spec-rest's registration test matches, without DOTALL, so
# the offenders and ``items`` must sit on one line of the message.
_NAMES_ITEMS = r"\['pks'\].*items"
_PKS = Parameter("pks", "array", required=True)
_T = TypeVar("_T")


def _annotated(annotation: Any, *, default: Any = inspect.Parameter.empty) -> Callable[..., Any]:
    """A selector taking ``pks``, annotated afterwards, as a consumer may build one."""

    def selector(*, pks: Any = default) -> Any:
        return pks

    selector.__annotations__["pks"] = annotation
    return selector


def _postponed(*, pks: Sequence[int]) -> Any:
    """Annotated as a string, under this module's postponed annotations."""
    return pks


def _hidden_element(*, pks: list[Hidden]) -> Any:  # noqa: F821
    return pks


def _beside_a_hidden_hint(*, pks: list[int], other: Hidden = None) -> Any:  # noqa: F821
    return pks


def _positional_or_keyword(pks: Sequence[int]) -> Any:
    return pks


def _with_another(*, pks: Sequence[int], other: int) -> Any:
    return pks


class _ClassSeat:
    def __init__(self, *, pks: Sequence[int]) -> None:
        self.pks = pks


class _CallableSeat:
    def __call__(self, *, pks: Sequence[int]) -> Any:
        return pks


@dataclass
class _CallableWithFields:
    pks: list[int]

    def __call__(self, *, pks: str = "") -> Any:
        return pks


class _FillsPks(TypedDict):
    pks: list[int]


def _fills_pks() -> _FillsPks:
    return {"pks": [1]}


class _MayFillPks(TypedDict):
    pks: list[int] | UnsetType


def _may_fill_pks() -> _MayFillPks:
    return {"pks": UNSET}


class TestAnArrayReadWithNoItems:
    def test_dispatch_hands_the_callable_any_element(self) -> None:
        handed: list[Any] = []

        def service(*, pks: list[int]) -> None:
            handed.append(pks)

        dispatch(
            _service(service, reads=Parameters.of(_PKS)),
            principal=make_user("ada"),
            arguments={"pks": ["1", "3"]},
        )
        assert handed == [["1", "3"]]

    @pytest.mark.parametrize(
        "annotation",
        [
            list[int],
            Sequence[int],
            tuple[int, ...],
            list[int] | None,
            Optional[list[int]],  # noqa: UP045 - the typing form, a distinct object up to 3.13
            Union[None, Sequence[str]],  # noqa: UP007
            list[int | None],
        ],
        ids=[
            "list",
            "Sequence",
            "tuple",
            "list-or-none",
            "Optional",
            "Union",
            "nullable-element",
        ],
    )
    def test_it_is_refused(self, annotation: Any) -> None:
        refused = _refusal(_retrieve(_annotated(annotation), reads=Parameters.of(_PKS)))
        assert re.search(_NAMES_ITEMS, refused)
        assert f"SelectorSpec.selector reads the array(s) ['pks'] {_NO_ITEMS}" in refused
        assert _NOTHING_FILLS not in refused
        assert _OPTIONAL not in refused

    def test_a_postponed_annotation_is_resolved(self) -> None:
        assert _NO_ITEMS in _refusal(_retrieve(_postponed, reads=Parameters.of(_PKS)))

    def test_a_hint_that_does_not_resolve_leaves_only_its_own_keyword_alone(self) -> None:
        check_seeds(_retrieve(_hidden_element, reads=Parameters.of(_PKS)))
        # ``other`` does not resolve either, and ``pks`` is read on its own.
        assert _NO_ITEMS in _refusal(_retrieve(_beside_a_hidden_hint, reads=Parameters.of(_PKS)))

    @pytest.mark.parametrize(
        "annotation",
        [
            list[Any],
            list[object],
            list[typing_extensions.Any],
            list,
            Sequence[Any] | None,
            tuple[int, int],
            tuple[int],
            typing.Sequence,
            list[int] | tuple[int, ...],
            int,
            dict[str, int],
            list[_T],
        ],
        ids=[
            "list-of-any",
            "list-of-object",
            "list-of-typing-extensions-any",
            "bare-list",
            "Sequence-of-any-or-none",
            "fixed-tuple",
            "one-tuple",
            "bare-typing-Sequence",
            "two-sequences",
            "not-a-sequence",
            "mapping",
            "type-variable",
        ],
    )
    def test_what_it_cannot_misread_is_not(self, annotation: Any) -> None:
        check_seeds(_retrieve(_annotated(annotation), reads=Parameters.of(_PKS)))

    def test_an_unannotated_keyword_is_not(self) -> None:
        check_seeds(_retrieve(lambda *, pks: pks, reads=Parameters.of(_PKS)))

    def test_a_callable_object_s_fields_are_not_its_keywords(self) -> None:
        # Dispatch binds ``__call__``'s ``pks``, a string, whatever the field says.
        selector = _CallableWithFields(pks=[1])
        check_seeds(_retrieve(selector, reads=Parameters.of(_PKS)))

    @pytest.mark.parametrize(
        "selector",
        [
            _positional_or_keyword,
            functools.partial(_with_another, other=1),
            _ClassSeat,
            _CallableSeat(),
            passthrough(_postponed),
        ],
        ids=["positional-or-keyword", "partial", "class", "callable-object", "decorated-elsewhere"],
    )
    def test_it_is_refused_on_every_kind_of_callable(self, selector: Callable[..., Any]) -> None:
        """Each annotated ``Sequence[int]``, a name only this module's globals resolve."""
        refused = _refusal(_retrieve(selector, reads=Parameters.of(_PKS)))
        assert re.search(_NAMES_ITEMS, refused)

    def test_a_declared_items_is_not(self) -> None:
        read = Parameter("pks", "array", required=True, items="integer")
        check_seeds(_retrieve(_annotated(list[int]), reads=Parameters.of(read)))

    def test_a_read_of_another_type_is_not(self) -> None:
        read = Parameter("pks", "string", required=True)
        check_seeds(_retrieve(_annotated(list[int]), reads=Parameters.of(read)))

    @pytest.mark.parametrize(
        "provider",
        [_fills_pks, _may_fill_pks, _untyped],
        ids=["fills", "may-decline", "untyped"],
    )
    def test_a_keyword_a_provider_fills_or_may_fill_is_not(
        self, provider: Callable[..., Any]
    ) -> None:
        check_seeds(_retrieve(_annotated(list[int]), reads=Parameters.of(_PKS), kwargs=provider))

    def test_a_reflected_read_a_seed_fills_is_not(self) -> None:
        def selector(*, tenant: list[int]) -> Any: ...

        spec = _retrieve(
            selector, reads=Parameters.of(Parameter("tenant", "array", reflected=True))
        )
        check_seeds(spec, pool_seeds=_SEEDED)
        # Without the seed it is the caller's read, and refused.
        assert "['tenant'] with no items" in _refusal(spec)

    def test_a_positional_only_parameter_the_read_never_fills_is_not(self) -> None:
        def positional(pks: list[int] = [], /, **_: Any) -> Any:  # noqa: B006
            return pks

        check_seeds(_retrieve(positional, reads=Parameters.of(_PKS)))

    def test_on_a_target_selector_and_a_service_beside_a_validator(self) -> None:
        def service(*, ids: list[int], data: Any) -> None: ...

        spec = _service(
            service,
            reads=Parameters.of(Parameter("ids", "array", required=True)),
            validator=DataclassValidator(_Titled),
            instance_selector_spec=_retrieve(_annotated(Sequence[int]), reads=Parameters.of(_PKS)),
        )
        refused = _refusal(spec)
        assert (
            f"ServiceSpec.instance_selector_spec.selector reads the array(s) ['pks'] {_NO_ITEMS}"
            in refused
        )
        assert f"ServiceSpec.service reads the array(s) ['ids'] {_NO_ITEMS}" in refused

    def test_only_the_seat_the_read_fills_is_read(self) -> None:
        """A service's read never reaches its target selector, whose keyword of that name is its own."""
        spec = _service(
            lambda *, pks: pks,
            reads=Parameters.of(_PKS),
            instance_selector_spec=_retrieve(_annotated(list[int], default=())),
        )
        check_seeds(spec)

    def test_every_offender_is_named_in_one_sorted_list(self) -> None:
        def selector(*, pks: list[int], ids: Sequence[int]) -> Any: ...

        reads = Parameters.of(_PKS, Parameter("ids", "array", required=True))
        assert f"['ids', 'pks'] {_NO_ITEMS}" in _refusal(_retrieve(selector, reads=reads))

    def test_it_is_named_beside_another_refusal(self) -> None:
        def selector(*, pks: list[int], missing: Any) -> Any: ...

        refused = _refusal(_retrieve(selector, reads=Parameters.of(_PKS)))
        assert f"['pks'] {_NO_ITEMS}" in refused
        assert f"['missing'], {_NOTHING_FILLS}" in refused


def test_a_validator_field_the_service_never_receives_is_left_to_unreceived_fields() -> None:
    """Such a spec runs, and may mean to, so it is answered elsewhere and never refused here."""
    check_seeds(_service(lambda *, title: title, validator=DataclassValidator(_Titled)))


def test_every_refusal_is_named_at_once() -> None:
    def positional(only: Any, /, **_: Any) -> None: ...

    refused = _refusal(
        _service(positional, instance_selector_spec=_retrieve(lambda *, missing: missing))
    )
    assert "['missing'], which nothing fills" in refused
    assert "['only'] with no default" in refused


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


def _unreadable_by_a_bad_signature() -> Callable[..., Any]:
    """A function whose ``__signature__`` is no ``Signature``: ``inspect.signature`` raises ``TypeError``."""

    def fn(**_: Any) -> None: ...

    setattr(fn, "__signature__", 3)  # noqa: B010
    return fn


class TestACallableWhoseSignatureCannotBeRead:
    """A builtin type has no signature to read, and dispatch fails every call that reaches it.

    The refusal is ``ImproperlyConfigured``, as every other refusal is, not
    the ``ValueError`` ``inspect.signature`` raises. The guard in
    ``_unfilled`` catches ``(ValueError, TypeError)``: the first is held by
    every ``dict`` case here and the second by
    ``test_a_signature_that_is_not_one_is_refused_alike``, which fails
    without ``TypeError`` in the tuple.
    """

    def test_python_reads_no_signature_for_the_callable_used_here(self) -> None:
        # Guards the tests below against passing vacuously on a Python where
        # ``dict`` gained a signature.
        with pytest.raises(ValueError, match="no signature found"):
            inspect.signature(dict)
        with pytest.raises(TypeError):
            inspect.signature(_unreadable_by_a_bad_signature())

    @pytest.mark.parametrize(
        ("spec", "seat"),
        [
            pytest.param(_retrieve(dict), "SelectorSpec.selector", id="selector-spec"),
            pytest.param(_service(dict), "ServiceSpec.service", id="service-spec"),
            pytest.param(
                _service(lambda: None, instance_selector_spec=_retrieve(dict)),
                "instance_selector_spec",
                id="instance-selector",
            ),
            pytest.param(
                _service(
                    lambda: None,
                    collection_selector_spec=SelectorSpec(
                        kind=SelectorKind.LIST, selector=dict, permissions=OPEN
                    ),
                ),
                "collection_selector_spec",
                id="collection-selector",
            ),
        ],
    )
    def test_it_is_refused_naming_the_seat_and_the_callable(self, spec: Any, seat: str) -> None:
        refused = _refusal(spec)
        assert seat in refused
        assert repr(dict) in refused
        assert "signature cannot be read" in refused
        # The unreadable seat is answered by this refusal alone, not by the
        # checks that need its signature.
        assert _POSITIONAL not in refused
        assert _NOTHING_FILLS not in refused

    @pytest.mark.parametrize(
        ("spec", "error"),
        [
            pytest.param(_retrieve(dict), ValueError, id="selector-spec"),
            pytest.param(_service(dict), ValueError, id="service-spec"),
            pytest.param(
                _service(lambda: None, instance_selector_spec=_retrieve(dict, reads=PK)),
                ValueError,
                id="instance-selector",
            ),
            pytest.param(
                _service(
                    lambda: None,
                    collection_selector_spec=SelectorSpec(
                        kind=SelectorKind.LIST, selector=dict, permissions=OPEN
                    ),
                ),
                ValueError,
                id="collection-selector",
            ),
            pytest.param(_service(_unreadable_by_a_bad_signature()), TypeError, id="bad-signature"),
        ],
    )
    def test_dispatch_fails_every_call_that_reaches_it(
        self, spec: Any, error: type[Exception]
    ) -> None:
        # Holds the claim that the declaration cannot run, for each seat.
        arguments = {"pk": 1} if getattr(spec, "instance_selector_spec", None) else {}
        with pytest.raises(error, match="signature"):
            dispatch(spec, principal=make_user("ada"), arguments=arguments)

    def test_a_signature_that_is_not_one_is_refused_alike(self) -> None:
        fn = _unreadable_by_a_bad_signature()
        refused = _refusal(_service(fn))
        assert "ServiceSpec.service" in refused
        assert repr(fn) in refused

    def test_the_other_seats_are_still_refused_in_the_same_exception(self) -> None:
        def positional(only: Any, /, **_: Any) -> None: ...

        refused = _refusal(
            _service(positional, instance_selector_spec=_retrieve(dict, reads=PK)),
            pool_seeds=_SEEDED,
        )
        assert repr(dict) in refused
        assert "['only'] with no default" in refused

    def test_a_seed_named_read_is_refused_beside_it(self) -> None:
        refused = _refusal(
            _retrieve(dict, reads=Parameters.of(Parameter("tenant", "string"))),
            pool_seeds=_SEEDED,
        )
        assert repr(dict) in refused
        assert "['tenant']" in refused
