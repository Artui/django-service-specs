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
from django.db.models import Q

from django_service_specs import check_seeds as exported
from django_service_specs.adapters.dataclass.dataclass_validator import DataclassValidator
from django_service_specs.dispatch.adispatch import adispatch
from django_service_specs.dispatch.check_call import check_call
from django_service_specs.dispatch.check_seeds import check_seeds
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.parameters import Parameter, Parameters
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.affordance import Affordance
from django_service_specs.types.selector_kind import SelectorKind
from django_service_specs.types.unset import UNSET, UnsetType
from django_service_specs.validation.validation_context import ValidationContext
from django_service_specs.validation.validator import Validator
from tests.dispatch.utils import (
    EVERY_ASK,
    OPEN,
    PK,
    TENANT_SEEDS,
    Titled,
    every_ask_case,
    make_user,
)
from tests.dispatch_app.models import Note
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
    # service's checks authorize, so the nested one is the derivation without them.
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


@dataclass
class _Untitled:
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


async def _found_async(**_: Any) -> int:
    # The route only an ``async def`` selector takes in ``adispatch``.
    return 1


class _Computing(Validator):
    """Returns ``slug``, which it never declares."""

    def parameters(self) -> Parameters:
        return Parameters.of(Parameter("title", "string", required=True))

    def validate(self, arguments: Mapping[str, Any], context: ValidationContext) -> dict[str, Any]:
        return {"title": arguments["title"], "slug": arguments["title"].lower()}


def _untyped_other() -> dict[str, Any]:
    return {"other": 2}


def _needs_tenant(*, tenant: Any) -> None: ...


def _needs_data(*, data: Any) -> None: ...


def _needs_instance(*, instance: Any) -> None: ...


def _needs_collection(*, collection: Any) -> None: ...


def _list(selector: Callable[..., Any], **declared: Any) -> SelectorSpec:
    return SelectorSpec(kind=SelectorKind.LIST, selector=selector, permissions=OPEN, **declared)


def _none(**_: Any) -> list[Any]:
    # A LIST's rows, never ``None``: settle answers no condition on a
    # ``None`` under ``allow_none``, so a condition test returns a list.
    return []


def _notes(**_: Any) -> Any:
    # A QuerySet, since ``extend_queryset`` runs on nothing else.
    return Note.objects.all()


async def _none_async(**_: Any) -> list[Any]:
    return []


async def _notes_async(**_: Any) -> Any:
    # Not evaluated, which the executor does after the await.
    return Note.objects.all()


def _when(condition: Any, code: str = "c") -> list[Affordance]:
    return [Affordance(code=code, reason="Not now.", when=condition)]


def _mapping(condition: Any) -> dict[str, ServiceSpec]:
    """A selector's ``affordances``, mapping one operation to its condition."""
    return {"rename": _service(lambda **_: None, affordances=_when(condition))}


def _taking(*names: str, seen: dict[str, Any], answer: Any = True) -> Callable[..., Any]:
    """A callable requiring each of ``names`` by keyword, recording what it is handed.

    Its signature is all dispatch and ``check_seeds`` read, and the body
    records every keyword, so a test asserts the keyword arrived rather than
    that the call did not fail. ``answer`` is returned, or called with what
    was handed if it is callable.
    """

    def fn(**handed: Any) -> Any:
        seen.update(handed)
        return answer(handed) if callable(answer) else answer

    keyword = inspect.Parameter.KEYWORD_ONLY
    signature = inspect.Signature([inspect.Parameter(name, keyword) for name in names])
    setattr(fn, "__signature__", signature)  # noqa: B010
    return fn


class _Scope(TypedDict):
    tenant_id: str


def _scoped_by(name: str) -> Callable[..., _Scope]:
    """A provider typed to fill ``tenant_id`` that requires ``name``, which nothing fills."""

    def provide(**handed: Any) -> _Scope:
        return {"tenant_id": "acme"}

    keyword = inspect.Parameter.KEYWORD_ONLY
    signature = inspect.Signature([inspect.Parameter(name, keyword)], return_annotation=_Scope)
    setattr(provide, "__signature__", signature)  # noqa: B010
    return provide


def _scope(*, tenant: Any) -> _Scope:
    """A typed provider requiring the seed ``tenant``, which fills its callable's ``tenant_id``."""
    return {"tenant_id": tenant}


def _fills_its_own_limit(*, limit: int) -> _Fills:
    # Typed to fill ``limit``, so the caller's value for it is dropped
    # (``_without``) and never reaches this provider.
    return {"limit": limit}


def _declines_its_limit(seen: dict[str, Any]) -> Callable[..., _MayFill]:
    """A provider that may decline ``limit``, requiring it and recording what it is handed."""

    def provide(*, limit: int) -> _MayFill:
        seen["limit"] = limit
        return {"limit": UNSET}

    return provide


def _provides_from_limit(*, limit: int) -> dict[str, Any]:
    return {}


def _reports(*, progress: Any) -> None:
    # A run reports, or a sync run's ``progress_reporter`` is never resolved.
    progress(0.5)


def _reports_positionally(progress: Any) -> None:
    progress(0.5)


async def _reports_async(*, progress: Any) -> None:
    progress(0.5)


def _reports_row(*, progress: Any, **_: Any) -> int:
    progress(0.5)
    return 1


async def _reports_row_async(*, progress: Any, **_: Any) -> int:
    progress(0.5)
    return 1


def _provider(name: str, seen: dict[str, Any]) -> Callable[..., Any]:
    """A ``kwargs`` or ``input_data`` provider requiring ``name``, answering no key."""
    return _taking(name, seen=seen, answer={})


def _reporter(name: str, seen: dict[str, Any]) -> Callable[..., Any]:
    """A ``progress_reporter`` requiring ``name``, declining to report."""
    return _taking(name, seen=seen, answer=None)


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
    # A provider's pool is its own, not its callable's: each of these passes a
    # check that reads a provider seat as the seat of the callable beside it.
    pytest.param(
        lambda: _retrieve(_found, kwargs=lambda *, tenant: {}),
        "tenant",
        id="an-untyped-provider-is-read-as-any-other",
    ),
    pytest.param(
        lambda: _service(lambda **_: None, kwargs=_needs_data), "data", id="a-provider-is-no-data"
    ),
    pytest.param(
        lambda: _service(_reports, progress_reporter=_needs_data),
        "data",
        id="a-progress-reporter-is-no-data",
    ),
    pytest.param(
        lambda: _service(lambda **_: None, validator=Titled(), input_data=lambda *, title: {}),
        "title",
        id="input-data-is-handed-no-validator-field",
    ),
    pytest.param(
        lambda: _service(_reports, reads=_TITLE, progress_reporter=lambda *, title: None),
        "title",
        id="a-progress-reporter-is-handed-no-read",
    ),
    pytest.param(
        lambda: _retrieve(_found, kwargs=_needs_instance), "instance", id="a-lookup-s-provider"
    ),
    pytest.param(
        lambda: _service(
            lambda **_: None, instance_selector_spec=_retrieve(_found, kwargs=_needs_instance)
        ),
        "instance",
        id="a-target-s-provider-is-handed-no-row",
    ),
    pytest.param(
        lambda: _retrieve(_found, reads=_LIMIT_REQUIRED, kwargs=_fills_its_own_limit),
        "limit",
        id="a-read-its-provider-is-typed-to-fill",
    ),
    pytest.param(
        lambda: _service(
            lambda **_: None,
            reads=_LIMIT_REQUIRED,
            kwargs=_fills_limit,
            validator=Titled(),
            input_data=_provides_from_limit,
        ),
        "limit",
        id="input-data-and-a-read-the-spec-s-provider-is-typed-to-fill",
    ),
]


