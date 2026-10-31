"""The call's ``request`` and ``view``, read off its context for every callable naming one.

The behavioural tests name the two keys as strings rather than importing the
constant, so each runs against a tree that has none and fails on its assertion.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping
from typing import Any

import pytest
from asgiref.sync import async_to_sync
from django.core.exceptions import ImproperlyConfigured

from django_service_specs.authorization.permission_check import PermissionCheck
from django_service_specs.dispatch.adispatch import adispatch
from django_service_specs.dispatch.authorize import authorize
from django_service_specs.dispatch.authorize_scope import authorize_scope
from django_service_specs.dispatch.authorize_target import authorize_target
from django_service_specs.dispatch.check_server_arguments import check_server_arguments
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.dispatch.resolve_target import resolve_target
from django_service_specs.parameters.parameters import Parameter, Parameters
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS, PoolSeeds
from django_service_specs.pool.reserved_pool_seeds import RESERVED_POOL_SEEDS
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.server_owned_keys import server_owned_keys
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.affordance import Affordance
from django_service_specs.types.selector_kind import SelectorKind
from django_service_specs.types.server_arguments import ServerArguments
from django_service_specs.validation.validated import Validated
from django_service_specs.validation.validation_context import ValidationContext
from django_service_specs.validation.validator import Validator
from tests.dispatch.utils import OPEN, PK, Titled, make_user
from tests.dispatch_app.models import Note

pytestmark = pytest.mark.django_db

_ENTRIES = pytest.mark.parametrize(
    "entry", [dispatch, async_to_sync(adispatch)], ids=["sync", "async"]
)


class _Marker:
    """A value no stage could have made up, so ``is`` tells it from any other."""

    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:
        return f"<{self.name}>"


class _Saw:
    """Records the ``request`` and ``view`` each stage was handed, by the stage's name."""

    def __init__(self) -> None:
        self.seen: dict[str, list[tuple[Any, Any]]] = {}

    def __call__(self, stage: str, request: Any, view: Any) -> None:
        self.seen.setdefault(stage, []).append((request, view))

    def all_are(self, request: Any, view: Any) -> bool:
        return all(
            seen_request is request and seen_view is view
            for pairs in self.seen.values()
            for seen_request, seen_view in pairs
        )


class _Check(PermissionCheck):
    """Admits everything; each question declares ``request`` and ``view`` and records them."""

    def __init__(self, saw: _Saw) -> None:
        self.saw = saw

    def has_permission(self, principal: Any, spec: Any, *, request: Any, view: Any) -> bool:
        self.saw("has_permission", request, view)
        return True

    def has_object_permission(
        self, principal: Any, spec: Any, target: Any, *, request: Any, view: Any
    ) -> bool:
        self.saw("has_object_permission", request, view)
        return True

    def has_scope_permission(
        self, principal: Any, spec: Any, scope: Any, *, request: Any, view: Any
    ) -> bool:
        self.saw("has_scope_permission", request, view)
        return True


class _Validator(Titled):
    """``Titled``, keeping the ``ambient`` its context was handed."""

    def __init__(self) -> None:
        super().__init__()
        self.ambient: dict[str, Any] | None = None

    def validate(self, arguments: Mapping[str, Any], context: ValidationContext) -> dict[str, Any]:
        self.ambient = dict(context.ambient)
        return super().validate(arguments, context)


def _every_stage(
    saw: _Saw, *, pool_seeds: PoolSeeds = DEFAULT_POOL_SEEDS, validator: Validator | None = None
) -> ServiceSpec:
    """An update whose every stage declares ``request`` and ``view`` and records them."""

    def instance(*, pk: int, request: Any, view: Any) -> Any:
        saw("instance_selector", request, view)
        return Note.objects.filter(pk=pk)

    def provider(*, request: Any, view: Any) -> dict[str, Any]:
        saw("kwargs", request, view)
        return {}

    def server_input(*, request: Any, view: Any) -> dict[str, Any]:
        saw("input_data", request, view)
        return {}

    def when(*, request: Any, view: Any) -> bool:
        saw("affordance", request, view)
        return True

    def precondition(*, request: Any, view: Any) -> None:
        saw("precondition", request, view)

    def reporter(*, request: Any, view: Any) -> None:
        saw("progress_reporter", request, view)

    def service(*, instance: Any, request: Any, view: Any, progress: Any) -> Any:
        saw("service", request, view)
        # A report, since a sync run asks its reporter on the first one.
        progress(1.0)
        return instance

    def reread(*, result: Any, request: Any, view: Any) -> Any:
        saw("output_selector", request, view)
        return Note.objects.filter(pk=result.pk)

    return ServiceSpec(
        service=service,
        permissions=(_Check(saw),),
        validator=_Validator() if validator is None else validator,
        instance_selector_spec=SelectorSpec(
            kind=SelectorKind.RETRIEVE, selector=instance, reads=PK
        ),
        kwargs=provider,
        input_data=server_input,
        affordances=[Affordance(code="open", reason="Never refused.", when=when)],
        preconditions=[precondition],
        progress_reporter=reporter,
        output_selector_spec=SelectorSpec(kind=SelectorKind.RETRIEVE, selector=reread),
    )


