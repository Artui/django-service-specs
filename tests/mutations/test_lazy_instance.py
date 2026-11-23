from __future__ import annotations

from typing import Any

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from django.utils.functional import SimpleLazyObject

from django_service_specs.mutations.aupdate_from_input import aupdate_from_input
from django_service_specs.mutations.update_from_input import update_from_input


def lazy_user(pk: Any) -> Any:
    """``request.user`` as Django's auth middleware hands it over: a proxy over a saved row."""
    return SimpleLazyObject(lambda: get_user_model().objects.get(pk=pk))


@pytest.mark.django_db
def test_update_from_input_writes_a_lazy_row() -> None:
    saved = get_user_model().objects.create_user(username="ada")
    lazy = lazy_user(saved.pk)

    result = update_from_input(lazy, {"first_name": "Ada"})

    assert result.changed_fields == ("first_name",)
    assert result.instance is lazy
    saved.refresh_from_db()
    assert saved.first_name == "Ada"


@pytest.mark.django_db(transaction=True)
async def test_aupdate_from_input_writes_a_lazy_row() -> None:
    saved = await get_user_model().objects.acreate(username="ada")
    lazy = lazy_user(saved.pk)
    # The proxy resolves on a thread, as an async view's middleware has already resolved it.
    await sync_to_async(lambda: lazy.pk)()

    result = await aupdate_from_input(lazy, {"first_name": "Ada"})

    assert result.changed_fields == ("first_name",)
    await sync_to_async(saved.refresh_from_db)()
    assert saved.first_name == "Ada"