_CONDITION_TAIL = "Register the seed on the mount, or give it a default."
_OUTPUT_TAIL = "never an argument"
_EXTEND_TAIL = "it is handed queryset beside what its selector is handed"
_DECLARE_TAIL = "Declare it, or give it a default."
_PROVIDER_TAIL = "a provider is handed what every pool carries"
_REPORTER_TAIL = "a progress_reporter is handed only the call's seeds"

# Each provider seat requiring the seed ``tenant``: refused where no mount
# registers it, and passing where one does (TestAKeywordOnlyAMountsSeedFills).
_PROVIDER_SEATS = [
    pytest.param(
        lambda: _service(lambda *, tenant_id: tenant_id, kwargs=_scope),
        "tenant",
        "ServiceSpec.kwargs",
        _PROVIDER_TAIL,
        id="a-service-s-kwargs",
    ),
    pytest.param(
        lambda: _retrieve(lambda *, tenant_id: tenant_id, kwargs=_scope),
        "tenant",
        "SelectorSpec.kwargs",
        _PROVIDER_TAIL,
        id="a-selector-s-kwargs",
    ),
    pytest.param(
        # The Validator leaves the service to dispatch, never its input_data.
        lambda: _service(lambda **_: None, validator=Titled(), input_data=lambda *, tenant: {}),
        "tenant",
        "ServiceSpec.input_data",
        _PROVIDER_TAIL,
        id="input-data",
    ),
    pytest.param(
        lambda: _service(
            lambda **_: None,
            instance_selector_spec=_retrieve(lambda *, tenant_id: 1, kwargs=_scope),
        ),
        "tenant",
        "ServiceSpec.instance_selector_spec.kwargs",
        _PROVIDER_TAIL,
        id="an-instance-target-s-kwargs",
    ),
    pytest.param(
        lambda: _service(
            lambda **_: None,
            collection_selector_spec=_list(lambda *, tenant_id: [], kwargs=_scope),
        ),
        "tenant",
        "ServiceSpec.collection_selector_spec.kwargs",
        _PROVIDER_TAIL,
        id="a-collection-target-s-kwargs",
    ),
    pytest.param(
        lambda: _service(_reports, progress_reporter=_needs_tenant),
        "tenant",
        "ServiceSpec.progress_reporter",
        _REPORTER_TAIL,
        id="a-service-s-progress-reporter",
    ),
    pytest.param(
        lambda: _service(_reports_positionally, progress_reporter=_needs_tenant),
        "tenant",
        "ServiceSpec.progress_reporter",
        _REPORTER_TAIL,
        id="a-progress-reporter-beside-a-positional-or-keyword-progress",
    ),
    pytest.param(
        lambda: _service(lambda **handed: handed["progress"](0.5), progress_reporter=_needs_tenant),
        "tenant",
        "ServiceSpec.progress_reporter",
        _REPORTER_TAIL,
        id="a-progress-reporter-beside-a-catch-all-run",
    ),
    pytest.param(
        lambda: _retrieve(_reports_row, progress_reporter=_needs_tenant),
        "tenant",
        "SelectorSpec.progress_reporter",
        _REPORTER_TAIL,
        id="a-selector-s-progress-reporter",
    ),
]

# The seats the fifth refusal is not run on: a case each, with the keyword
# nothing fills, the seat's label and what the message says of the seat.
_SEATS_WITHOUT_THE_FIFTH = [
    pytest.param(
        lambda: _service(lambda **_: None, affordances=_when(lambda *, tenant: True)),
        "tenant",
        "ServiceSpec.affordances[0] ('c').when",
        _CONDITION_TAIL,
        id="a-service-condition",
    ),
    pytest.param(
        lambda: _service(lambda **_: None, preconditions=[_needs_tenant]),
        "tenant",
        "ServiceSpec.preconditions[0] (_needs_tenant)",
        _DECLARE_TAIL,
        id="a-service-precondition",
    ),
    pytest.param(
        lambda: _retrieve(_found, preconditions=[_needs_tenant]),
        "tenant",
        "SelectorSpec.preconditions[0] (_needs_tenant)",
        _DECLARE_TAIL,
        id="a-selector-precondition",
    ),
    pytest.param(
        lambda: _retrieve(_found, preconditions=[_needs_data]),
        "data",
        "SelectorSpec.preconditions[0] (_needs_data)",
        _DECLARE_TAIL,
        id="a-selector-precondition-requiring-data",
    ),
    pytest.param(
        lambda: _list(_none, preconditions=[_needs_instance]),
        "instance",
        "SelectorSpec.preconditions[0] (_needs_instance)",
        _DECLARE_TAIL,
        id="a-list-precondition-requiring-the-row",
    ),
    pytest.param(
        lambda: _retrieve(_found, preconditions=[_needs_collection]),
        "collection",
        "SelectorSpec.preconditions[0] (_needs_collection)",
        _DECLARE_TAIL,
        id="a-retrieve-precondition-requiring-the-rows",
    ),
    pytest.param(
        lambda: _list(_none, affordances=_mapping(lambda *, frozen: True)),
        "frozen",
        "SelectorSpec.affordances['rename'][0] ('c').when",
        _CONDITION_TAIL,
        id="a-selector-s-mapped-condition",
    ),
    pytest.param(
        lambda: _service(
            lambda **_: None,
            instance_selector_spec=_retrieve(_found, affordances=_mapping(lambda *, frozen: True)),
        ),
        "frozen",
        "ServiceSpec.instance_selector_spec.affordances['rename'][0] ('c').when",
        _CONDITION_TAIL,
        id="an-instance-target-s-mapped-condition",
    ),
    pytest.param(
        lambda: _service(
            lambda **_: None,
            collection_selector_spec=_list(_none, affordances=_mapping(lambda *, frozen: True)),
        ),
        "frozen",
        "ServiceSpec.collection_selector_spec.affordances['rename'][0] ('c').when",
        _CONDITION_TAIL,
        id="a-target-s-mapped-condition",
    ),
    pytest.param(
        lambda: _service(
            lambda **_: None,
            output_selector_spec=_list(_none, affordances=_mapping(lambda *, frozen: True)),
        ),
        "frozen",
        "ServiceSpec.output_selector_spec.affordances['rename'][0] ('c').when",
        _CONDITION_TAIL,
        id="an-output-s-mapped-condition",
    ),
    pytest.param(
        lambda: _service(lambda **_: 1, output_selector_spec=_retrieve(lambda *, pk: pk, reads=PK)),
        "pk",
        "ServiceSpec.output_selector_spec.selector",
        _OUTPUT_TAIL,
        id="an-output-selector-requiring-its-own-read",
    ),
    pytest.param(
        lambda: _service(lambda **_: 1, output_selector_spec=_retrieve(lambda *, data: data)),
        "data",
        "ServiceSpec.output_selector_spec.selector",
        _OUTPUT_TAIL,
        id="an-output-selector-requiring-data",
    ),
    pytest.param(
        lambda: _list(_notes, extend_queryset=lambda *, queryset, data: queryset),
        "data",
        "SelectorSpec.extend_queryset",
        _EXTEND_TAIL,
        id="a-selector-s-extend-queryset-requiring-data",
    ),
    pytest.param(
        lambda: _service(
            lambda **_: None,
            collection_selector_spec=_list(
                _notes, extend_queryset=lambda *, queryset, tenant: queryset
            ),
        ),
        "tenant",
        "ServiceSpec.collection_selector_spec.extend_queryset",
        _EXTEND_TAIL,
        id="a-target-s-extend-queryset",
    ),
    pytest.param(
        lambda: _service(
            lambda **_: None,
            output_selector_spec=_list(_notes, extend_queryset=lambda *, queryset, data: queryset),
        ),
        "data",
        "ServiceSpec.output_selector_spec.extend_queryset",
        _OUTPUT_TAIL,
        id="an-output-s-extend-queryset",
    ),
    *_PROVIDER_SEATS,
]