_SERVICE_STAGES = {
    "has_permission",
    "instance_selector",
    "has_object_permission",
    "input_data",
    "kwargs",
    "affordance",
    "precondition",
    "progress_reporter",
    "service",
    "output_selector",
}


def test_the_call_seeds_are_request_and_view_and_no_dispatcher_name() -> None:
    """Outside ``RESERVED_POOL_SEEDS``, which ``extend`` refuses and ``spec.parameters()`` too."""
    call_seeds = importlib.import_module("django_service_specs.pool.call_seeds").CALL_SEEDS
    assert call_seeds == frozenset({"request", "view"})
    assert not call_seeds & RESERVED_POOL_SEEDS
    assert importlib.import_module("django_service_specs").CALL_SEEDS is call_seeds


class TestEveryStage:
    """Each stage dispatch resolves is handed the very objects the call's context holds."""

    @_ENTRIES
    def test_a_service_spec_s_stages_are_handed_the_context_s_request_and_view(
        self, entry: Callable[..., Any]
    ) -> None:
        ada = make_user("ada")
        note = Note.objects.create(title="n", owner=ada)
        saw = _Saw()
        request, view = _Marker("request"), _Marker("view")
        entry(
            _every_stage(saw),
            principal=ada,
            arguments={"pk": note.pk, "title": "t"},
            call_context={"request": request, "view": view},
        )
        assert set(saw.seen) == _SERVICE_STAGES
        assert saw.all_are(request, view)

    @_ENTRIES
    def test_with_neither_key_in_the_context_every_stage_is_handed_none(
        self, entry: Callable[..., Any]
    ) -> None:
        ada = make_user("ada")
        note = Note.objects.create(title="n", owner=ada)
        saw = _Saw()
        entry(_every_stage(saw), principal=ada, arguments={"pk": note.pk, "title": "t"})
        assert set(saw.seen) == _SERVICE_STAGES
        assert saw.all_are(None, None)

    @_ENTRIES
    def test_a_selector_spec_s_stages_are_handed_them(self, entry: Callable[..., Any]) -> None:
        saw = _Saw()

        def rows(*, request: Any, view: Any) -> Any:
            saw("selector", request, view)
            return Note.objects.all()

        def provider(*, request: Any, view: Any) -> dict[str, Any]:
            saw("kwargs", request, view)
            return {}

        def precondition(*, request: Any, view: Any) -> None:
            saw("precondition", request, view)

        def narrowed(*, queryset: Any, request: Any, view: Any) -> Any:
            saw("extend_queryset", request, view)
            return queryset

        spec = SelectorSpec(
            kind=SelectorKind.LIST,
            selector=rows,
            permissions=(_Check(saw),),
            kwargs=provider,
            preconditions=[precondition],
            extend_queryset=narrowed,
        )
        request, view = _Marker("request"), _Marker("view")
        entry(
            spec,
            principal=make_user("ada"),
            arguments={},
            call_context={"request": request, "view": view},
        )
        assert set(saw.seen) == {
            "has_permission",
            "has_scope_permission",
            "selector",
            "kwargs",
            "precondition",
            "extend_queryset",
        }
        assert saw.all_are(request, view)

    @_ENTRIES
    def test_an_async_service_s_progress_reporter_is_handed_them(
        self, entry: Callable[..., Any]
    ) -> None:
        """Asked before the run, from sync code, as an ``async def`` service needs."""
        seen: list[Any] = []

        def reporter(*, request: Any, view: Any) -> None:
            seen.append((request, view))

        async def service(*, progress: Any) -> None:
            progress(1.0)

        request = _Marker("request")
        entry(
            ServiceSpec(service=service, permissions=OPEN, progress_reporter=reporter),
            principal=make_user("ada"),
            arguments={},
            call_context={"request": request},
        )
        assert seen == [(request, None)]

    @_ENTRIES
    def test_a_catch_all_is_handed_neither(self, entry: Callable[..., Any]) -> None:
        """By name only, as the call's context is: a ``**kwargs`` seat is handed what it was before.

        A catch-all forwarding its ``**kwargs`` into a strict callable would
        otherwise raise on two keys more, at the service and at a seed's
        resolver alike.
        """
        handed: dict[str, Any] = {}

        def service(**kwargs: Any) -> None:
            handed.update(kwargs)

        seeds = DEFAULT_POOL_SEEDS.extend(seen=lambda **kwargs: sorted(kwargs))
        entry(
            ServiceSpec(service=service, permissions=OPEN),
            principal=make_user("ada"),
            arguments={},
            call_context={"request": _Marker("request"), "view": _Marker("view")},
            pool_seeds=seeds,
        )
        assert sorted(handed) == ["data", "progress", "seen", "user"]
        assert handed["seen"] == ["progress", "user"]

    @_ENTRIES
    def test_the_validator_s_ambient_holds_neither(self, entry: Callable[..., Any]) -> None:
        """``ambient`` is the seeds alone; a Validator reads the two off its ``call_context``."""
        ada = make_user("ada")
        note = Note.objects.create(title="n", owner=ada)
        validator = _Validator()
        entry(
            _every_stage(_Saw(), validator=validator),
            principal=ada,
            arguments={"pk": note.pk, "title": "t"},
            call_context={"request": _Marker("request"), "view": _Marker("view")},
        )
        assert validator.ambient is not None
        assert set(validator.ambient) == {"user", "progress"}


