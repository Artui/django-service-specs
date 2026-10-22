"""The kernel's three seats: where a provider's parameter and a registered seed's name are answered.

- **Seat (a)**: a parameter a provider *may* fill - a typed provider's
  declinable key, or any parameter in the seat an untyped provider's values
  reach - is not demanded by the shape check. Its requiredness is checked
  against the assembled pool once the provider has answered, in the seat that
  merges the answer, and so is every parameter the seat takes.
- **Seat (b)**: a read marked ``reflected`` that a registered seed is named
  like leaves the call's argument set, and the seed fills it.
- **Seat (c)**: a top-level Validator field named like a registered seed stays
  the caller's argument, is validated into ``data``, and is never spread into
  the service's pool, where the seed keeps its own value.

Every ``Parameter(..., reflected=True)`` is built inside a test, never at
import, so this module collects against a ``Parameter`` with no such field.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import pytest
from asgiref.sync import async_to_sync
from django import forms
from django.core.exceptions import ImproperlyConfigured
from typing_extensions import TypedDict

from django_service_specs.adapters.forms.form_validator import FormValidator
from django_service_specs.authorization.not_permitted import NotPermitted
from django_service_specs.dispatch.adispatch import adispatch
from django_service_specs.dispatch.bind_arguments import bind_arguments
from django_service_specs.dispatch.check_call import check_call
from django_service_specs.dispatch.check_requested_input import check_requested_input
from django_service_specs.dispatch.check_server_arguments import check_server_arguments
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.dispatch.resolve_target import resolve_target
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.parameters import Parameter, Parameters
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.server_owned_keys import server_owned_keys
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.selector_kind import SelectorKind
from django_service_specs.types.server_arguments import ServerArguments
from django_service_specs.types.unknown_arguments import UnknownArguments
from django_service_specs.types.unset import UNSET, UnsetType
from django_service_specs.validation.validation_context import ValidationContext
from django_service_specs.validation.validator import Validator
from tests.dispatch.utils import (
    OPEN,
    PK,
    TENANT_SEEDS,
    Arguing,
    Record,
    Refuse,
    make_user,
    note_by_pk,
)
from tests.dispatch_app.models import Note

pytestmark = pytest.mark.django_db

LIST = SelectorKind.LIST
RETRIEVE = SelectorKind.RETRIEVE
REQUIRED = ["This field is required."]
SEEDED = "tenant-of-ada"
"""What ``TENANT_SEEDS`` resolves for ada: a value no caller here ever sends."""

ENTRIES = pytest.mark.parametrize(
    "entry", [dispatch, async_to_sync(adispatch)], ids=["sync", "async"]
)
POLICIES = pytest.mark.parametrize(
    "policy", [UnknownArguments.REJECT, UnknownArguments.IGNORE], ids=["reject", "ignore"]
)


@pytest.fixture
def ada() -> Any:
    return make_user("ada")


def _project(**kwargs: Any) -> Parameters:
    return Parameters.of(Parameter("project_pk", "integer", required=True, **kwargs))


def _tenant(**kwargs: Any) -> Parameters:
    """A ``tenant`` parameter, as a reflected read or a field declares it."""
    return Parameters.of(Parameter("tenant", "string", **kwargs))


class Fields(Validator):
    """Declares the parameters it is given and returns what it is handed, through the base ``validated()``."""

    def __init__(self, *parameters: Parameter) -> None:
        self._parameters = Parameters.of(*parameters)
        self.calls: list[dict[str, Any]] = []

    def parameters(self) -> Parameters:
        return self._parameters

    def validate(self, arguments: Mapping[str, Any], context: ValidationContext) -> dict[str, Any]:
        self.calls.append(dict(arguments))
        return dict(arguments)


# --- seat (a): a parameter a provider may fill -------------------------------------------


class _DecliningProject(TypedDict):
    project_pk: int | UnsetType


class _MaybeProject(TypedDict, total=False):
    project_pk: int


def _declining(value: Any, calls: list[None]) -> Callable[[], _DecliningProject]:
    """A typed provider that may decline ``project_pk``, answering ``value``."""

    def server() -> _DecliningProject:
        calls.append(None)
        return {"project_pk": value}

    return server


def _untyped(answer: Mapping[str, Any], calls: list[None]) -> Callable[..., Any]:
    """A provider whose return names no keys, answering ``answer``."""

    def server() -> dict[str, Any]:
        calls.append(None)
        return dict(answer)

    return server


def _filled(value: Any, calls: list[None]) -> Callable[[], _MaybeProject]:
    """A typed provider annotated to fill ``project_pk``; ``UNSET`` or no value declines it."""

    def server() -> _MaybeProject:
        calls.append(None)
        return {} if value is None else {"project_pk": value}

    return server


def test_a_read_an_untyped_provider_may_fill_left_out_reaches_the_class_level_check(
    ada: Any,
) -> None:
    # Relaxed at step one, so the refusing check answers first and no
    # provider has run: it stays after class-level authorization. The
    # declinable key's twin is test_a_declinable_key_left_out_reaches_the_class_level_check.
    calls: list[None] = []
    spec = ServiceSpec(
        service=Record(), permissions=[Refuse()], reads=_project(), kwargs=_untyped({}, calls)
    )
    with pytest.raises(NotPermitted):
        dispatch(spec, principal=ada, arguments={})
    assert calls == []


@ENTRIES
@pytest.mark.parametrize(
    "provider",
    [
        pytest.param(lambda calls: _declining(7, calls), id="a-declinable-key"),
        pytest.param(lambda calls: _untyped({"project_pk": 7}, calls), id="an-untyped-provider"),
    ],
)
def test_a_may_fill_read_the_provider_answers_reaches_the_service(
    ada: Any, entry: Any, provider: Callable[[list[None]], Any]
) -> None:
    calls: list[None] = []
    service = Record()
    spec = ServiceSpec(service=service, permissions=OPEN, reads=_project(), kwargs=provider(calls))
    entry(spec, principal=ada, arguments={})
    assert service.calls[0]["project_pk"] == 7
    assert calls == [None]


@ENTRIES
@pytest.mark.parametrize(
    "provider",
    [
        pytest.param(lambda calls: _declining(UNSET, calls), id="a-declinable-key"),
        pytest.param(lambda calls: _untyped({}, calls), id="an-untyped-provider"),
    ],
)
def test_a_may_fill_read_nobody_fills_is_refused_at_the_service_seat(
    ada: Any, entry: Any, provider: Callable[[list[None]], Any]
) -> None:
    # The service takes ``**pool``, so ``call_keywords`` would never ask for
    # it: the refusal is the seat's, keyed by the read, after the provider ran.
    calls: list[None] = []
    service = Record()
    spec = ServiceSpec(service=service, permissions=OPEN, reads=_project(), kwargs=provider(calls))
    with pytest.raises(InvalidArguments) as caught:
        entry(spec, principal=ada, arguments={})
    assert caught.value.detail == {"project_pk": REQUIRED}
    assert calls == [None]
    assert service.calls == []


def test_a_may_fill_read_the_caller_sends_stands_when_an_untyped_provider_leaves_it_out(
    ada: Any,
) -> None:
    calls: list[None] = []
    service = Record()
    spec = ServiceSpec(
        service=service, permissions=OPEN, reads=_project(), kwargs=_untyped({}, calls)
    )
    dispatch(spec, principal=ada, arguments={"project_pk": 3})
    assert service.calls[0]["project_pk"] == 3


def test_a_may_fill_read_the_caller_sends_is_still_checked(ada: Any) -> None:
    calls: list[None] = []
    spec = ServiceSpec(
        service=Record(), permissions=OPEN, reads=_project(), kwargs=_untyped({}, calls)
    )
    with pytest.raises(InvalidArguments) as caught:
        dispatch(spec, principal=ada, arguments={"project_pk": "x"})
    assert caught.value.detail == {"project_pk": ["Expected an integer."]}
    assert calls == []


def test_a_check_s_arguments_lack_a_may_fill_read_the_caller_left_out(ada: Any) -> None:
    arguing = Arguing()
    spec = ServiceSpec(
        service=Record(), permissions=[arguing], reads=_project(), kwargs=_untyped({}, [])
    )
    with pytest.raises(InvalidArguments):
        dispatch(spec, principal=ada, arguments={})
    assert arguing.questions()[0] == ("has_permission", {})


@ENTRIES
@pytest.mark.parametrize("answers", [True, False], ids=["answered", "left-out"])
def test_a_selector_spec_s_read_an_untyped_provider_may_fill(
    ada: Any, entry: Any, answers: bool
) -> None:
    # The selector declares a default, so only the seat can refuse.
    note = Note.objects.create(owner=ada, title="Row")

    def by_pk(*, pk: int = 0) -> Any:
        return Note.objects.filter(pk=pk)

    spec = SelectorSpec(
        kind=RETRIEVE,
        selector=by_pk,
        permissions=OPEN,
        reads=PK,
        kwargs=_untyped({"pk": note.pk} if answers else {}, []),
    )
    if answers:
        assert entry(spec, principal=ada, arguments={}).value == note
        return
    with pytest.raises(InvalidArguments) as caught:
        entry(spec, principal=ada, arguments={})
    assert caught.value.detail == {"pk": REQUIRED}


@pytest.mark.parametrize("answers", [True, False], ids=["answered", "left-out"])
def test_a_target_read_an_untyped_lookup_provider_may_fill(ada: Any, answers: bool) -> None:
    note = Note.objects.create(owner=ada, title="Row")

    def by_pk(*, pk: int = 0) -> Any:
        return Note.objects.filter(pk=pk)

    service = Record()
    target = SelectorSpec(
        kind=RETRIEVE,
        selector=by_pk,
        reads=PK,
        kwargs=_untyped({"pk": note.pk} if answers else {}, []),
    )
    spec = ServiceSpec(service=service, permissions=OPEN, instance_selector_spec=target)
    if answers:
        dispatch(spec, principal=ada, arguments={})
        assert service.calls[0]["instance"] == note
        return
    with pytest.raises(InvalidArguments) as caught:
        dispatch(spec, principal=ada, arguments={})
    assert caught.value.detail == {"pk": REQUIRED}
    assert service.calls == []


def test_a_target_read_is_relaxed_only_by_the_lookup_s_own_provider(ada: Any) -> None:
    # The spec's untyped ``kwargs`` reaches the spec's reads, never the
    # target's, so the target's ``pk`` stays required of the caller.
    target = SelectorSpec(kind=RETRIEVE, selector=note_by_pk, reads=PK)
    spec = ServiceSpec(
        service=Record(),
        permissions=[Refuse()],
        instance_selector_spec=target,
        kwargs=_untyped({}, []),
    )
    with pytest.raises(InvalidArguments) as caught:
        dispatch(spec, principal=ada, arguments={})
    assert caught.value.detail == {"pk": REQUIRED}


class _TitleForm(forms.Form):
    title = forms.CharField()


@ENTRIES
@pytest.mark.parametrize("answers", [True, False], ids=["answered", "left-out"])
def test_a_validator_field_an_untyped_input_data_may_fill(
    ada: Any, entry: Any, answers: bool
) -> None:
    # Relaxed at step one, and the Validator refuses it if nobody filled it,
    # which is where a Validator field is already refused.
    service = Record()
    spec = ServiceSpec(
        service=service,
        permissions=OPEN,
        validator=FormValidator(_TitleForm),
        input_data=_untyped({"title": "server's"} if answers else {}, []),
    )
    if answers:
        entry(spec, principal=ada, arguments={})
        assert service.calls[0]["data"] == {"title": "server's"}
        return
    with pytest.raises(InvalidArguments) as caught:
        entry(spec, principal=ada, arguments={})
    assert caught.value.detail == {"title": REQUIRED}


def test_a_many_row_field_an_untyped_input_data_may_fill_is_relaxed_in_each_row(ada: Any) -> None:
    service = Record()
    spec = ServiceSpec(
        service=service,
        permissions=OPEN,
        many=True,
        validator=FormValidator(_TitleForm),
        input_data=_untyped({"title": "server's"}, []),
    )
    dispatch(spec, principal=ada, arguments={"items": [{}, {"title": "caller's"}]})
    assert service.calls[0]["data"] == [{"title": "server's"}, {"title": "server's"}]


def test_a_many_spec_s_read_an_untyped_provider_may_fill(ada: Any) -> None:
    service = Record()
    spec = ServiceSpec(
        service=service,
        permissions=OPEN,
        many=True,
        validator=FormValidator(_TitleForm),
        reads=_project(),
        kwargs=_untyped({}, []),
    )
    with pytest.raises(InvalidArguments) as caught:
        dispatch(spec, principal=ada, arguments={"items": [{"title": "a"}]})
    assert caught.value.detail == {"project_pk": REQUIRED}
    dispatch(spec, principal=ada, arguments={"items": [{"title": "a"}], "project_pk": 4})
    assert service.calls[0]["project_pk"] == 4


@pytest.mark.parametrize(
    "seat",
    ["service", "selector-spec", "target-selector"],
)
@pytest.mark.parametrize("declined", [UNSET, None], ids=["unset", "omitted"])
def test_a_required_read_the_provider_declines_is_refused_though_its_callable_has_a_default(
    ada: Any, seat: str, declined: Any
) -> None:
    # A filled key the provider declines meets the seat's rule too: the
    # callable's own default never stands in for a read declared required.
    calls: list[None] = []
    ran: list[Any] = []

    def run(*, project_pk: int = 0) -> list[Any]:
        ran.append(project_pk)
        return []

    provider = _filled(declined, calls)
    if seat == "service":
        spec: Any = ServiceSpec(service=run, permissions=OPEN, reads=_project(), kwargs=provider)
    elif seat == "selector-spec":
        spec = SelectorSpec(
            kind=LIST, selector=run, permissions=OPEN, reads=_project(), kwargs=provider
        )
    else:
        target = SelectorSpec(kind=LIST, selector=run, reads=_project(), kwargs=provider)
        spec = ServiceSpec(service=Record(), permissions=OPEN, collection_selector_spec=target)
    with pytest.raises(InvalidArguments) as caught:
        dispatch(spec, principal=ada, arguments={"project_pk": 99})
    assert caught.value.detail == {"project_pk": REQUIRED}
    assert calls == [None]
    assert ran == []


def test_an_optional_read_nobody_fills_is_not_refused_at_the_seat(ada: Any) -> None:
    # Holds the seat's ``required`` conjunct: without it every absent read is refused.
    service = Record()
    spec = ServiceSpec(
        service=service,
        permissions=OPEN,
        reads=Parameters.of(Parameter("project_pk", "integer")),
        kwargs=_untyped({}, []),
    )
    dispatch(spec, principal=ada, arguments={})
    assert "project_pk" not in service.calls[0]


def test_a_required_read_declaring_a_default_is_not_refused_at_the_seat(ada: Any) -> None:
    # Holds the seat's ``default`` conjunct, as ``check_arguments`` reads one:
    # the shape check lets it through absent, and so does the seat.
    service = Record()
    spec = ServiceSpec(service=service, permissions=OPEN, reads=_project(default=3))
    dispatch(spec, principal=ada, arguments={})
    assert "project_pk" not in service.calls[0]


def test_check_call_relaxes_a_may_fill_read(ada: Any) -> None:
    spec = ServiceSpec(
        service=Record(), permissions=OPEN, reads=_project(), kwargs=_declining(UNSET, [])
    )
    checked, _ = check_call(spec, principal=ada, arguments={})
    assert checked == {}


def test_bind_arguments_relaxes_a_may_fill_read(ada: Any) -> None:
    spec = SelectorSpec(
        kind=LIST,
        selector=lambda **_: [],
        permissions=OPEN,
        reads=_project(),
        kwargs=_untyped({}, []),
    )
    assert bind_arguments(spec, {}, principal=ada) == {}


def test_check_server_arguments_lets_a_read_an_untyped_provider_reaches_be_withheld() -> None:
    # The selector declares the read with no default, which alone would
    # refuse withholding it: the provider may fill it, so a call can do without.
    def selector(*, project_pk: int) -> list[Any]:
        return []

    spec = SelectorSpec(
        kind=LIST, selector=selector, permissions=OPEN, reads=_project(), kwargs=_untyped({}, [])
    )
    check_server_arguments(spec, ServerArguments(withheld=frozenset({"project_pk"})))


def test_check_server_arguments_lets_a_field_an_untyped_input_data_reaches_be_withheld() -> None:
    spec = ServiceSpec(
        service=Record(),
        permissions=OPEN,
        validator=FormValidator(_TitleForm),
        input_data=_untyped({}, []),
    )
    check_server_arguments(spec, ServerArguments(withheld=frozenset({"title"})))


def test_check_server_arguments_still_refuses_withholding_a_many_read_a_row_field_shares() -> None:
    # ``input_data`` reaches each row's ``project_pk``, never the top-level
    # read of that name, which the shape check still demands.
    class _ProjectForm(forms.Form):
        project_pk = forms.IntegerField()

    spec = ServiceSpec(
        service=Record(),
        permissions=OPEN,
        many=True,
        validator=FormValidator(_ProjectForm),
        reads=_project(),
        input_data=_untyped({}, []),
    )
    with pytest.raises(ImproperlyConfigured, match="which no call could then do without"):
        check_server_arguments(spec, ServerArguments(withheld=frozenset({"project_pk"})))


# --- seat (b): a registered seed fills a reflected read ----------------------------------


@ENTRIES
@POLICIES
def test_a_reflected_read_a_registered_seed_is_named_like_is_the_seed_s(
    ada: Any, entry: Any, policy: UnknownArguments
) -> None:
    spec = SelectorSpec(
        kind=LIST,
        selector=lambda *, tenant: [tenant],
        permissions=OPEN,
        reads=_tenant(required=True, reflected=True),
    )
    result = entry(
        spec, principal=ada, arguments={}, pool_seeds=TENANT_SEEDS, unknown_arguments=policy
    )
    assert result.value == [SEEDED]


@ENTRIES
@pytest.mark.parametrize("seat", ["selector-spec", "target-selector", "service"])
def test_a_caller_s_value_for_a_reflected_read_never_reaches_its_callable(
    ada: Any, entry: Any, seat: str
) -> None:
    # The read is no argument of the call: unknown under REJECT, dropped under
    # IGNORE, and never merged over the seed.
    seen: list[Any] = []

    def selector(*, tenant: str) -> list[Any]:
        seen.append(tenant)
        return []

    service = Record()
    reads = _tenant(required=True, reflected=True)
    if seat == "selector-spec":
        spec: Any = SelectorSpec(kind=LIST, selector=selector, permissions=OPEN, reads=reads)
    elif seat == "target-selector":
        target = SelectorSpec(kind=LIST, selector=selector, reads=reads)
        spec = ServiceSpec(service=service, permissions=OPEN, collection_selector_spec=target)
    else:
        spec = ServiceSpec(service=service, permissions=OPEN, reads=reads)
    arguments = {"tenant": "victim-corp"}
    with pytest.raises(InvalidArguments) as caught:
        entry(spec, principal=ada, arguments=arguments, pool_seeds=TENANT_SEEDS)
    assert caught.value.detail == {"tenant": ["Unknown argument."]}
    entry(
        spec,
        principal=ada,
        arguments=arguments,
        pool_seeds=TENANT_SEEDS,
        unknown_arguments=UnknownArguments.IGNORE,
    )
    received = [call["tenant"] for call in service.calls] if seat == "service" else seen
    assert received == [SEEDED]


async def test_an_async_selector_s_reflected_read_is_the_seed_s(ada: Any) -> None:
    async def selector(*, tenant: str) -> list[Any]:
        return [tenant]

    spec = SelectorSpec(
        kind=LIST, selector=selector, permissions=OPEN, reads=_tenant(reflected=True)
    )
    result = await adispatch(spec, principal=ada, arguments={}, pool_seeds=TENANT_SEEDS)
    assert result.value == [SEEDED]


@pytest.mark.parametrize("marked", [True, False], ids=["reflected", "unmarked"])
def test_resolve_target_and_check_call_split_as_dispatch_does(ada: Any, marked: bool) -> None:
    note = Note.objects.create(owner=ada, title="Row")

    def by_pk(*, pk: int, tenant: str) -> Any:
        assert tenant == SEEDED
        return Note.objects.filter(pk=pk)

    target = SelectorSpec(
        kind=RETRIEVE,
        selector=by_pk,
        reads=PK + _tenant(reflected=marked),
    )
    spec = ServiceSpec(service=Record(), permissions=OPEN, instance_selector_spec=target)
    arguments = {"pk": note.pk}
    if not marked:
        for call in (resolve_target, check_call):
            with pytest.raises(ImproperlyConfigured, match=r"\['tenant'\], which a registered"):
                call(spec, principal=ada, arguments=arguments, pool_seeds=TENANT_SEEDS)
        return
    found, _ = resolve_target(spec, principal=ada, arguments=arguments, pool_seeds=TENANT_SEEDS)
    assert found == note
    checked, _ = check_call(spec, principal=ada, arguments=arguments, pool_seeds=TENANT_SEEDS)
    assert checked == arguments


def test_a_reflected_shape_named_like_a_registered_seed_is_still_refused(ada: Any) -> None:
    # Only a read is filled by a seed; a shape is the presenter's argument.
    spec = SelectorSpec(
        kind=LIST,
        selector=lambda **_: [],
        permissions=OPEN,
        shapes=_tenant(reflected=True),
    )
    with pytest.raises(ImproperlyConfigured, match=r"\['tenant'\], which a registered"):
        dispatch(spec, principal=ada, arguments={}, pool_seeds=TENANT_SEEDS)


def test_a_reflected_read_and_a_field_of_two_seeds_names_each_answer_by_their_own_seat(
    ada: Any,
) -> None:
    seeds = TENANT_SEEDS.extend(region=lambda: "seeded-region")
    service = Record()
    spec = ServiceSpec(
        service=service,
        permissions=OPEN,
        reads=_tenant(required=True, reflected=True),
        validator=Fields(Parameter("region", "string", required=True)),
    )
    with pytest.raises(InvalidArguments) as caught:
        dispatch(spec, principal=ada, arguments={"tenant": "t", "region": "r"}, pool_seeds=seeds)
    assert caught.value.detail == {"tenant": ["Unknown argument."]}
    dispatch(spec, principal=ada, arguments={"region": "caller's"}, pool_seeds=seeds)
    assert service.calls[0]["tenant"] == SEEDED
    assert service.calls[0]["region"] == "seeded-region"
    assert service.calls[0]["data"] == {"region": "caller's"}


class TestServerArgumentsOnAReflectedRead:
    FILLS = "which a registered pool seed fills on every call"

    @pytest.mark.parametrize(
        "server",
        [
            ServerArguments(values={"tenant": "acme"}),
            ServerArguments(withheld=frozenset({"tenant"})),
        ],
        ids=["bound", "withheld"],
    )
    def test_binding_or_withholding_it_is_refused_as_doing_nothing(
        self, server: ServerArguments
    ) -> None:
        spec = SelectorSpec(
            kind=LIST, selector=lambda **_: [], permissions=OPEN, reads=_tenant(reflected=True)
        )
        with pytest.raises(ImproperlyConfigured) as caught:
            check_server_arguments(spec, server, pool_seeds=TENANT_SEEDS)
        assert self.FILLS in str(caught.value)
        assert "rename the parameter" not in str(caught.value)

    def test_an_unmarked_read_is_still_refused_as_dispatch_refuses_it(self) -> None:
        spec = SelectorSpec(
            kind=LIST,
            selector=lambda **_: [],
            permissions=OPEN,
            reads=_tenant(reflected=True) + Parameters.of(Parameter("region", "string")),
        )
        seeds = TENANT_SEEDS.extend(region=lambda: "r")
        with pytest.raises(ImproperlyConfigured) as caught:
            check_server_arguments(
                spec, ServerArguments(values={"tenant": "a", "region": "b"}), pool_seeds=seeds
            )
        assert "region" in str(caught.value)
        assert "tenant" not in str(caught.value)
        assert self.FILLS not in str(caught.value)


def test_check_requested_input_refuses_asking_for_a_reflected_read() -> None:
    spec = SelectorSpec(
        kind=LIST, selector=lambda **_: [], permissions=OPEN, reads=_tenant(reflected=True)
    )
    schema = {"tenant": {"type": "string"}}
    check_requested_input(spec, schema)
    with pytest.raises(ImproperlyConfigured, match="fills it"):
        check_requested_input(spec, schema, pool_seeds=TENANT_SEEDS)


# --- seat (c): a Validator field named like a registered seed ----------------------------


def _field_spec(service: Any = None, **kwargs: Any) -> ServiceSpec:
    return ServiceSpec(
        service=Record() if service is None else service,
        permissions=OPEN,
        validator=Fields(Parameter("tenant", "string", required=True)),
        **kwargs,
    )


@ENTRIES
@POLICIES
def test_a_field_named_like_a_registered_seed_validates_into_data_and_the_pool_keeps_the_seed(
    ada: Any, entry: Any, policy: UnknownArguments
) -> None:
    service = Record()
    validator = Fields(Parameter("tenant", "string", required=True))
    spec = ServiceSpec(service=service, permissions=OPEN, validator=validator)
    entry(
        spec,
        principal=ada,
        arguments={"tenant": "caller's"},
        pool_seeds=TENANT_SEEDS,
        unknown_arguments=policy,
    )
    assert validator.calls == [{"tenant": "caller's"}]
    # The base ``validated()`` hands one dict as ``values`` and ``data``, so
    # ``data`` keeping the field is what shows the spread took a copy.
    assert service.calls[0]["data"] == {"tenant": "caller's"}
    assert service.calls[0]["tenant"] == SEEDED


async def test_an_async_service_s_seed_named_field_reaches_data_alone(ada: Any) -> None:
    seen: list[tuple[Any, Any]] = []

    async def service(*, tenant: str, data: Any) -> None:
        seen.append((tenant, data))

    spec = _field_spec(service)
    await adispatch(spec, principal=ada, arguments={"tenant": "caller's"}, pool_seeds=TENANT_SEEDS)
    assert seen == [(SEEDED, {"tenant": "caller's"})]


def test_a_required_seed_named_field_left_out_is_refused_at_the_shape_check(ada: Any) -> None:
    spec = ServiceSpec(
        service=Record(),
        permissions=[Refuse()],
        validator=Fields(Parameter("tenant", "string", required=True)),
    )
    with pytest.raises(InvalidArguments) as caught:
        dispatch(spec, principal=ada, arguments={}, pool_seeds=TENANT_SEEDS)
    assert caught.value.detail == {"tenant": REQUIRED}


class _ServerTenant(TypedDict):
    tenant: str


def _server_tenant() -> _ServerTenant:
    return {"tenant": "server's"}


def test_input_data_filling_a_seed_named_field_reaches_data_and_never_the_pool(ada: Any) -> None:
    service = Record()
    spec = _field_spec(service, input_data=_server_tenant)
    dispatch(spec, principal=ada, arguments={}, pool_seeds=TENANT_SEEDS)
    assert service.calls[0]["data"] == {"tenant": "server's"}
    assert service.calls[0]["tenant"] == SEEDED


def test_a_reflected_validator_field_is_still_the_caller_s(ada: Any) -> None:
    # Seat (c) reads no marker: a Validator field is never filled by the seed.
    service = Record()
    spec = ServiceSpec(
        service=service,
        permissions=OPEN,
        validator=Fields(Parameter("tenant", "string", required=True, reflected=True)),
    )
    dispatch(spec, principal=ada, arguments={"tenant": "caller's"}, pool_seeds=TENANT_SEEDS)
    assert service.calls[0]["data"] == {"tenant": "caller's"}
    assert service.calls[0]["tenant"] == SEEDED


def test_a_many_row_field_named_like_a_registered_seed_stays_in_its_row(ada: Any) -> None:
    service = Record()
    spec = ServiceSpec(
        service=service,
        permissions=OPEN,
        many=True,
        validator=Fields(Parameter("tenant", "string", required=True)),
    )
    dispatch(
        spec, principal=ada, arguments={"items": [{"tenant": "row's"}]}, pool_seeds=TENANT_SEEDS
    )
    assert service.calls[0]["tenant"] == SEEDED
    assert service.calls[0]["data"] == [{"tenant": "row's"}]


def test_an_overlay_key_named_like_the_seed_is_still_refused_beside_such_a_field(ada: Any) -> None:
    # An ``UNSET`` entry, which ``refuse_overlaid_parameters`` lets through for
    # a declared parameter: the field's value is not spread, so the entry
    # reaches the overlay's own refusal of a seed's name, as on a spec
    # declaring no such field, rather than being dropped beneath it.
    spec = _field_spec()
    with pytest.raises(ImproperlyConfigured) as caught:
        dispatch(
            spec,
            principal=ada,
            arguments={"tenant": "caller's"},
            pool_seeds=TENANT_SEEDS,
            extra_kwargs={"tenant": UNSET},
        )
    assert str(caught.value).startswith("extra_kwargs returned the key(s) ['tenant']")


def test_check_call_passes_a_spec_with_such_a_field(ada: Any) -> None:
    # resolve_target's twin is
    # test_a_validator_field_a_registered_seed_names_resolves_as_dispatch_runs_it.
    note = Note.objects.create(owner=ada, title="Row")
    spec = _field_spec(
        instance_selector_spec=SelectorSpec(kind=RETRIEVE, selector=note_by_pk, reads=PK)
    )
    checked, _ = check_call(
        spec, principal=ada, arguments={"pk": note.pk, "tenant": "t"}, pool_seeds=TENANT_SEEDS
    )
    assert checked == {"pk": note.pk, "tenant": "t"}


def test_check_server_arguments_binds_such_a_field() -> None:
    check_server_arguments(
        _field_spec(), ServerArguments(values={"tenant": "acme"}), pool_seeds=TENANT_SEEDS
    )


def test_server_owned_keys_leaves_such_a_field_out_and_a_service_may_ask_for_it() -> None:
    spec = _field_spec()
    assert "tenant" not in server_owned_keys(spec, pool_seeds=TENANT_SEEDS)
    check_requested_input(spec, {"tenant": {"type": "string"}}, pool_seeds=TENANT_SEEDS)


@pytest.mark.parametrize(
    "spec",
    [
        pytest.param(
            lambda: ServiceSpec(
                service=Record(),
                many=True,
                validator=Fields(Parameter("tenant", "string")),
            ),
            id="a-many-row-field",
        ),
        pytest.param(lambda: ServiceSpec(service=Record()), id="no-validator"),
        pytest.param(
            lambda: SelectorSpec(kind=LIST, selector=lambda **_: []), id="a-selector-spec"
        ),
    ],
)
def test_server_owned_keys_still_lists_a_seed_no_top_level_field_takes(
    spec: Callable[[], Any],
) -> None:
    assert "tenant" in server_owned_keys(spec(), pool_seeds=TENANT_SEEDS)


def test_server_owned_keys_still_lists_a_dispatcher_name_a_field_takes() -> None:
    # Only a registered seed's name leaves the set: ``parameters()`` refuses a
    # field named like one of the dispatcher's own when the call assembles it,
    # and this reads the Validator without assembling.
    spec = ServiceSpec(service=Record(), validator=Fields(Parameter("user", "string")))
    assert "user" in server_owned_keys(spec, pool_seeds=TENANT_SEEDS)