_UNFILLED += [pytest.param(*case.values[:2], id=case.id) for case in _SEATS_WITHOUT_THE_FIFTH]


_EVERY_POOL_S = ("user", "progress", "call_context", "shapes", "request", "view", "tenant")
_A_CONDITION_S = ("user", "progress", "call_context", "request", "view", "tenant")
_TITLE = Parameters.of(Parameter("title", "string", required=True))
_LIMIT_REQUIRED = Parameters.of(Parameter("limit", "integer", required=True))


def _filling(name: str, read: Parameters) -> dict[str, Any]:
    """What a seat declares so that ``name`` is its read's, or its typed provider's."""
    if name in read.names():
        return {"reads": read}
    if name == "limit":
        return {"kwargs": _fills_limit}
    return {}


def _service_condition(name: str, seen: dict[str, Any]) -> ServiceSpec:
    return _service(lambda **_: None, affordances=_when(_taking(name, seen=seen)))


def _selector_condition(name: str, seen: dict[str, Any]) -> SelectorSpec:
    return _list(_none, affordances=_mapping(_taking(name, seen=seen)))


def _target_condition(name: str, seen: dict[str, Any]) -> ServiceSpec:
    target = _list(_none, affordances=_mapping(_taking(name, seen=seen)))
    return _service(lambda **_: None, collection_selector_spec=target)


def _output_condition(name: str, seen: dict[str, Any]) -> ServiceSpec:
    output = _list(_none, affordances=_mapping(_taking(name, seen=seen)))
    return _service(lambda **_: None, output_selector_spec=output)


def _service_precondition(name: str, seen: dict[str, Any]) -> ServiceSpec:
    targets: dict[str, dict[str, Any]] = {
        "instance": {"instance_selector_spec": _retrieve(_found)},
        "collection": {"collection_selector_spec": _list(_none)},
    }
    return _service(
        lambda **_: None,
        preconditions=[_taking(name, seen=seen)],
        **_filling(name, _TITLE),
        **targets.get(name, {}),
    )


def _retrieve_precondition(name: str, seen: dict[str, Any]) -> SelectorSpec:
    # A row, since a RETRIEVE's preconditions never run without one.
    return _retrieve(_found, preconditions=[_taking(name, seen=seen)], **_filling(name, PK))


def _list_precondition(name: str, seen: dict[str, Any]) -> SelectorSpec:
    return _list(_none, preconditions=[_taking(name, seen=seen)], **_filling(name, PK))


def _output_selector(name: str, seen: dict[str, Any]) -> ServiceSpec:
    output = _retrieve(_taking(name, seen=seen, answer=1))
    return _service(lambda **_: "made", output_selector_spec=output)


def _extending(name: str, seen: dict[str, Any]) -> Callable[..., Any]:
    names = dict.fromkeys(("queryset", name))
    return _taking(*names, seen=seen, answer=lambda handed: handed["queryset"])


def _selector_extend(name: str, seen: dict[str, Any]) -> SelectorSpec:
    return _list(_notes, extend_queryset=_extending(name, seen), **_filling(name, PK))


def _target_extend(name: str, seen: dict[str, Any]) -> ServiceSpec:
    target = _list(_notes, extend_queryset=_extending(name, seen), **_filling(name, PK))
    return _service(lambda **_: None, collection_selector_spec=target)


def _output_extend(name: str, seen: dict[str, Any]) -> ServiceSpec:
    output = _list(_notes, extend_queryset=_extending(name, seen))
    return _service(lambda **_: None, output_selector_spec=output)


def _async_selector_condition(name: str, seen: dict[str, Any]) -> SelectorSpec:
    return _list(_none_async, affordances=_mapping(_taking(name, seen=seen)))


def _async_retrieve_precondition(name: str, seen: dict[str, Any]) -> SelectorSpec:
    return _retrieve(_found_async, preconditions=[_taking(name, seen=seen)], **_filling(name, PK))


def _async_selector_extend(name: str, seen: dict[str, Any]) -> SelectorSpec:
    return _list(_notes_async, extend_queryset=_extending(name, seen), **_filling(name, PK))


def _providing(name: str, seen: dict[str, Any], read: Parameters) -> dict[str, Any]:
    """A seat's ``kwargs`` requiring ``name``: its read's, or ``limit``, a read it may decline.

    The declinable read is declared required, so the fourth refusal, which
    reads a read as declared, has nothing to say of it.
    """
    if name == "limit":
        return {"reads": _LIMIT_REQUIRED, "kwargs": _declines_its_limit(seen)}
    return {"kwargs": _provider(name, seen), **({"reads": read} if name in read.names() else {})}


def _target(name: str) -> dict[str, Any]:
    """The target a service is handed as ``instance``, where ``name`` asks for it."""
    return {"instance_selector_spec": _retrieve(_found)} if name == "instance" else {}


def _service_kwargs(name: str, seen: dict[str, Any]) -> ServiceSpec:
    return _service(lambda **_: None, **_providing(name, seen, _TITLE), **_target(name))


def _service_input_data(name: str, seen: dict[str, Any]) -> ServiceSpec:
    # A read ``limit`` the spec's ``kwargs`` may decline, so the caller's
    # value stays in the call and reaches ``input_data``.
    declared: dict[str, Any] = (
        {"reads": _LIMIT_REQUIRED, "kwargs": _may_fill_limit}
        if name == "limit"
        else _filling(name, PK)
    )
    return _service(
        lambda **_: None,
        validator=Titled(),
        input_data=_provider(name, seen),
        **declared,
        **_target(name),
    )


def _selector_kwargs(name: str, seen: dict[str, Any]) -> SelectorSpec:
    return _retrieve(_found, **_providing(name, seen, PK))


def _target_kwargs(name: str, seen: dict[str, Any]) -> ServiceSpec:
    return _service(lambda **_: None, instance_selector_spec=_selector_kwargs(name, seen))


def _service_reporter(name: str, seen: dict[str, Any]) -> ServiceSpec:
    return _service(_reports, progress_reporter=_reporter(name, seen))


def _selector_reporter(name: str, seen: dict[str, Any]) -> SelectorSpec:
    return _retrieve(_reports_row, progress_reporter=_reporter(name, seen))


def _async_selector_kwargs(name: str, seen: dict[str, Any]) -> SelectorSpec:
    return _retrieve(_found_async, **_providing(name, seen, PK))


def _async_selector_reporter(name: str, seen: dict[str, Any]) -> SelectorSpec:
    return _retrieve(_reports_row_async, progress_reporter=_reporter(name, seen))


_CONDITIONS_HANDED = [
    pytest.param(build, name, id=f"{seat}-{name}")
    for seat, build in (
        ("a-service-condition", _service_condition),
        ("a-selector-s-mapped-condition", _selector_condition),
        ("a-target-s-mapped-condition", _target_condition),
        ("an-output-s-mapped-condition", _output_condition),
    )
    for name in _A_CONDITION_S
]