def _owned_by_the_request(*, pk: int, request: Any) -> Any:
    """A lookup scoped by what it reads off the request, so another value finds another row."""
    return Note.objects.filter(pk=pk, owner=request.owner)


def test_a_target_selector_finds_the_same_row_on_every_route() -> None:
    ada, bob = make_user("ada"), make_user("bob")
    note = Note.objects.create(title="n", owner=ada)
    spec = ServiceSpec(
        service=lambda *, instance: instance,
        permissions=OPEN,
        instance_selector_spec=SelectorSpec(
            kind=SelectorKind.RETRIEVE, selector=_owned_by_the_request, reads=PK
        ),
    )
    call_context = {"request": _Request(ada)}
    arguments = {"pk": note.pk}
    found, _ = resolve_target(spec, principal=bob, arguments=arguments, call_context=call_context)
    ran = dispatch(spec, principal=bob, arguments=arguments, call_context=call_context)
    aran = async_to_sync(adispatch)(
        spec, principal=bob, arguments=arguments, call_context=call_context
    )
    assert found == ran.value == aran.value == note


class _Request:
    def __init__(self, owner: Any) -> None:
        self.owner = owner


class TestASeedResolver:
    """A resolver declaring either name is handed the call's value, read off the context."""

    @_ENTRIES
    def test_a_seed_resolved_with_its_pool_reads_the_request(
        self, entry: Callable[..., Any]
    ) -> None:
        seeds = DEFAULT_POOL_SEEDS.extend(tenant=lambda *, request: request.owner)
        ada = make_user("ada")
        result = entry(
            ServiceSpec(service=lambda *, tenant: tenant, permissions=OPEN),
            principal=ada,
            arguments={},
            pool_seeds=seeds,
            call_context={"request": _Request(ada)},
        )
        assert result.value == ada

    @_ENTRIES
    def test_a_seed_resolved_early_for_a_check_reads_the_request(
        self, entry: Callable[..., Any]
    ) -> None:
        """The check names the seed, so it resolves before the class-level check."""
        seen: list[Any] = []

        class TenantCheck(PermissionCheck):
            def has_permission(self, principal: Any, spec: Any, *, tenant: Any) -> bool:
                seen.append(tenant)
                return True

        seeds = DEFAULT_POOL_SEEDS.extend(tenant=lambda *, request: request.owner)
        ada = make_user("ada")
        result = entry(
            ServiceSpec(service=lambda *, tenant: tenant, permissions=(TenantCheck(),)),
            principal=ada,
            arguments={},
            pool_seeds=seeds,
            call_context={"request": _Request(ada)},
        )
        assert seen == [ada]
        assert result.value == ada

    @_ENTRIES
    def test_a_seed_resolver_naming_the_call_context_is_handed_it(
        self, entry: Callable[..., Any]
    ) -> None:
        """Its pool carries the context, so the two can be read off it; and so it is handed it.

        A resolver read neither before, and nothing else of the call's context
        reaches a pool through a seed's resolution.
        """
        call_context = {"locale": "fr"}
        seeds = DEFAULT_POOL_SEEDS.extend(locale=lambda *, call_context: call_context["locale"])
        result = entry(
            ServiceSpec(service=lambda *, locale: locale, permissions=OPEN),
            principal=make_user("ada"),
            arguments={},
            pool_seeds=seeds,
            call_context=call_context,
        )
        assert result.value == "fr"


