"""``AsyncSelector``: an ``async def`` selector, which ``adispatch`` awaits."""

from __future__ import annotations

from typing import Any

import pytest
from asgiref.sync import sync_to_async

from django_service_specs.dispatch.adispatch import adispatch
from django_service_specs.selectors.async_selector import AsyncSelector
from django_service_specs.selectors.selector import Selector
from django_service_specs.services.is_async import is_async
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from tests.dispatch.utils import OPEN, make_user
from tests.dispatch_app.models import Note


async def _titles(**_: Any) -> list[str]:
    return [note.title async for note in Note.objects.order_by("pk")]


def _read(**_: Any) -> list[Any]:
    return []


def test_an_isinstance_check_cannot_tell_it_from_a_sync_selector() -> None:
    assert isinstance(_titles, AsyncSelector)
    assert isinstance(_read, AsyncSelector)
    assert isinstance(_titles, Selector)


def test_is_async_is_the_run_time_question() -> None:
    assert is_async(_titles)
    assert not is_async(_read)


@pytest.mark.django_db(transaction=True)
async def test_adispatch_awaits_it() -> None:
    ada = await sync_to_async(make_user)("ada")
    await Note.objects.acreate(owner=ada, title="Minutes")
    spec = SelectorSpec(kind=SelectorKind.LIST, selector=_titles, permissions=OPEN)

    result = await adispatch(spec, principal=ada, arguments={})

    assert list(result.value) == ["Minutes"]
