"""``apresent``: ``present`` in one executor hop, safe to use from the event loop."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Any

import pytest
from asgiref.sync import sync_to_async

from django_service_specs.dispatch.apresent import apresent
from django_service_specs.dispatch.dispatch_result import DispatchResult
from django_service_specs.output.output import Output
from django_service_specs.output.output_field import OutputField
from django_service_specs.output.presenter import Presenter
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from tests.dispatch.utils import OPEN, make_user, notes_of
from tests.dispatch_app.models import Note

# By import path: the package's attribute of this name is the function.
_module = importlib.import_module("django_service_specs.dispatch.apresent")


@pytest.fixture
def hops(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    made: list[str] = []

    def counted(fn: Callable[..., Any], *, thread_sensitive: bool) -> Any:
        assert thread_sensitive is True
        made.append(fn.__name__)
        return sync_to_async(fn, thread_sensitive=True)

    monkeypatch.setattr(_module, "sync_to_async", counted)
    return made


class OwnerNames(Presenter):
    """Reads a relation off each row: a query per row, unless it was prefetched."""

    def output(self) -> Output:
        return Output((OutputField("owner", "string"),))

    def present(self, value: Any) -> Any:
        return {"owner": value.owner.username}


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("presenter", [OwnerNames(), None], ids=["presenter", "no presenter"])
async def test_a_list_is_presented_in_one_hop_and_comes_back_evaluated(
    hops: list[str], presenter: Any
) -> None:
    owner = await sync_to_async(make_user)("ada")
    note = await Note.objects.acreate(owner=owner, title="a")
    spec = SelectorSpec(
        kind=SelectorKind.LIST, selector=notes_of, permissions=OPEN, presenter=presenter
    )

    rendered = await apresent(spec, DispatchResult("list", Note.objects.all()))

    # Compared here, on the loop, which iterates it: an unevaluated queryset
    # would run its query now and raise.
    assert type(rendered) is list
    assert rendered == ([{"owner": "ada"}] if presenter is not None else [note])
    assert hops == ["present"]


async def test_not_found_is_refused_as_present_refuses_it() -> None:
    spec = SelectorSpec(kind=SelectorKind.RETRIEVE, selector=notes_of, permissions=OPEN)

    with pytest.raises(ValueError) as caught:
        await apresent(spec, DispatchResult("not_found"))

    assert str(caught.value) == (
        "A not-found result has nothing to present. Answer it as the transport's own "
        "not-found before presenting."
    )