class TestAMountRegisteringEither:
    """A mount that registers ``request`` or ``view`` keeps its own; the kernel skips the name.

    The registries are built exactly as the two packages build theirs:
    djangorestframework-services by the constructor, django-spec-agents through
    ``extend``. Both pass on a tree without the change, and hold that it breaks
    neither.
    """

    @pytest.mark.parametrize(
        "registry",
        [
            lambda request, view: PoolSeeds(
                seeds=(("request", lambda: request), ("view", lambda: view))
            ),
            lambda request, view: DEFAULT_POOL_SEEDS.extend(
                request=lambda: request, view=lambda: view
            ),
        ],
        ids=["constructor", "extend"],
    )
    @_ENTRIES
    def test_the_registered_seed_supplies_the_name(
        self, entry: Callable[..., Any], registry: Callable[[Any, Any], PoolSeeds]
    ) -> None:
        ada = make_user("ada")
        note = Note.objects.create(title="n", owner=ada)
        saw = _Saw()
        request, view = _Marker("registered-request"), _Marker("registered-view")
        entry(
            _every_stage(saw),
            principal=ada,
            arguments={"pk": note.pk, "title": "t"},
            pool_seeds=registry(request, view),
            # A different pair in the context, so the test tells which one won.
            call_context={"request": _Marker("context-request"), "view": _Marker("context-view")},
        )
        assert set(saw.seen) == _SERVICE_STAGES
        assert saw.all_are(request, view)

    @_ENTRIES
    def test_another_resolver_on_that_mount_reads_the_context_s_request(
        self, entry: Callable[..., Any]
    ) -> None:
        """The kernel's value is in the pool every resolver binds against, before any seed."""
        ada = make_user("ada")
        request = _Request(ada)
        seeds = DEFAULT_POOL_SEEDS.extend(
            request=lambda: request,
            view=lambda: None,
            tenant=lambda *, request: request.owner,
        )
        result = entry(
            ServiceSpec(service=lambda *, tenant: tenant, permissions=OPEN),
            principal=ada,
            arguments={},
            pool_seeds=seeds,
            call_context={"request": request},
        )
        assert result.value == ada

    @_ENTRIES
    def test_a_registered_view_still_reaches_a_catch_all(self, entry: Callable[..., Any]) -> None:
        """A registered seed is a pool entry, so ``**kwargs`` is handed it, as before."""
        handed: dict[str, Any] = {}

        def service(**kwargs: Any) -> None:
            handed.update(kwargs)

        view = _Marker("registered-view")
        entry(
            ServiceSpec(service=service, permissions=OPEN),
            principal=make_user("ada"),
            arguments={},
            pool_seeds=DEFAULT_POOL_SEEDS.extend(view=lambda: view),
            call_context={"request": _Marker("request"), "view": _Marker("context-view")},
        )
        assert handed["view"] is view
        assert "request" not in handed


class _Returning(Validator):
    """Declares ``title`` and returns ``returns`` whatever it is handed."""

    def __init__(self, returns: Mapping[str, Any]) -> None:
        self.returns = returns

    def parameters(self) -> Parameters:
        return Parameters.of(Parameter("title", "string"))

    def validate(self, arguments: Mapping[str, Any], context: ValidationContext) -> dict[str, Any]:
        return dict(self.returns)


class _Fielded(Validator):
    """Declares a top-level field named ``name`` and returns what it is handed."""

    def __init__(self, name: str) -> None:
        self.name = name

    def parameters(self) -> Parameters:
        return Parameters.of(Parameter(self.name, "string", required=True))

    def validate(self, arguments: Mapping[str, Any], context: ValidationContext) -> dict[str, Any]:
        return dict(arguments)