# Every keyword each seat the fifth refusal skips is handed, as dispatch
# hands it: each is dispatched and seen to arrive in
# TestWhatEachSeatTheFifthSkipsIsHanded, and passes the check in
# test_a_keyword_something_fills_is_not.
_HANDED = [
    *_CONDITIONS_HANDED,
    *(
        pytest.param(build, name, id=f"{seat}-{name}")
        for seat, build, names in (
            (
                "a-service-precondition",
                _service_precondition,
                (*_EVERY_POOL_S, "title", "limit", "data", "instance", "collection"),
            ),
            (
                "a-retrieve-precondition",
                _retrieve_precondition,
                (*_EVERY_POOL_S, "pk", "limit", "instance"),
            ),
            (
                "a-list-precondition",
                _list_precondition,
                (*_EVERY_POOL_S, "pk", "limit", "collection"),
            ),
            ("an-output-selector", _output_selector, (*_EVERY_POOL_S, "instance", "result")),
            (
                "a-selector-s-extend-queryset",
                _selector_extend,
                (*_EVERY_POOL_S, "pk", "limit", "queryset"),
            ),
            (
                "a-target-s-extend-queryset",
                _target_extend,
                (*_EVERY_POOL_S, "pk", "limit", "queryset"),
            ),
            (
                "an-output-s-extend-queryset",
                _output_extend,
                (*_EVERY_POOL_S, "instance", "result", "queryset"),
            ),
            ("a-service-s-kwargs", _service_kwargs, (*_EVERY_POOL_S, "title", "limit", "instance")),
            ("input-data", _service_input_data, (*_EVERY_POOL_S, "pk", "limit", "instance")),
            ("a-selector-s-kwargs", _selector_kwargs, (*_EVERY_POOL_S, "pk", "limit")),
            ("a-target-s-kwargs", _target_kwargs, (*_EVERY_POOL_S, "pk", "limit")),
            ("a-service-s-progress-reporter", _service_reporter, _EVERY_POOL_S),
            ("a-selector-s-progress-reporter", _selector_reporter, _EVERY_POOL_S),
        )
        for name in names
    ),
]


