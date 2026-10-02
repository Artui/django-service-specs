"""``adispatch``: dispatch's steps, counted in executor hops.

Every test here reads rows on the executor thread, whose connection is not the
test's, so each runs with ``transaction=True``: rows written inside the
ordinary test transaction would be invisible to it. Any query that strays onto
the event loop raises ``SynchronousOnlyOperation``, so a test passing is also
evidence that nothing did.
"""

from __future__ import annotations

import asyncio
import importlib
from collections.abc import Callable, Mapping
from typing import Any

import pytest
from asgiref.sync import sync_to_async
from django.db.models import Q

from django_service_specs.authorization.grant import Grant
from django_service_specs.authorization.not_permitted import NotPermitted
from django_service_specs.authorization.principal_unavailable import PrincipalUnavailable
from django_service_specs.dispatch.adispatch import adispatch
from django_service_specs.dispatch.dispatch_result import DispatchResult
from django_service_specs.services.action_unavailable import ActionUnavailable
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.affordance import Affordance
from tests.dispatch.utils import (
    OPEN,
    PK,
    OwnerOnly,
    Record,
    Refuse,
    Titled,
    make_user,
    note_by_pk,
    notes_of,
)
from tests.dispatch_app.models import Note

LIST = SelectorKind.LIST
RETRIEVE = SelectorKind.RETRIEVE

pytestmark = pytest.mark.django_db(transaction=True)

# By import path, because the package re-exports the function under the
# module's own name, and attribute access on the package finds the function.
_module = importlib.import_module("django_service_specs.dispatch.adispatch")


@pytest.fixture
def ada() -> Any:
    return make_user("ada")


@pytest.fixture
def bob() -> Any:
    return make_user("bob")