class TestAnArgumentNamedEither:
    """No argument may meet the call's value in one pool, so a spec naming one is refused."""

    @pytest.mark.parametrize("where", ["a-many-list", "a-selector-read", "a-selector-shape"])
    @pytest.mark.parametrize("name", ["request", "view"])
    @_ENTRIES
    def test_a_parameter_named_either_is_refused(
        self, entry: Callable[..., Any], name: str, where: str
    ) -> None:
        """The parameters of either name a spec can still be built with, refused on every call.

        A service spec's read, its target selector's or its shape of either
        name is refused when the spec is built
        (``tests/specs/test_utils.py``'s ``TestAParameterNamedForTheCallsOwnSeat``);
        a selector spec's own is not, since it is also built where its
        parameters are no call's.
        """
        declared = Parameters.of(Parameter(name, "string"))
        spec: ServiceSpec | SelectorSpec
        if where == "a-many-list":
            spec = ServiceSpec(
                service=lambda **_: None,
                permissions=OPEN,
                many=True,
                many_argument=name,
                validator=Titled(),
            )
        else:
            spec = SelectorSpec(
                kind=SelectorKind.LIST,
                selector=lambda **_: Note.objects.none(),
                permissions=OPEN,
                **({"reads": declared} if where == "a-selector-read" else {"shapes": declared}),
            )
        with pytest.raises(ImproperlyConfigured, match=rf"\['{name}'\].*the call's own"):
            entry(spec, principal=make_user("ada"), arguments={})

    @pytest.mark.parametrize("reflected", [False, True])
    @pytest.mark.parametrize("name", ["request", "view"])
    @_ENTRIES
    def test_an_output_selector_s_read_named_request_builds_and_runs(
        self, entry: Callable[..., Any], name: str, reflected: bool
    ) -> None:
        """Its reads are never the call's parameters, and its selector is handed the call's own by name.

        So it is neither refused when the spec is built nor at dispatch,
        whether or not it is marked ``reflected``.
        """
        marker = _Marker(name)
        seen: list[Any] = []

        def output(*, request: Any, view: Any, instance: Any) -> Any:
            seen.append(request if name == "request" else view)
            return Note.objects.none()

        out = SelectorSpec(
            kind=SelectorKind.LIST,
            selector=output,
            permissions=OPEN,
            reads=Parameters.of(Parameter(name, "string", reflected=reflected)),
        )
        spec = ServiceSpec(
            service=lambda **_: None,
            permissions=OPEN,
            output_selector_spec=out.derive(permissions=None),
        )
        entry(spec, principal=make_user("ada"), arguments={}, call_context={name: marker})
        assert seen == [marker]

    @pytest.mark.parametrize("name", ["request", "view"])
    @_ENTRIES
    def test_a_reflected_read_named_either_is_the_call_s(
        self, entry: Callable[..., Any], name: str
    ) -> None:
        """Read off a selector's signature, so the selector's own: the context fills it.

        As a reflected read named like a registered seed is the seed's: no
        caller argument carries it, and the selector is handed the call's.
        """
        marker = _Marker(name)
        seen: list[Any] = []

        def named(*, request: Any = None, view: Any = None) -> Any:
            seen.append(request if name == "request" else view)
            return Note.objects.none()

        spec = SelectorSpec(
            kind=SelectorKind.LIST,
            selector=named,
            permissions=OPEN,
            reads=Parameters.of(Parameter(name, "string", reflected=True)),
        )
        entry(spec, principal=make_user("ada"), arguments={}, call_context={name: marker})
        assert seen == [marker]

    @pytest.mark.parametrize("name", ["request", "view"])
    @_ENTRIES
    def test_a_validator_field_named_request_takes_the_seat(
        self, entry: Callable[..., Any], name: str
    ) -> None:
        """Into ``data``, and never the pool: the service naming it reads the call's own.

        As a field named like a registered seed does. Fails with the name
        refused, and, without the call's names among the fields the pool keeps
        out, on the second assertion.
        """
        seen: dict[str, Any] = {}

        def service(*, data: Any, request: Any, view: Any) -> None:
            seen.update(data=data, request=request, view=view)

        call_context = {"request": _Marker("request"), "view": _Marker("view")}
        entry(
            ServiceSpec(service=service, permissions=OPEN, validator=_Fielded(name)),
            principal=make_user("ada"),
            arguments={name: "sent"},
            call_context=call_context,
        )
        assert seen["data"] == {name: "sent"}
        assert seen[name] is call_context[name]

    @pytest.mark.parametrize("name", ["request", "view"])
    @_ENTRIES
    def test_a_validator_returning_either_is_refused(
        self, entry: Callable[..., Any], name: str
    ) -> None:
        """A returned value of either name would outrank the context's, so it is refused."""
        spec = ServiceSpec(
            service=lambda **_: "ran",
            permissions=OPEN,
            validator=_Returning({name: "spread"}),
        )
        with pytest.raises(ImproperlyConfigured, match=rf"returned the key\(s\) \['{name}'\]"):
            entry(spec, principal=make_user("ada"), arguments={})

    @pytest.mark.parametrize("name", ["request", "view"])
    @_ENTRIES
    def test_a_validator_binding_either_is_refused(
        self, entry: Callable[..., Any], name: str
    ) -> None:
        """A bound value of either name would outrank the context's, so it is refused."""

        class Binds(_Returning):
            def validated(self, arguments: Mapping[str, Any], context: ValidationContext) -> Any:
                return Validated(values={}, data={}, pool={name: "bound"})

        spec = ServiceSpec(service=lambda **_: "ran", permissions=OPEN, validator=Binds({}))
        with pytest.raises(ImproperlyConfigured, match=rf"bound the key\(s\) \['{name}'\]"):
            entry(spec, principal=make_user("ada"), arguments={})

    @pytest.mark.parametrize("name", ["request", "view"])
    @pytest.mark.parametrize(
        "spec",
        [
            pytest.param(
                lambda name: ServiceSpec(
                    service=lambda **_: None, permissions=OPEN, kwargs=lambda: {name: "x"}
                ),
                id="service-kwargs",
            ),
            pytest.param(
                lambda name: SelectorSpec(
                    kind=SelectorKind.LIST,
                    selector=lambda **_: Note.objects.none(),
                    permissions=OPEN,
                    kwargs=lambda: {name: "x"},
                ),
                id="selector-kwargs",
            ),
        ],
    )
    @_ENTRIES
    def test_a_provider_returning_request_is_refused(
        self, entry: Callable[..., Any], spec: Callable[[str], Any], name: str
    ) -> None:
        """Its value would outrank the context's for every callable naming the name."""
        with pytest.raises(ImproperlyConfigured, match=rf"returned the key\(s\) \['{name}'\]"):
            entry(spec(name), principal=make_user("ada"), arguments={})

    @pytest.mark.parametrize("name", ["request", "view"])
    @pytest.mark.parametrize(
        "spec",
        [
            pytest.param(
                lambda: ServiceSpec(service=lambda **_: None, permissions=OPEN), id="service"
            ),
            pytest.param(
                lambda: SelectorSpec(
                    kind=SelectorKind.LIST,
                    selector=lambda **_: Note.objects.none(),
                    permissions=OPEN,
                ),
                id="selector",
            ),
        ],
    )
    @_ENTRIES
    def test_an_overlay_key_named_either_is_refused(
        self, entry: Callable[..., Any], spec: Callable[[], Any], name: str
    ) -> None:
        with pytest.raises(ImproperlyConfigured, match=rf"returned the key\(s\) \['{name}'\]"):
            entry(spec(), principal=make_user("ada"), arguments={}, extra_kwargs={name: "x"})

    @_ENTRIES
    def test_a_validator_field_named_like_a_registered_one_validates_into_data(
        self, entry: Callable[..., Any]
    ) -> None:
        """On a mount registering the name, the field takes a registered seed's seat."""
        request = _Marker("registered-request")
        seen: dict[str, Any] = {}

        def service(*, data: Any, request: Any) -> None:
            seen.update(data=data, request=request)

        entry(
            ServiceSpec(service=service, permissions=OPEN, validator=_Fielded("request")),
            principal=make_user("ada"),
            arguments={"request": "sent"},
            pool_seeds=DEFAULT_POOL_SEEDS.extend(request=lambda: request),
        )
        assert seen == {"data": {"request": "sent"}, "request": request}