# The seats an ``async def`` selector spec reaches through its own route
# (``_open_selector``, then ``_settle_and_conclude`` after the await), which a
# sync selector never takes: the fill sets of the seats that route runs.
_ASYNC_HANDED = [
    *(
        pytest.param(_async_selector_condition, name, id=f"an-async-selector-s-condition-{name}")
        for name in _A_CONDITION_S
    ),
    *(
        pytest.param(
            _async_retrieve_precondition, name, id=f"an-async-retrieve-precondition-{name}"
        )
        for name in (*_EVERY_POOL_S, "pk", "limit", "instance")
    ),
    *(
        pytest.param(_async_selector_extend, name, id=f"an-async-extend-queryset-{name}")
        for name in (*_EVERY_POOL_S, "pk", "limit", "queryset")
    ),
    *(
        pytest.param(_async_selector_kwargs, name, id=f"an-async-selector-s-kwargs-{name}")
        for name in (*_EVERY_POOL_S, "pk", "limit")
    ),
    *(
        pytest.param(
            _async_selector_reporter, name, id=f"an-async-selector-s-progress-reporter-{name}"
        )
        for name in _EVERY_POOL_S
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
            pytest.param(
                lambda: _service(
                    lambda **_: None,
                    affordances=_when(lambda **_: True),
                    preconditions=[lambda **_: None],
                    output_selector_spec=_list(
                        lambda **_: [], extend_queryset=lambda **handed: handed["queryset"]
                    ),
                ),
                id="a-catch-all-on-every-seat-without-the-fifth",
            ),
            *(
                pytest.param(functools.partial(case.values[0], case.values[1], {}), id=case.id)
                for case in _HANDED
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

        spec = _service(lambda *, title, slug: slug, validator=_Computing())
        check_seeds(spec)
        result = dispatch(spec, principal=make_user("ada"), arguments={"title": "Ada"})
        assert result.value == "ada"


@pytest.fixture
def ada() -> Any:
    return make_user("ada")


class TestAKeywordOnlyAMountsSeedFills:
    """A condition, a precondition or a provider requiring a seed the mount does not register."""

    _CASES = [
        pytest.param(
            lambda: _service(lambda **_: None, affordances=_when(lambda *, tenant: True)),
            "ServiceSpec.affordances[0] ('c').when",
            id="a-condition",
        ),
        pytest.param(
            lambda: _service(lambda **_: None, preconditions=[_needs_tenant]),
            "ServiceSpec.preconditions[0] (_needs_tenant)",
            id="a-service-precondition",
        ),
        pytest.param(
            lambda: _list(_none, preconditions=[_needs_tenant]),
            "SelectorSpec.preconditions[0] (_needs_tenant)",
            id="a-selector-precondition",
        ),
        *(pytest.param(case.values[0], case.values[2], id=case.id) for case in _PROVIDER_SEATS),
    ]

    @pytest.mark.parametrize(("build", "label"), _CASES)
    def test_it_is_refused_where_the_seed_is_not_registered(
        self, build: Callable[[], Any], label: str
    ) -> None:
        refused = _refusal(build(), pool_seeds=DEFAULT_POOL_SEEDS)
        assert f"{label} requires the keyword(s) ['tenant'], {_NOTHING_FILLS}" in refused

    @pytest.mark.parametrize(("build", "label"), _CASES)
    def test_it_passes_where_the_seed_is_registered(
        self, build: Callable[[], Any], label: str
    ) -> None:
        check_seeds(build(), pool_seeds=_SEEDED)


def _rename() -> ServiceSpec:
    frozen = Affordance(
        code="frozen", reason="The row is frozen.", when=lambda *, frozen: not frozen
    )
    return _service(lambda **_: "renamed", affordances=[frozen])


_FROZEN = DEFAULT_POOL_SEEDS.extend(frozen=lambda: False)


class TestAConditionReadingASeedNoMountRegisters:
    """A rename whose condition reads ``frozen``, and a list answering it for each row."""

    _CASES = [
        pytest.param(_rename, id="the-operation"),
        pytest.param(
            lambda: _list(_none, affordances={"rename": _rename()}), id="a-list-mapping-it"
        ),
    ]

    @pytest.mark.parametrize("build", _CASES)
    def test_dispatch_fails_every_call_without_the_seed(self, build: Callable[[], Any]) -> None:
        with pytest.raises(TypeError, match="frozen"):
            dispatch(build(), principal=make_user("ada"), arguments={})

    @pytest.mark.parametrize("build", _CASES)
    def test_it_is_refused_without_the_seed(self, build: Callable[[], Any]) -> None:
        assert f"requires the keyword(s) ['frozen'], {_NOTHING_FILLS}" in _refusal(build())

    @pytest.mark.parametrize("build", _CASES)
    def test_it_passes_and_runs_with_the_seed(self, build: Callable[[], Any]) -> None:
        check_seeds(build(), pool_seeds=_FROZEN)
        dispatch(build(), principal=make_user("ada"), arguments={}, pool_seeds=_FROZEN)


class TestTheSeatsTheFifthRefusalSkips:
    @pytest.mark.parametrize(("build", "name", "label", "tail"), _SEATS_WITHOUT_THE_FIFTH)
    def test_each_is_named_with_what_it_is_handed(
        self, build: Callable[[], Any], name: str, label: str, tail: str
    ) -> None:
        refused = _refusal(build())
        assert refused.startswith(f"{label} requires the keyword(s) ['{name}'], {_NOTHING_FILLS}: ")
        assert tail in refused
        # A seat that sees no reads is never told that no read declares it.
        assert ("no read" in refused) is (tail in (_DECLARE_TAIL, _EXTEND_TAIL))

    def test_a_service_precondition_beside_a_validator_is_left_to_dispatch(self) -> None:
        seen: dict[str, Any] = {}
        spec = _service(
            lambda **_: None, validator=_Computing(), preconditions=[_taking("slug", seen=seen)]
        )
        check_seeds(spec)
        dispatch(spec, principal=make_user("ada"), arguments={"title": "Ada"})
        assert seen == {"slug": "ada"}

    def test_a_selector_precondition_beside_an_untyped_provider_is_left_to_dispatch(self) -> None:
        seen: dict[str, Any] = {}
        spec = _retrieve(_found, kwargs=_untyped_other, preconditions=[_taking("other", seen=seen)])
        check_seeds(spec)
        dispatch(spec, principal=make_user("ada"), arguments={})
        assert seen == {"other": 2}

    def test_an_extend_queryset_beside_an_untyped_provider_is_left_to_dispatch(self) -> None:
        seen: dict[str, Any] = {}
        extend = _taking("queryset", "other", seen=seen, answer=lambda handed: handed["queryset"])
        spec = _list(_notes, kwargs=_untyped_other, extend_queryset=extend)
        check_seeds(spec)
        dispatch(spec, principal=make_user("ada"), arguments={})
        assert seen["other"] == 2

    @pytest.mark.parametrize(
        "build",
        [
            pytest.param(
                lambda: _service(
                    lambda **_: None,
                    instance_selector_spec=_retrieve(_found),
                    affordances=_when(Q(archived=False)),
                ),
                id="the-operation-s",
            ),
            pytest.param(
                lambda: _list(
                    _none,
                    affordances={
                        "archive": _service(
                            lambda **_: None,
                            instance_selector_spec=_retrieve(_found),
                            affordances=_when(Q(archived=False)),
                        )
                    },
                ),
                id="a-mapped-one",
            ),
        ],
    )
    def test_a_condition_on_the_row_binds_nothing_and_is_not_read(
        self, build: Callable[[], Any]
    ) -> None:
        check_seeds(build())

    def test_a_service_spec_s_are_named_in_the_order_a_call_reaches_them(self) -> None:
        spec = _service(
            lambda *, s3, progress: None,
            collection_selector_spec=_list(
                lambda *, a1, tenant_id: [],
                kwargs=_scoped_by("a0"),
                affordances=_mapping(lambda *, a2: True),
                extend_queryset=lambda *, queryset, a3: queryset,
            ),
            kwargs=_scoped_by("k1"),
            affordances=_when(lambda *, s1: True),
            preconditions=[lambda *, s2: None],
            progress_reporter=lambda *, r1: None,
            output_selector_spec=_list(
                lambda *, z1: [],
                affordances=_mapping(lambda *, z2: True),
                extend_queryset=lambda *, queryset, z3: queryset,
            ),
        )
        refused = _refusal(spec)
        order = ["a0", "a1", "a2", "a3", "k1", "s1", "s2", "s3", "r1", "z1", "z2", "z3"]
        found = [refused.index(f"['{name}']") for name in order]
        assert found == sorted(found)

    def test_input_data_is_named_before_the_spec_s_kwargs(self) -> None:
        """``input_data`` runs before the Validator, and ``kwargs`` after it, before the conditions."""
        spec = _service(
            lambda **_: None,
            instance_selector_spec=_retrieve(lambda *, a1, tenant_id: 1, kwargs=_scoped_by("a0")),
            validator=Titled(),
            input_data=lambda *, i1: {},
            kwargs=lambda *, k1: {},
            affordances=_when(lambda *, s1: True),
        )
        refused = _refusal(spec)
        found = [refused.index(f"['{name}']") for name in ("a0", "a1", "i1", "k1", "s1")]
        assert found == sorted(found)

    def test_a_selector_spec_s_are_named_in_the_order_a_call_reaches_them(self) -> None:
        """Its ``progress_reporter`` beside its selector: resolved by the run, before ``settle``."""
        spec = _list(
            lambda *, a1, progress, tenant_id: [],
            kwargs=_scoped_by("a0"),
            progress_reporter=lambda *, r1: None,
            affordances=_mapping(lambda *, a2: True),
            extend_queryset=lambda *, queryset, a3: queryset,
            preconditions=[lambda *, a4: None],
        )
        refused = _refusal(spec)
        found = [refused.index(f"['{name}']") for name in ("a0", "a1", "r1", "a2", "a3", "a4")]
        assert found == sorted(found)


class TestWhatEachSeatTheFifthSkipsIsHanded:
    """Each keyword the check counts as filled on a seat the fifth refusal skips, dispatched and seen to arrive.

    The guard against refusing a spec that runs: the check passes each of
    these (test_a_keyword_something_fills_is_not), so each must reach its
    callable on a real call. Each fixture is sized so the seat runs: a row
    for a RETRIEVE's precondition, a QuerySet for ``extend_queryset``, and a
    list, never ``None``, for a selector whose conditions are answered.
    """

    @pytest.mark.parametrize(("build", "name"), _HANDED)
    def test_dispatch_hands_it(self, build: Callable[..., Any], name: str) -> None:
        seen: dict[str, Any] = {}
        spec = build(name, seen)
        arguments = {param.name: _SAMPLES[param.type] for param in spec.parameters()}
        dispatch(spec, principal=make_user("ada"), arguments=arguments, pool_seeds=_SEEDED)
        assert name in seen

    @pytest.mark.parametrize(("build", "name"), _CONDITIONS_HANDED)
    async def test_adispatch_hands_a_condition_it(
        self, build: Callable[..., Any], name: str, ada: Any
    ) -> None:
        seen: dict[str, Any] = {}
        await adispatch(build(name, seen), principal=ada, arguments={}, pool_seeds=_SEEDED)
        assert name in seen

    @pytest.mark.parametrize(("build", "name"), _ASYNC_HANDED)
    async def test_adispatch_hands_it_on_an_async_selector(
        self, build: Callable[..., Any], name: str, ada: Any
    ) -> None:
        """Through ``_open_selector`` and ``_settle_and_conclude``, which a sync selector never reaches."""
        seen: dict[str, Any] = {}
        spec = build(name, seen)
        arguments = {param.name: _SAMPLES[param.type] for param in spec.parameters()}
        await adispatch(spec, principal=ada, arguments=arguments, pool_seeds=_SEEDED)
        assert name in seen

    @pytest.mark.parametrize(("build", "name"), _ASYNC_HANDED)
    def test_check_seeds_passes_what_an_async_selector_is_handed(
        self, build: Callable[..., Any], name: str
    ) -> None:
        check_seeds(build(name, {}), pool_seeds=_SEEDED)


def _unreadable_run() -> Callable[..., Any]:
    """A run whose ``__signature__`` is no ``Signature``, for the ``TypeError`` arm."""

    def run(**_: Any) -> None: ...

    setattr(run, "__signature__", 3)  # noqa: B010
    return run


class TestAProviderSeat:
    """A provider is bound from a pool of its own, refused as any seat is, and never derived from its callable's."""

    @pytest.mark.parametrize(
        ("build", "name"),
        [
            pytest.param(
                lambda: _retrieve(_found_async, kwargs=_scope), "tenant", id="an-async-selector"
            ),
            pytest.param(
                lambda: _service(_found_async, kwargs=_scope), "tenant", id="an-async-service"
            ),
            pytest.param(
                lambda: _service(_reports_async, progress_reporter=_needs_tenant),
                "tenant",
                id="an-async-service-s-progress-reporter",
            ),
            pytest.param(
                lambda: _retrieve(_reports_row_async, progress_reporter=_needs_tenant),
                "tenant",
                id="an-async-selector-s-progress-reporter",
            ),
            pytest.param(
                lambda: _retrieve(_reports_row, progress_reporter=_needs_tenant),
                "tenant",
                id="a-sync-selector-s-progress-reporter",
            ),
        ],
    )
    async def test_adispatch_fails_every_call_with_it(
        self, build: Callable[[], Any], name: str, ada: Any
    ) -> None:
        spec = build()
        assert f"requires the keyword(s) ['{name}'], {_NOTHING_FILLS}" in _refusal(spec)
        with pytest.raises(TypeError, match=name):
            await adispatch(spec, principal=ada, arguments={})

    @pytest.mark.parametrize(
        "run",
        [
            pytest.param(lambda: None, id="no-progress"),
            pytest.param(lambda *, other=1: None, id="another-keyword"),
            pytest.param(lambda progress=None, /: None, id="a-positional-only-progress"),
        ],
    )
    def test_a_progress_reporter_beside_a_run_taking_no_progress_is_not_read(
        self, run: Callable[..., Any]
    ) -> None:
        """Dispatch calls it only where the run takes ``progress``, so it requires nothing of the rest.

        Dispatched to hold the claim: the reporter requiring ``tenant``,
        unregistered, is never called.
        """
        spec = _service(run, progress_reporter=_needs_tenant)
        check_seeds(spec)
        dispatch(spec, principal=make_user("ada"), arguments={})

    def test_a_selector_s_progress_reporter_beside_a_run_taking_no_progress_is_not_read(
        self,
    ) -> None:
        spec = _retrieve(lambda: 1, progress_reporter=_needs_tenant)
        check_seeds(spec)
        dispatch(spec, principal=make_user("ada"), arguments={})

    @pytest.mark.parametrize(
        "run",
        [
            pytest.param(dict, id="no-signature"),
            pytest.param(_unreadable_run(), id="a-signature-that-is-not-one"),
        ],
    )
    def test_a_run_whose_signature_cannot_be_read_is_refused_alone(
        self, run: Callable[..., Any]
    ) -> None:
        """The run's own refusal answers it; whether it takes ``progress`` is not read."""
        refused = _refusal(_service(run, progress_reporter=_needs_tenant))
        assert "ServiceSpec.service is" in refused
        assert "progress_reporter" not in refused

    def test_a_typed_provider_is_handed_what_its_seat_names(self) -> None:
        """The probe: refused without the seed, and the seed reaches the provider and its callable."""
        spec = _service(lambda *, tenant_id: tenant_id, kwargs=_scope)
        assert _refusal(spec).startswith(
            f"ServiceSpec.kwargs requires the keyword(s) ['tenant'], {_NOTHING_FILLS}: "
        )
        check_seeds(spec, pool_seeds=_SEEDED)
        result = dispatch(spec, principal=make_user("ada"), arguments={}, pool_seeds=_SEEDED)
        assert result.value == "acme"


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


def _positional_title(title: str, /) -> None: ...


def _positional_pk(pk: int, /) -> None: ...


_LIMIT = Parameters.of(Parameter("limit", "integer"))


def _requires_limit(*, limit: int) -> None: ...


def _pks_precondition(*, pks: list[int]) -> None: ...


def _extends_with_pks(*, queryset: Any, pks: list[int]) -> Any:
    return queryset


def _extends_with_limit(*, queryset: Any, limit: int) -> Any:
    return queryset


# A positional-only parameter something fills by name on its seat (a read, the
# pool's ``user``, ``queryset``, ``result``), so the third refusal has nothing
# to say and only the second can answer. One case per place a seat is built:
# the spec builder, the label, the arguments the call sends.
_POSITIONAL_SEATS = [
    pytest.param(
        lambda: _service(lambda **_: None, reads=_TITLE, preconditions=[_positional_title]),
        "title",
        "ServiceSpec.preconditions[0] (_positional_title)",
        id="a-service-precondition",
    ),
    pytest.param(
        lambda: _retrieve(_found, reads=PK, preconditions=[_positional_pk]),
        "pk",
        "SelectorSpec.preconditions[0] (_positional_pk)",
        id="a-retrieve-precondition",
    ),
    pytest.param(
        lambda: _list(_none, reads=PK, preconditions=[_positional_pk]),
        "pk",
        "SelectorSpec.preconditions[0] (_positional_pk)",
        id="a-list-precondition",
    ),
    pytest.param(
        lambda: _service(lambda **_: None, affordances=_when(lambda user, /: True)),
        "user",
        "ServiceSpec.affordances[0] ('c').when",
        id="a-service-condition",
    ),
    pytest.param(
        lambda: _list(_none, affordances=_mapping(lambda user, /: True)),
        "user",
        "SelectorSpec.affordances['rename'][0] ('c').when",
        id="a-selector-s-mapped-condition",
    ),
    pytest.param(
        lambda: _service(
            lambda **_: None,
            collection_selector_spec=_list(_none, affordances=_mapping(lambda user, /: True)),
        ),
        "user",
        "ServiceSpec.collection_selector_spec.affordances['rename'][0] ('c').when",
        id="a-target-s-mapped-condition",
    ),
    pytest.param(
        lambda: _service(
            lambda **_: None,
            instance_selector_spec=_retrieve(_found, affordances=_mapping(lambda user, /: True)),
        ),
        "user",
        "ServiceSpec.instance_selector_spec.affordances['rename'][0] ('c').when",
        id="an-instance-target-s-mapped-condition",
    ),
    pytest.param(
        lambda: _service(
            lambda **_: None,
            output_selector_spec=_list(_none, affordances=_mapping(lambda user, /: True)),
        ),
        "user",
        "ServiceSpec.output_selector_spec.affordances['rename'][0] ('c').when",
        id="an-output-s-mapped-condition",
    ),
    pytest.param(
        lambda: _list(_notes, extend_queryset=lambda queryset, /: queryset),
        "queryset",
        "SelectorSpec.extend_queryset",
        id="a-selector-s-extend-queryset",
    ),
    pytest.param(
        lambda: _service(
            lambda **_: None,
            collection_selector_spec=_list(_notes, extend_queryset=lambda queryset, /: queryset),
        ),
        "queryset",
        "ServiceSpec.collection_selector_spec.extend_queryset",
        id="a-target-s-extend-queryset",
    ),
    pytest.param(
        lambda: _service(
            lambda **_: None,
            instance_selector_spec=_retrieve(_notes, extend_queryset=lambda queryset, /: queryset),
        ),
        "queryset",
        "ServiceSpec.instance_selector_spec.extend_queryset",
        id="an-instance-target-s-extend-queryset",
    ),
    pytest.param(
        lambda: _service(
            lambda **_: None,
            output_selector_spec=_list(_notes, extend_queryset=lambda queryset, /: queryset),
        ),
        "queryset",
        "ServiceSpec.output_selector_spec.extend_queryset",
        id="an-output-s-extend-queryset",
    ),
    pytest.param(
        lambda: _service(lambda **_: "made", output_selector_spec=_retrieve(lambda result, /: 1)),
        "result",
        "ServiceSpec.output_selector_spec.selector",
        id="an-output-selector",
    ),
    pytest.param(
        lambda: _service(lambda **_: None, kwargs=lambda user, /: {}),
        "user",
        "ServiceSpec.kwargs",
        id="a-service-s-kwargs",
    ),
    pytest.param(
        lambda: _service(lambda **_: None, validator=Titled(), input_data=lambda user, /: {}),
        "user",
        "ServiceSpec.input_data",
        id="input-data",
    ),
    pytest.param(
        lambda: _retrieve(_found, kwargs=lambda user, /: {}),
        "user",
        "SelectorSpec.kwargs",
        id="a-selector-s-kwargs",
    ),
    pytest.param(
        lambda: _service(
            lambda **_: None, instance_selector_spec=_retrieve(_found, kwargs=lambda user, /: {})
        ),
        "user",
        "ServiceSpec.instance_selector_spec.kwargs",
        id="an-instance-target-s-kwargs",
    ),
    pytest.param(
        lambda: _service(_reports, progress_reporter=lambda user, /: None),
        "user",
        "ServiceSpec.progress_reporter",
        id="a-service-s-progress-reporter",
    ),
    pytest.param(
        lambda: _retrieve(_reports_row, progress_reporter=lambda user, /: None),
        "user",
        "SelectorSpec.progress_reporter",
        id="a-selector-s-progress-reporter",
    ),
]

# The seats a positional-only parameter is refused on though the third
# refusal leaves them to dispatch.
_POSITIONAL_BESIDE = [
    pytest.param(
        lambda: _retrieve(_found, reads=PK, kwargs=_untyped, preconditions=[_positional_pk]),
        "pk",
        {"pk": 1},
        id="a-selector-precondition-beside-an-untyped-provider",
    ),
    pytest.param(
        lambda: _service(
            lambda **_: None,
            validator=DataclassValidator(_Titled),
            preconditions=[_positional_title],
        ),
        "title",
        {"title": "t"},
        id="a-service-precondition-beside-a-validator",
    ),
]


class TestAPositionalOnlyParameterOnTheOtherSeats:
    """The second refusal on a precondition, a condition, the output selector and an ``extend_queryset``."""

    @pytest.mark.parametrize(("build", "name", "label"), _POSITIONAL_SEATS)
    def test_dispatch_fails_every_call_with_it(
        self, build: Callable[[], Any], name: str, label: str
    ) -> None:
        spec = build()
        arguments = {param.name: _SAMPLES[param.type] for param in spec.parameters()}
        with pytest.raises(TypeError, match="positional"):
            dispatch(spec, principal=make_user("ada"), arguments=arguments)

    @pytest.mark.parametrize(("build", "name", "label"), _POSITIONAL_SEATS)
    def test_it_is_refused_though_something_fills_it_by_name(
        self, build: Callable[[], Any], name: str, label: str
    ) -> None:
        refused = _refusal(build())
        assert f"{label} takes the {_POSITIONAL} parameter(s) ['{name}']" in refused
        assert _NOTHING_FILLS not in refused

    @pytest.mark.parametrize(("build", "name", "arguments"), _POSITIONAL_BESIDE)
    def test_dispatch_fails_every_call_beside_what_the_third_leaves_to_it(
        self, build: Callable[[], Any], name: str, arguments: dict[str, Any]
    ) -> None:
        with pytest.raises(TypeError, match="positional"):
            dispatch(build(), principal=make_user("ada"), arguments=arguments)

    @pytest.mark.parametrize(("build", "name", "arguments"), _POSITIONAL_BESIDE)
    def test_it_is_refused_beside_a_validator_or_an_untyped_provider(
        self, build: Callable[[], Any], name: str, arguments: dict[str, Any]
    ) -> None:
        refused = _refusal(build())
        assert f"the {_POSITIONAL} parameter(s) ['{name}']" in refused
        assert _NOTHING_FILLS not in refused

    def test_one_with_a_default_is_not(self) -> None:
        spec = _service(
            lambda **_: None,
            affordances=_when(lambda user=None, /: True),
            preconditions=[lambda title=None, /: None],
            reads=_TITLE,
        )
        check_seeds(spec)


# An optional ``limit`` read over a keyword the callable requires, on each seat
# that carries reads: the spec builder, the label, and what a call leaving it
# out raises - the shape check's refusal, or a provider's own ``TypeError``.
_OPTIONAL_SEATS = [
    pytest.param(
        lambda: _service(lambda **_: None, reads=_LIMIT, preconditions=[_requires_limit]),
        "ServiceSpec.preconditions[0] (_requires_limit)",
        InvalidArguments,
        id="a-service-precondition",
    ),
    pytest.param(
        lambda: _retrieve(_found, reads=_LIMIT, preconditions=[_requires_limit]),
        "SelectorSpec.preconditions[0] (_requires_limit)",
        InvalidArguments,
        id="a-retrieve-precondition",
    ),
    pytest.param(
        lambda: _list(_none, reads=_LIMIT, preconditions=[_requires_limit]),
        "SelectorSpec.preconditions[0] (_requires_limit)",
        InvalidArguments,
        id="a-list-precondition",
    ),
    pytest.param(
        lambda: _list(_notes, reads=_LIMIT, extend_queryset=_extends_with_limit),
        "SelectorSpec.extend_queryset",
        InvalidArguments,
        id="a-selector-s-extend-queryset",
    ),
    pytest.param(
        lambda: _service(
            lambda **_: None,
            collection_selector_spec=_list(
                _notes, reads=_LIMIT, extend_queryset=_extends_with_limit
            ),
        ),
        "ServiceSpec.collection_selector_spec.extend_queryset",
        InvalidArguments,
        id="a-target-s-extend-queryset",
    ),
    pytest.param(
        lambda: _service(
            lambda **_: None,
            instance_selector_spec=_retrieve(
                _notes, reads=_LIMIT, extend_queryset=_extends_with_limit
            ),
        ),
        "ServiceSpec.instance_selector_spec.extend_queryset",
        InvalidArguments,
        id="an-instance-target-s-extend-queryset",
    ),
    pytest.param(
        lambda: _service(lambda **_: None, reads=_LIMIT, kwargs=_provides_from_limit),
        "ServiceSpec.kwargs",
        TypeError,
        id="a-service-s-kwargs",
    ),
    pytest.param(
        lambda: _service(
            lambda **_: None,
            reads=_LIMIT,
            validator=DataclassValidator(_Untitled),
            input_data=_provides_from_limit,
        ),
        "ServiceSpec.input_data",
        TypeError,
        id="input-data",
    ),
    pytest.param(
        lambda: _retrieve(_found, reads=_LIMIT, kwargs=_provides_from_limit),
        "SelectorSpec.kwargs",
        TypeError,
        id="a-selector-s-kwargs",
    ),
    pytest.param(
        lambda: _service(
            lambda **_: None,
            instance_selector_spec=_retrieve(_found, reads=_LIMIT, kwargs=_provides_from_limit),
        ),
        "ServiceSpec.instance_selector_spec.kwargs",
        TypeError,
        id="an-instance-target-s-kwargs",
    ),
]


def _untyped_limit() -> dict[str, Any]:
    return {"limit": 5}


class _ReturnsLimit(Validator):
    """Returns ``limit``, which it never declares."""

    def parameters(self) -> Parameters:
        return _TITLE

    def validate(self, arguments: Mapping[str, Any], context: ValidationContext) -> dict[str, Any]:
        return {"title": arguments["title"], "limit": 5}


# An optional ``limit`` read the callable requires, that a provider or a
# Validator fills beyond the read: the check cannot see what either returns,
# so it leaves the seat to dispatch, which runs the call without ``limit``
# sent. One case per seat the bail applies to, each with the arguments sent.
_OPTIONAL_BESIDE = [
    pytest.param(
        lambda seen: _retrieve(
            _found,
            reads=_LIMIT,
            kwargs=_untyped_limit,
            preconditions=[_taking("limit", seen=seen)],
        ),
        {},
        id="a-precondition-beside-an-untyped-provider",
    ),
    pytest.param(
        lambda seen: _list(
            _notes, reads=_LIMIT, kwargs=_untyped_limit, extend_queryset=_extending("limit", seen)
        ),
        {},
        id="an-extend-queryset-beside-an-untyped-provider",
    ),
    pytest.param(
        lambda seen: _service(
            lambda **_: None,
            reads=_LIMIT,
            validator=_ReturnsLimit(),
            preconditions=[_taking("limit", seen=seen)],
        ),
        {"title": "t"},
        id="a-service-precondition-beside-a-validator",
    ),
]

# Two optional reads a precondition requires: the offenders are all of them,
# sorted (test_it_names_every_one_sorted).
_TWO_OPTIONAL = Parameters.of(Parameter("limit", "integer"), Parameter("after", "integer"))


class TestAnOptionalReadOnTheOtherSeats:
    """The fourth refusal on a precondition and an ``extend_queryset``, the seats that are handed reads.

    A condition and the output selector are handed none, so there is nothing
    for it to find on them.
    """

    @pytest.mark.parametrize(("build", "label", "error"), _OPTIONAL_SEATS)
    def test_dispatch_refuses_a_call_leaving_it_out(
        self, build: Callable[[], Any], label: str, error: type[Exception]
    ) -> None:
        with pytest.raises(error) as refused:
            dispatch(build(), principal=make_user("ada"), arguments={})
        if isinstance(refused.value, InvalidArguments):
            assert set(refused.value.detail) == {"limit"}
        else:
            assert "'limit'" in str(refused.value)

    @pytest.mark.parametrize(
        "build",
        [
            pytest.param(
                lambda: _retrieve(_found_async, reads=_LIMIT, preconditions=[_requires_limit]),
                id="an-async-retrieve-precondition",
            ),
            pytest.param(
                lambda: _list(_notes_async, reads=_LIMIT, extend_queryset=_extends_with_limit),
                id="an-async-extend-queryset",
            ),
        ],
    )
    async def test_adispatch_refuses_a_call_leaving_it_out_on_an_async_selector(
        self, build: Callable[[], Any], ada: Any
    ) -> None:
        """The same refusal through ``_settle_and_conclude``, the route only an async selector takes.

        An ``extend_queryset`` binds there with the reads ``adispatch`` was
        given; a RETRIEVE's precondition takes its ``fillable`` from
        ``conclude_selector``, not from ``adispatch``.
        """
        spec = build()
        with pytest.raises(InvalidArguments) as refused:
            await adispatch(spec, principal=ada, arguments={})
        assert set(refused.value.detail) == {"limit"}
        await adispatch(spec, principal=ada, arguments={"limit": 1})

    @pytest.mark.parametrize(("build", "label", "error"), _OPTIONAL_SEATS)
    def test_a_call_sending_it_runs(
        self, build: Callable[[], Any], label: str, error: type[Exception]
    ) -> None:
        dispatch(build(), principal=make_user("ada"), arguments={"limit": 1})

    @pytest.mark.parametrize(("build", "label", "error"), _OPTIONAL_SEATS)
    def test_it_is_refused(
        self, build: Callable[[], Any], label: str, error: type[Exception]
    ) -> None:
        refused = _refusal(build())
        assert f"{label} requires the keyword(s) ['limit'], {_OPTIONAL}" in refused
        # What the call leaving it out meets, in the words of the seat.
        omitted = (
            "is refused as missing"
            if error is InvalidArguments
            else "fails with the provider's own TypeError"
        )
        assert f"so a call leaving one out {omitted}" in refused
        assert _NOTHING_FILLS not in refused
        assert _POSITIONAL not in refused

    @pytest.mark.parametrize(("build", "arguments"), _OPTIONAL_BESIDE)
    def test_it_is_left_to_dispatch_beside_an_untyped_provider_or_a_validator(
        self, build: Callable[[dict[str, Any]], Any], arguments: dict[str, Any]
    ) -> None:
        """The fourth is bailed from where the third is, though ``checks_items`` is false.

        A mutant running it on these seats whatever the provider or Validator
        may return refuses a spec whose call sends no ``limit`` and runs.
        """
        seen: dict[str, Any] = {}
        spec = build(seen)
        check_seeds(spec)
        dispatch(spec, principal=make_user("ada"), arguments=arguments)
        assert seen["limit"] == 5

    def test_it_names_every_one_sorted(self) -> None:
        """Both offenders, ``after`` before ``limit``, whichever order the callable declares them."""
        spec = _retrieve(
            _found,
            reads=_TWO_OPTIONAL,
            preconditions=[_taking("limit", "after", seen={})],
        )
        refused = _refusal(spec)
        assert "requires the keyword(s) ['after', 'limit']," in refused

    @pytest.mark.parametrize(
        ("limit", "keywords"),
        [
            pytest.param(Parameter("limit", "integer", required=True), {}, id="demanded"),
            pytest.param(Parameter("limit", "integer"), {"kwargs": _fills_limit}, id="typed"),
        ],
    )
    def test_one_something_else_fills_is_not(
        self, limit: Parameter, keywords: dict[str, Any]
    ) -> None:
        spec = _retrieve(
            _found, reads=Parameters.of(limit), preconditions=[_requires_limit], **keywords
        )
        check_seeds(spec)


class TestTheFifthRefusalIsNotRunOnThem:
    """An array read with no ``items`` is refused on the callable it fills, not on a precondition or an ``extend_queryset``."""

    @pytest.mark.parametrize(
        "build",
        [
            pytest.param(
                lambda: _service(
                    lambda **_: None,
                    reads=Parameters.of(Parameter("pks", "array", required=True)),
                    preconditions=[_pks_precondition],
                ),
                id="a-service-precondition",
            ),
            pytest.param(
                lambda: _retrieve(
                    _found,
                    reads=Parameters.of(Parameter("pks", "array", required=True)),
                    preconditions=[_pks_precondition],
                ),
                id="a-selector-precondition",
            ),
            pytest.param(
                lambda: _list(
                    _notes,
                    reads=Parameters.of(Parameter("pks", "array", required=True)),
                    extend_queryset=_extends_with_pks,
                ),
                id="an-extend-queryset",
            ),
        ],
    )
    def test_a_precondition_s_array_read_with_no_items_is_not_the_fifth_s(
        self, build: Callable[[], Any]
    ) -> None:
        spec = build()
        check_seeds(spec)
        dispatch(spec, principal=make_user("ada"), arguments={"pks": [1]})


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


# A provider seat's callable with no signature to read, and the seat's label.
_UNREADABLE_PROVIDERS = [
    (_service(lambda **_: None, kwargs=dict), "ServiceSpec.kwargs"),
    (_service(lambda **_: None, validator=Titled(), input_data=dict), "ServiceSpec.input_data"),
    (_retrieve(_found, kwargs=dict), "SelectorSpec.kwargs"),
    (
        _service(lambda **_: None, instance_selector_spec=_retrieve(_found, kwargs=dict)),
        "ServiceSpec.instance_selector_spec.kwargs",
    ),
    (
        _service(lambda **_: None, collection_selector_spec=_list(_none, kwargs=dict)),
        "ServiceSpec.collection_selector_spec.kwargs",
    ),
    (_service(_reports, progress_reporter=dict), "ServiceSpec.progress_reporter"),
    (_retrieve(_reports_row, progress_reporter=dict), "SelectorSpec.progress_reporter"),
]


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
            pytest.param(
                _service(lambda **_: None, preconditions=[dict]),
                "ServiceSpec.preconditions[0] (dict)",
                id="service-precondition",
            ),
            pytest.param(
                _retrieve(_found, preconditions=[dict]),
                "SelectorSpec.preconditions[0] (dict)",
                id="selector-precondition",
            ),
            pytest.param(
                _service(lambda **_: 1, output_selector_spec=_retrieve(dict)),
                "ServiceSpec.output_selector_spec.selector",
                id="output-selector",
            ),
            pytest.param(
                _list(_notes, extend_queryset=dict),
                "SelectorSpec.extend_queryset",
                id="extend-queryset",
            ),
            *(pytest.param(spec, seat, id=f"{seat}") for spec, seat in _UNREADABLE_PROVIDERS),
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
            pytest.param(
                _service(lambda **_: None, preconditions=[dict]),
                ValueError,
                id="service-precondition",
            ),
            pytest.param(
                _retrieve(_found, preconditions=[dict]), ValueError, id="selector-precondition"
            ),
            pytest.param(
                _service(lambda **_: 1, output_selector_spec=_retrieve(dict)),
                ValueError,
                id="output-selector",
            ),
            pytest.param(_list(_notes, extend_queryset=dict), ValueError, id="extend-queryset"),
            *(pytest.param(spec, ValueError, id=f"{seat}") for spec, seat in _UNREADABLE_PROVIDERS),
        ],
    )
    def test_dispatch_fails_every_call_that_reaches_it(
        self, spec: Any, error: type[Exception]
    ) -> None:
        # Holds the claim that the declaration cannot run, for each seat:
        # every declared argument sent, so the call reaches it.
        arguments = {param.name: _SAMPLES[param.type] for param in spec.parameters()}
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


@pytest.mark.parametrize("case", EVERY_ASK)
def test_describe_time_readers_hand_none(case: str) -> None:
    """Registration is outside any call, so it invents no dict for the Validator."""
    spec, validator, _, _ = every_ask_case(case)
    check_seeds(spec, pool_seeds=TENANT_SEEDS)
    assert validator.asked
    assert validator.asked == [None] * len(validator.asked)