@pytest.fixture
def hops(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every executor hop ``adispatch`` itself makes, by the function it hopped with."""
    made: list[str] = []

    def counted(fn: Callable[..., Any], *, thread_sensitive: bool) -> Any:
        assert thread_sensitive is True
        made.append(fn.__name__)
        return sync_to_async(fn, thread_sensitive=True)

    monkeypatch.setattr(_module, "sync_to_async", counted)
    return made


class Boom(Exception):
    """Raised by a service after it wrote, to see whether the write survives."""


async def _create(**fields: Any) -> Note:
    return await Note.objects.acreate(**fields)


# --- Who is acting -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "who", [{}, {"principal": object(), "principal_id": 1}], ids=["neither", "both"]
)
async def test_exactly_one_of_principal_and_principal_id_is_required(who: dict[str, Any]) -> None:
    spec = SelectorSpec(kind=LIST, selector=notes_of, permissions=OPEN)

    with pytest.raises(TypeError) as caught:
        await adispatch(spec, arguments={}, **who)

    assert str(caught.value) == "adispatch() takes exactly one of principal= and principal_id=."


async def test_principal_id_is_resolved_inside_the_one_hop(ada: Any, hops: list[str]) -> None:
    note = await _create(owner=ada, title="mine")
    spec = SelectorSpec(kind=LIST, selector=notes_of, permissions=OPEN)

    result = await adispatch(spec, principal_id=ada.pk, arguments={})

    assert [row.pk for row in await sync_to_async(list)(result.value)] == [note.pk]
    assert len(hops) == 1


async def test_a_principal_id_naming_nobody_is_refused(ada: Any) -> None:
    spec = SelectorSpec(kind=LIST, selector=notes_of, permissions=OPEN)

    with pytest.raises(PrincipalUnavailable) as caught:
        await adispatch(spec, principal_id=404, arguments={})

    assert caught.value.message == "No principal with identifier 404."


async def test_a_grant_never_covers_a_principal_resolved_here(ada: Any) -> None:
    spec = SelectorSpec(kind=LIST, selector=notes_of, permissions=OPEN)

    with pytest.raises(NotPermitted) as caught:
        await adispatch(spec, principal_id=ada.pk, arguments={}, grant=Grant(spec, ada))

    assert caught.value.message == "The grant does not cover this spec and principal."


async def test_a_refused_principal_learns_nothing_about_which_rows_exist(ada: Any) -> None:
    async def selector(*, pk: int) -> Any:
        raise AssertionError("resolved a row for a refused principal")

    spec = SelectorSpec(kind=RETRIEVE, selector=selector, reads=PK, permissions=[Refuse()])

    with pytest.raises(NotPermitted) as caught:
        await adispatch(spec, principal=ada, arguments={"pk": 1})

    assert caught.value.message == "Only editors may run this."


# --- A sync run joins the one hop --------------------------------------------------------


async def test_a_sync_selector_spec_costs_one_hop(ada: Any, hops: list[str]) -> None:
    note = await _create(owner=ada, title="mine")
    spec = SelectorSpec(kind=RETRIEVE, selector=note_by_pk, reads=PK, permissions=[OwnerOnly()])

    result = await adispatch(spec, principal=ada, arguments={"pk": note.pk})

    assert result == DispatchResult(kind="instance", value=note)
    assert len(hops) == 1


async def test_a_non_atomic_sync_service_costs_one_hop(ada: Any, hops: list[str]) -> None:
    note = await _create(owner=ada, title="old")

    def rename(*, instance: Note, title: str) -> Note:
        instance.title = title
        instance.save()
        return instance

    spec = ServiceSpec(
        service=rename,
        permissions=[OwnerOnly()],
        validator=Titled(),
        atomic=False,
        instance_selector_spec=SelectorSpec(kind=RETRIEVE, selector=note_by_pk, reads=PK),
        output_selector_spec=SelectorSpec(kind=LIST, selector=notes_of),
    )

    result = await adispatch(spec, principal=ada, arguments={"pk": note.pk, "title": "new"})

    assert result.kind == "list"
    assert [row.title for row in await sync_to_async(list)(result.value)] == ["new"]
    assert len(hops) == 1


async def test_an_atomic_async_service_joins_the_hop_and_rolls_back(
    ada: Any, hops: list[str]
) -> None:
    async def write_then_fail(*, user: Any) -> None:
        # Its own thread-sensitive ORM call comes back to the executor thread,
        # whose connection holds the transaction the bridge opened.
        await Note.objects.acreate(owner=user, title="half-done")
        raise Boom

    spec = ServiceSpec(service=write_then_fail, permissions=OPEN)

    with pytest.raises(Boom):
        await adispatch(spec, principal=ada, arguments={})

    assert await Note.objects.filter(title="half-done").aexists() is False
    assert len(hops) == 1


# --- A non-atomic async run is awaited on the loop ----------------------------------------


async def test_a_non_atomic_async_service_is_awaited_after_the_hop(
    ada: Any, hops: list[str]
) -> None:
    async def write_then_fail(*, user: Any, title: str) -> None:
        await Note.objects.acreate(owner=user, title=title)
        raise Boom

    spec = ServiceSpec(service=write_then_fail, permissions=OPEN, validator=Titled(), atomic=False)

    with pytest.raises(Boom):
        await adispatch(spec, principal=ada, arguments={"title": "kept"})

    # No transaction around it, so its write stands.
    assert await Note.objects.filter(title="kept").aexists() is True
    assert len(hops) == 1


async def test_a_non_atomic_async_service_s_result_needs_no_second_hop(
    ada: Any, hops: list[str]
) -> None:
    async def service(*, title: str) -> str:
        return f"async {title}"

    spec = ServiceSpec(service=service, permissions=OPEN, validator=Titled(), atomic=False)

    result = await adispatch(spec, principal=ada, arguments={"title": "t"})

    assert result == DispatchResult(
        kind="instance", value="async t", service_result="async t", data={"title": "t"}
    )
    assert len(hops) == 1


async def test_its_output_selector_takes_a_second_hop(ada: Any, hops: list[str]) -> None:
    async def service(*, user: Any, title: str) -> Note:
        return await Note.objects.acreate(owner=user, title=title)

    reread = Record(returns=None)

    def by_result(**pool: Any) -> Any:
        reread(**pool)
        return Note.objects.filter(pk=pool["result"].pk)

    spec = ServiceSpec(
        service=service,
        permissions=OPEN,
        validator=Titled(),
        atomic=False,
        output_selector_spec=SelectorSpec(kind=RETRIEVE, selector=by_result),
    )

    result = await adispatch(spec, principal=ada, arguments={"title": "made"})

    assert result.value.title == "made"
    assert result.value == result.service_result
    assert set(reread.calls[0]) == {"user", "progress", "result"}
    assert len(hops) == 2


async def test_a_non_atomic_async_service_s_missing_row_is_not_found(
    ada: Any, hops: list[str]
) -> None:
    async def service(*, instance: Note) -> None:
        raise AssertionError("ran without its row")

    spec = ServiceSpec(
        service=service,
        permissions=OPEN,
        atomic=False,
        instance_selector_spec=SelectorSpec(kind=RETRIEVE, selector=note_by_pk, reads=PK),
    )

    result = await adispatch(spec, principal=ada, arguments={"pk": 404})

    assert result == DispatchResult(kind="not_found")
    assert len(hops) == 1


async def test_an_async_selector_is_awaited_between_two_hops(ada: Any, hops: list[str]) -> None:
    note = await _create(owner=ada, title="mine")

    async def selector(*, pk: int) -> Any:
        # Unevaluated: collapsing it to its row is a query, and happens in the second hop.
        return Note.objects.filter(pk=pk)

    spec = SelectorSpec(kind=RETRIEVE, selector=selector, reads=PK, permissions=OPEN)

    result = await adispatch(spec, principal=ada, arguments={"pk": note.pk})

    assert result == DispatchResult(kind="instance", value=note)
    assert len(hops) == 2


async def test_an_async_selector_s_row_is_object_checked(ada: Any, bob: Any) -> None:
    theirs = await _create(owner=bob, title="theirs")

    async def selector(*, pk: int) -> Note:
        return await Note.objects.aget(pk=pk)

    check = OwnerOnly()
    spec = SelectorSpec(kind=RETRIEVE, selector=selector, reads=PK, permissions=[check])

    with pytest.raises(NotPermitted) as caught:
        await adispatch(spec, principal=ada, arguments={"pk": theirs.pk})

    assert caught.value.message == "Only the owner may touch this note."
    assert check.rows == [theirs]


@pytest.mark.parametrize(
    ("allow_none", "expected"),
    [
        (False, DispatchResult(kind="not_found")),
        (True, DispatchResult(kind="instance", value=None)),
    ],
    ids=["required", "allow_none"],
)
async def test_an_async_retrieve_raising_does_not_exist_is_decided_without_a_second_hop(
    ada: Any, hops: list[str], allow_none: bool, expected: DispatchResult
) -> None:
    async def selector(*, pk: int) -> Note:
        return await Note.objects.aget(pk=pk)

    check = OwnerOnly()
    spec = SelectorSpec(
        kind=RETRIEVE, selector=selector, reads=PK, permissions=[check], allow_none=allow_none
    )

    result = await adispatch(spec, principal=ada, arguments={"pk": 404})

    assert result == expected
    assert check.rows == []
    assert len(hops) == 1


async def test_an_async_list_raising_does_not_exist_passes_through(ada: Any) -> None:
    async def broken(*, user: Any) -> Any:
        return await Note.objects.aget(pk=404)

    spec = SelectorSpec(kind=LIST, selector=broken, permissions=OPEN)

    with pytest.raises(Note.DoesNotExist):
        await adispatch(spec, principal=ada, arguments={})


async def test_an_async_list_is_shaped_in_the_second_hop(ada: Any, bob: Any) -> None:
    await _create(owner=ada, title="mine")
    await _create(owner=bob, title="theirs")

    async def everything() -> Any:
        return Note.objects.all()

    def mine_only(*, queryset: Any, user: Any) -> Any:
        return queryset.filter(owner=user)

    spec = SelectorSpec(kind=LIST, selector=everything, permissions=OPEN, extend_queryset=mine_only)

    result = await adispatch(spec, principal_id=ada.pk, arguments={})

    assert result.kind == "list"
    assert [row.title for row in await sync_to_async(list)(result.value)] == ["mine"]


# --- Refused inside the hop, on every path -----------------------------------------------


async def _async_service(*, user: Any) -> None:
    raise AssertionError("ran")


async def _async_selector(*, user: Any) -> Any:
    raise AssertionError("ran")


def _sync_service(*, user: Any) -> None:
    raise AssertionError("ran")


# One spec per path ``adispatch`` takes, named by the function its first hop runs.
_PATHS: dict[str, Callable[..., Any]] = {
    "_dispatch": lambda **kw: ServiceSpec(service=_sync_service, **kw),
    "_prepare": lambda **kw: ServiceSpec(service=_async_service, atomic=False, **kw),
    "_open_selector": lambda **kw: SelectorSpec(kind=LIST, selector=_async_selector, **kw),
}


async def _deactivated(username: str) -> Any:
    user = await sync_to_async(make_user)(username)
    user.is_active = False
    await user.asave(update_fields=["is_active"])
    return user


@pytest.mark.parametrize("path", sorted(_PATHS))
async def test_a_deactivated_principal_is_refused_before_the_class_level_check(
    path: str, hops: list[str]
) -> None:
    spec = _PATHS[path](permissions=[Refuse()])

    with pytest.raises(PrincipalUnavailable) as caught:
        await adispatch(spec, principal=await _deactivated("ada"), arguments={})

    assert caught.value.message == "The acting principal is unavailable."
    assert hops == [path]


async def test_a_deactivated_principal_id_is_refused_by_resolve_principal(ada: Any) -> None:
    # The one rule, answered by its first reader: the identifier's message, not
    # dispatch's, so the two copies cannot disagree about who is refused.
    ada.is_active = False
    await ada.asave(update_fields=["is_active"])
    spec = SelectorSpec(kind=LIST, selector=notes_of, permissions=[Refuse()])

    with pytest.raises(PrincipalUnavailable) as caught:
        await adispatch(spec, principal_id=ada.pk, arguments={})

    assert caught.value.message == f"The principal {ada.pk!r} is deactivated."


@pytest.mark.parametrize("path", ["_dispatch", "_prepare"])
async def test_an_unmet_affordance_is_refused_inside_the_one_hop(
    path: str, ada: Any, hops: list[str]
) -> None:
    closed = Affordance(code="closed", reason="Closed for the night.", when=lambda: False)
    spec = _PATHS[path](permissions=OPEN, affordances=[closed])

    with pytest.raises(ActionUnavailable) as caught:
        await adispatch(spec, principal=ada, arguments={})

    assert caught.value.code == "closed"
    assert hops == [path]


async def test_a_row_condition_is_answered_inside_the_one_hop(ada: Any, hops: list[str]) -> None:
    # A query: on the event loop it would raise ``SynchronousOnlyOperation``.
    note = await _create(owner=ada, title="old", archived=True)
    spec = ServiceSpec(
        service=_async_service,
        atomic=False,
        permissions=OPEN,
        instance_selector_spec=SelectorSpec(kind=RETRIEVE, selector=note_by_pk, reads=PK),
        affordances=[Affordance(code="note_archived", reason="Archived.", when=Q(archived=False))],
    )

    with pytest.raises(ActionUnavailable):
        await adispatch(spec, principal=ada, arguments={"pk": note.pk})

    assert hops == ["_prepare"]


# --- Progress, on every path -------------------------------------------------------------


def _on_the_loop() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


class _Reporter:
    """A ``ProgressReporter`` keeping each report, and whether it was made on the event loop."""

    def __init__(self) -> None:
        self.reports: list[tuple[float, str | None, bool]] = []

    def __call__(
        self,
        progress: float,
        *,
        total: float | None = None,
        message: str | None = None,
        meta: Mapping[str, Any] | None = None,
    ) -> None:
        self.reports.append((progress, message, _on_the_loop()))


def _sync_reporting(*, progress: Any) -> str:
    progress(1, message="sync")
    return "done"


async def _async_reporting(*, progress: Any) -> Any:
    progress(1, message="async")
    return "done"


async def _async_reporting_selector(*, user: Any, progress: Any) -> Any:
    progress(1, message="selector")
    return Note.objects.filter(owner=user)


# Each path's spec, the message its run reports, and whether that run is
# awaited on an event loop rather than called on the executor thread. An atomic
# ``async def`` service joins the one hop and is still a coroutine there.
_REPORTING: dict[str, tuple[Any, str, bool]] = {
    "_dispatch": (ServiceSpec(service=_sync_reporting, permissions=OPEN), "sync", False),
    "_dispatch-atomic-async": (
        ServiceSpec(service=_async_reporting, atomic=True, permissions=OPEN),
        "async",
        True,
    ),
    "_prepare": (
        ServiceSpec(service=_async_reporting, atomic=False, permissions=OPEN),
        "async",
        True,
    ),
    "_open_selector": (
        SelectorSpec(kind=LIST, selector=_async_reporting_selector, permissions=OPEN),
        "selector",
        True,
    ),
}


@pytest.mark.parametrize("path", sorted(_REPORTING))
async def test_the_caller_s_reporter_reaches_the_run_on_every_path(path: str, ada: Any) -> None:
    spec, message, on_the_loop = _REPORTING[path]
    reporter = _Reporter()

    await adispatch(spec, principal=ada, arguments={}, progress=reporter)

    assert reporter.reports == [(1, message, on_the_loop)]


async def test_a_run_declaring_progress_runs_with_no_reporter_supplied(ada: Any) -> None:
    spec, _, _ = _REPORTING["_prepare"]

    assert (await adispatch(spec, principal=ada, arguments={})).value == "done"