class TestEverySeedPool:
    """Each pool a seed resolves in carries the call's context, so a tenant read off the request binds."""

    @_ENTRIES
    def test_a_selector_spec_s_seed_reads_the_request(self, entry: Callable[..., Any]) -> None:
        request = _Marker("request")
        seen: list[Any] = []

        def rows(*, tenant: Any) -> Any:
            seen.append(tenant)
            return Note.objects.none()

        entry(
            SelectorSpec(kind=SelectorKind.LIST, selector=rows, permissions=OPEN),
            principal=make_user("ada"),
            arguments={},
            call_context={"request": request},
            pool_seeds=DEFAULT_POOL_SEEDS.extend(tenant=lambda *, request: request),
        )
        assert seen == [request]

    @_ENTRIES
    def test_the_output_selector_s_seed_reads_the_request(self, entry: Callable[..., Any]) -> None:
        request = _Marker("request")
        seen: list[Any] = []
        ada = make_user("ada")

        def output(*, result: Any, tenant: Any) -> Any:
            seen.append(tenant)
            return Note.objects.filter(pk=result.pk)

        entry(
            ServiceSpec(
                service=lambda: Note.objects.create(title="x", owner=ada),
                permissions=OPEN,
                output_selector_spec=SelectorSpec(kind=SelectorKind.RETRIEVE, selector=output),
            ),
            principal=ada,
            arguments={},
            call_context={"request": request},
            pool_seeds=DEFAULT_POOL_SEEDS.extend(tenant=lambda *, request: request),
        )
        assert seen == [request]

    def test_a_seed_for_an_object_or_a_scope_check_reads_the_request(self) -> None:
        seen: list[tuple[str, Any]] = []

        class TenantCheck(PermissionCheck):
            def has_permission(self, principal: Any, spec: Any) -> bool:
                return True

            def has_object_permission(
                self, principal: Any, spec: Any, target: Any, *, tenant: Any
            ) -> bool:
                seen.append(("object", tenant))
                return True

            def has_scope_permission(
                self, principal: Any, spec: Any, scope: Any, *, tenant: Any
            ) -> bool:
                seen.append(("scope", tenant))
                return True

        seeds = DEFAULT_POOL_SEEDS.extend(tenant=lambda *, request: request.name)
        call_context = {"request": _Marker("acme")}
        spec = SelectorSpec(kind=SelectorKind.LIST, selector=list, permissions=[TenantCheck()])
        principal = make_user("ada")
        grant = authorize(spec, principal)
        authorize_target(
            spec, principal, "row", grant=grant, pool_seeds=seeds, call_context=call_context
        )
        authorize_scope(
            spec, principal, [], grant=grant, pool_seeds=seeds, call_context=call_context
        )
        assert seen == [("object", "acme"), ("scope", "acme")]


