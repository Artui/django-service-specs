from __future__ import annotations

from types import MappingProxyType
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.db.models import QuerySet

from django_service_specs.authorization.permission_check import PermissionCheck
from django_service_specs.dispatch.adispatch import adispatch
from django_service_specs.dispatch.apply_server_arguments import apply_server_arguments
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.parameters import Parameter, Parameters
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.types.selector_kind import SelectorKind
from django_service_specs.types.server_arguments import ServerArguments
from django_service_specs.types.unknown_arguments import UnknownArguments
from tests.dispatch.utils import OPEN, make_user
from tests.dispatch_app.models import Note

pytestmark = pytest.mark.django_db

ABSENT = object()

READS = Parameters.of(
    Parameter("project_pk", "integer", required=True),
    Parameter("draw_request_pk", "integer"),
    # Declared apart from the selector's own ``"open"``, so a test can tell
    # which of the two answers a withheld name.
    Parameter("status", "string", default="any"),
)

# A per-caller scope: the project is the server's, and the sibling capture the
# model could otherwise reach for is withheld, so the selector sees only the project.
SCOPE = ServerArguments(values={"project_pk": 7}, withheld=frozenset({"draw_request_pk"}))


class Seen:
    """What the selector and the permission check were handed, call by call."""

    def __init__(self) -> None:
        self.selector: list[dict[str, Any]] = []
        self.permission: list[dict[str, Any]] = []


def scoped(seen: Seen) -> SelectorSpec:
    def notes_in(
        *, project_pk: Any = ABSENT, draw_request_pk: Any = ABSENT, status: str = "open"
    ) -> QuerySet[Note]:
        seen.selector.append(
            {"project_pk": project_pk, "draw_request_pk": draw_request_pk, "status": status}
        )
        return Note.objects.none()

    class Recording(PermissionCheck):
        def has_permission(self, principal: Any, spec: Any, *, arguments: Any) -> bool:
            seen.permission.append(dict(arguments))
            return True

    return SelectorSpec(
        kind=SelectorKind.LIST, selector=notes_in, reads=READS, permissions=(Recording(),)
    )


@pytest.fixture
def ada() -> Any:
    return make_user("ada")


def run(spec: SelectorSpec, ada: Any, arguments: dict[str, Any], server: ServerArguments) -> None:
    dispatch(
        spec,
        principal=ada,
        arguments=apply_server_arguments(spec, arguments, server),
        unknown_arguments=UnknownArguments.REJECT,
    )


# --- the value it returns ----------------------------------------------------------------


def test_a_bound_value_outranks_the_caller_s() -> None:
    # Fails if the overlay runs before the drop: the bound value is dropped with
    # the caller's, and the call goes out with no project at all.
    applied = apply_server_arguments(
        scoped(Seen()),
        {"project_pk": 99, "status": "closed"},
        ServerArguments(values={"project_pk": 7}),
    )
    assert applied == {"project_pk": 7, "status": "closed"}


def test_a_withheld_name_is_dropped_whatever_the_caller_sent() -> None:
    applied = apply_server_arguments(
        scoped(Seen()), {"draw_request_pk": "null", "status": "closed"}, SCOPE
    )
    assert applied == {"project_pk": 7, "status": "closed"}


def test_a_key_the_binding_does_not_name_is_left_as_sent() -> None:
    applied = apply_server_arguments(scoped(Seen()), {"rogue": 1, "status": 3}, SCOPE)
    assert applied == {"rogue": 1, "status": 3, "project_pk": 7}


def test_a_binding_that_only_withholds_reads_no_declaration() -> None:
    # Nothing to check a value against, so the spec's parameters are not
    # assembled on the call; the drop alone is the whole of it.
    class Unread:
        def as_kernel_spec(self) -> SelectorSpec:
            raise AssertionError("a withholding binding read the spec")

    sent = {"draw_request_pk": "null", "status": "closed"}
    applied = apply_server_arguments(
        Unread(), sent, ServerArguments(withheld=frozenset({"draw_request_pk"}))
    )
    assert applied == {"status": "closed"}


def test_the_caller_s_arguments_are_not_changed() -> None:
    sent = MappingProxyType({"project_pk": 99, "draw_request_pk": 5})
    applied = apply_server_arguments(scoped(Seen()), sent, SCOPE)
    assert dict(sent) == {"project_pk": 99, "draw_request_pk": 5}
    assert applied == {"project_pk": 7}
    assert type(applied) is dict


def test_a_bound_value_is_handed_on_as_the_shape_check_reads_it() -> None:
    # Checked against its own declaration, as dispatch would check it: an
    # integral float declared an integer is the int.
    applied = apply_server_arguments(
        scoped(Seen()), {}, ServerArguments(values={"project_pk": 7.0})
    )
    assert applied == {"project_pk": 7}
    assert type(applied["project_pk"]) is int


# --- a bound value that fails its own declaration ------------------------------------------


