from __future__ import annotations

import copy
import importlib
from collections.abc import Callable
from types import MappingProxyType
from typing import Any

import pytest
from asgiref.sync import async_to_sync

from django_service_specs.authorization.unrestricted import Unrestricted
from django_service_specs.dispatch.adispatch import adispatch
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.build_call_context import build_call_context
from django_service_specs.types.call_transport import call_transport
from django_service_specs.types.transport_key import TRANSPORT_KEY
from tests.dispatch.utils import make_user

_STANDARD = ("request", "view", "format", "action")


class _Marker:
    """A value nothing could have made up, so ``is`` tells it from any other."""

    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:
        return f"<{self.name}>"


def test_every_standard_entry_is_there_and_none_where_nothing_gave_one() -> None:
    # The four keys are always written.
    assert build_call_context("cli") == {
        "request": None,
        "view": None,
        "format": None,
        "action": None,
        TRANSPORT_KEY: "cli",
    }


def test_each_argument_lands_under_its_own_key() -> None:
    request, view = _Marker("request"), _Marker("view")
    context = build_call_context("rest", request=request, view=view, format="json", action="list")
    assert context["request"] is request
    assert context["view"] is view
    assert (context["format"], context["action"], context[TRANSPORT_KEY]) == (
        "json",
        "list",
        "rest",
    )


def test_the_stamp_is_the_string_it_was_handed() -> None:
    # Not a closed set: a third-party transport's own string goes in unconverted.
    context = build_call_context("worker")
    assert call_transport(context) == "worker"
    assert type(context[TRANSPORT_KEY]) is str


def test_base_s_entries_are_kept_over_the_none_defaults() -> None:
    request = _Marker("request")
    context = build_call_context("agent", base={"request": request, "client": "back-office"})
    assert context["request"] is request
    assert context["client"] == "back-office"
    assert (context["view"], context["format"], context["action"]) == (None, None, None)


@pytest.mark.parametrize("name", _STANDARD)
def test_an_argument_wins_over_base_s_entry(name: str) -> None:
    # Parametrized over all four: one comprehension is one coverage arc.
    given = _Marker(f"given {name}")
    context = build_call_context("agent", base={name: _Marker(f"base {name}")}, **{name: given})
    assert context[name] is given


@pytest.mark.parametrize("name", _STANDARD)
def test_a_none_argument_leaves_base_s_entry(name: str) -> None:
    # ``None`` is "not given": it never clears what ``base`` carried.
    kept = _Marker(f"base {name}")
    context = build_call_context("agent", base={name: kept}, **{name: None})
    assert context[name] is kept


def test_the_stamp_wins_over_a_transport_base_carried() -> None:
    # A run's dict handed in as ``base`` may name a transport of its own.
    context = build_call_context("agent", base={TRANSPORT_KEY: "rest"})
    assert context[TRANSPORT_KEY] == "agent"


def test_base_is_never_mutated() -> None:
    request = _Marker("request")
    base: dict[str, Any] = {"request": request, TRANSPORT_KEY: "rest", "client": "back-office"}
    before = copy.copy(base)

    context = build_call_context("agent", base=base, view=_Marker("view"), action="archive")
    context["archived"] = [1]

    assert base == before
    assert base[TRANSPORT_KEY] == "rest"
    assert base["request"] is request
    assert context is not base


def test_base_is_copied_shallowly_so_a_request_is_the_request() -> None:
    request = _Marker("request")
    context = build_call_context("agent", base={"request": request})
    assert context["request"] is request


def test_a_read_only_base_is_accepted() -> None:
    base = MappingProxyType({"client": "back-office", TRANSPORT_KEY: "rest"})
    context = build_call_context("mcp", base=base)
    assert context == {
        "request": None,
        "view": None,
        "format": None,
        "action": None,
        "client": "back-office",
        TRANSPORT_KEY: "mcp",
    }


def test_each_call_returns_a_fresh_plain_dict_the_caller_may_change() -> None:
    # A per-request transport builds one dict and passes the same object to every callable.
    base = {"client": "back-office"}
    first = build_call_context("rest", base=base)
    second = build_call_context("rest", base=base)
    assert type(first) is dict
    assert first is not second
    first["archived"] = [1]
    assert "archived" not in second
    assert "archived" not in base


def test_it_is_exported_from_the_root_and_from_types() -> None:
    assert importlib.import_module("django_service_specs").build_call_context is build_call_context
    assert (
        importlib.import_module("django_service_specs.types").build_call_context
        is build_call_context
    )


_ENTRIES = pytest.mark.parametrize(
    "entry", [dispatch, async_to_sync(adispatch)], ids=["sync", "async"]
)


@pytest.mark.django_db
class TestDispatchedWithIt:
    """A context the builder made binds as any transport's dict binds."""

    @_ENTRIES
    def test_a_callable_declaring_request_is_handed_none_as_with_no_key(
        self, entry: Callable[..., Any]
    ) -> None:
        seen: list[Any] = []

        def service(*, request: Any, view: Any) -> str:
            seen.append((request, view))
            return "ran"

        spec = ServiceSpec(service=service, permissions=[Unrestricted()])
        ada = make_user("ada")
        built = entry(spec, principal=ada, arguments={}, call_context=build_call_context("cli"))
        bare = entry(spec, principal=ada, arguments={}, call_context={TRANSPORT_KEY: "cli"})
        assert (built.value, bare.value) == ("ran", "ran")
        assert seen == [(None, None), (None, None)]

    @_ENTRIES
    def test_the_request_it_was_handed_reaches_the_callable(
        self, entry: Callable[..., Any]
    ) -> None:
        seen: list[Any] = []
        request = _Marker("request")

        def service(*, request: Any, call_context: dict[str, Any]) -> None:
            seen.append((request, call_transport(call_context)))

        spec = ServiceSpec(service=service, permissions=[Unrestricted()])
        entry(
            spec,
            principal=make_user("ada"),
            arguments={},
            call_context=build_call_context("rest", request=request),
        )
        assert seen == [(request, "rest")]
        assert seen[0][0] is request