def _reading(name: str, *, reflected: bool) -> SelectorSpec:
    return SelectorSpec(
        kind=SelectorKind.LIST,
        selector=lambda **_: Note.objects.none(),
        permissions=OPEN,
        reads=Parameters.of(Parameter(name, "string", reflected=reflected, required=False)),
    )


class TestTheTransportFacingAnswers:
    """What a transport reads to build its own schema says what dispatch does with either name."""

    @pytest.mark.parametrize("name", ["request", "view"])
    def test_server_owned_keys_owns_a_reflected_read_named_either(self, name: str) -> None:
        """Dispatch fills it from the context and refuses a caller's, so no caller is asked for it."""
        assert name in server_owned_keys(_reading(name, reflected=True))
        assert name not in server_owned_keys(_reading("title", reflected=True))
        assert name not in server_owned_keys(_reading(name, reflected=False))

    def test_server_owned_keys_owns_a_target_selector_s_reflected_read(self) -> None:
        target = _reading("view", reflected=True)
        spec = ServiceSpec(
            service=lambda **_: None,
            permissions=OPEN,
            collection_selector_spec=target.derive(permissions=None),
        )
        assert "view" in server_owned_keys(spec)

    @pytest.mark.parametrize("reflected", [False, True], ids=["a-read", "a-reflected-read"])
    def test_server_arguments_naming_either_say_it_is_the_call_s(self, reflected: bool) -> None:
        spec = _reading("view", reflected=reflected)
        server = ServerArguments(values={"view": "grid"})
        with pytest.raises(ImproperlyConfigured, match="'request' and 'view' are the call's own"):
            check_server_arguments(spec, server)
        # A registered seed of the name is the mount's, so the note is left out.
        with pytest.raises(ImproperlyConfigured) as refused:
            check_server_arguments(
                spec, server, pool_seeds=DEFAULT_POOL_SEEDS.extend(view=lambda: None)
            )
        assert "the call's own" not in str(refused.value)