def test_a_bound_value_that_fails_its_declaration_is_the_server_s_mistake() -> None:
    # Not InvalidArguments: a client refusal would ask the caller to fix a
    # value it never sent and cannot see.
    server = ServerArguments(values={"project_pk": "seven", "status": "closed"})
    with pytest.raises(ImproperlyConfigured) as raised:
        apply_server_arguments(scoped(Seen()), {"project_pk": 7}, server)
    assert not isinstance(raised.value, InvalidArguments)
    assert isinstance(raised.value.__cause__, InvalidArguments)
    assert raised.value.__cause__.detail == {"project_pk": ["Expected an integer."]}
    assert "'project_pk'" in str(raised.value)
    assert "status" not in str(raised.value)
    # Named, so a transport over many tools can say which one is wrong.
    assert "SelectorSpec for scoped.<locals>.notes_in" in str(raised.value)


def test_an_undeclared_bound_name_is_the_server_s_mistake_at_the_call_too() -> None:
    # ``check_server_arguments`` refuses it at construction; a transport that
    # skipped that check is still not handed a key no parameter declares.
    with pytest.raises(ImproperlyConfigured) as raised:
        apply_server_arguments(scoped(Seen()), {}, ServerArguments(values={"rogue": 1}))
    assert "'rogue'" in str(raised.value)


# --- composed with dispatch, rule by rule ----------------------------------------------------


def test_a_malformed_value_for_a_withheld_name_never_reaches_the_shape_check(ada: Any) -> None:
    # The drop runs first, so a value the model sends for a name it was never
    # shown cannot refuse the call: under REJECT, ``"null"`` for an integer.
    seen = Seen()
    run(scoped(seen), ada, {"project_pk": "null", "draw_request_pk": "null"}, SCOPE)
    assert seen.selector == [{"project_pk": 7, "draw_request_pk": ABSENT, "status": "open"}]


def test_reject_still_refuses_a_key_nobody_declared(ada: Any) -> None:
    # A bound or withheld name stays declared, so REJECT never reaches it; it
    # still closes the set for everything else.
    seen = Seen()
    with pytest.raises(InvalidArguments) as refused:
        run(scoped(seen), ada, {"draw_request_pk": 5, "rogue": 1}, SCOPE)
    assert refused.value.detail == {"rogue": ["Unknown argument."]}
    assert seen.selector == []


def test_a_bound_value_satisfies_a_required_parameter(ada: Any) -> None:
    seen = Seen()
    run(scoped(seen), ada, {}, SCOPE)
    assert seen.selector == [{"project_pk": 7, "draw_request_pk": ABSENT, "status": "open"}]


def test_a_bound_value_replaces_a_read_s_default(ada: Any) -> None:
    seen = Seen()
    server = ServerArguments(values={"project_pk": 7, "status": "closed"})
    run(scoped(seen), ada, {"status": "open"}, server)
    assert seen.selector[0]["status"] == "closed"


def test_a_withheld_name_falls_back_to_its_default(ada: Any) -> None:
    # Dispatch reports a declared default and does not apply it, so the read is
    # absent and the selector's own default answers, as for any omitted read:
    # ``"open"``, never the declared ``"any"``.
    seen = Seen()
    server = ServerArguments(values={"project_pk": 7}, withheld=frozenset({"status"}))
    run(scoped(seen), ada, {"status": "closed"}, server)
    assert seen.selector[0]["status"] == "open"


def test_the_permission_check_sees_the_bound_value(ada: Any) -> None:
    # The values are in ``arguments`` before dispatch's first step, so the
    # class-level check reads the same project the selector does.
    seen = Seen()
    run(scoped(seen), ada, {"project_pk": 99, "draw_request_pk": 5}, SCOPE)
    assert seen.permission == [{"project_pk": 7}]
    assert seen.selector[0]["project_pk"] == 7


def test_a_kwargs_provider_sees_the_bound_value(ada: Any) -> None:
    # A provider declaring a read receives it from the same arguments the
    # selector does, so it reads the server's value and not the caller's.
    provided: list[Any] = []

    def scope(*, project_pk: int) -> dict[str, Any]:
        provided.append(project_pk)
        return {}

    def notes_in(*, project_pk: int) -> QuerySet[Note]:
        return Note.objects.none()

    spec = SelectorSpec(
        kind=SelectorKind.LIST,
        selector=notes_in,
        reads=READS,
        kwargs=scope,
        permissions=OPEN,
    )
    run(spec, ada, {"project_pk": 99}, SCOPE)
    assert provided == [7]


async def test_adispatch_answers_as_dispatch_does(ada: Any) -> None:
    # The helpers are synchronous and shared: one applied mapping, either entry point.
    sync_seen, async_seen = Seen(), Seen()
    sent = {"project_pk": "null", "draw_request_pk": "null", "status": "closed"}
    run(scoped(sync_seen), ada, sent, SCOPE)
    spec = scoped(async_seen)
    await adispatch(
        spec,
        principal=ada,
        arguments=apply_server_arguments(spec, sent, SCOPE),
        unknown_arguments=UnknownArguments.REJECT,
    )
    assert async_seen.selector == sync_seen.selector
    assert async_seen.permission == sync_seen.permission
    assert async_seen.selector == [{"project_pk": 7, "draw_request_pk": ABSENT, "status": "closed"}]
