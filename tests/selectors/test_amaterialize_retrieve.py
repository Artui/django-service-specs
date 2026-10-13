"""The async twin of ``materialize_retrieve``: the same rule, without blocking the loop."""

from __future__ import annotations

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth.models import User

from django_service_specs.selectors.amaterialize_retrieve import amaterialize_retrieve


@pytest.mark.django_db(transaction=True)
async def test_a_queryset_resolves_to_its_first_row_on_the_loop() -> None:
    # ``.first()`` here would raise ``SynchronousOnlyOperation``.
    user = await sync_to_async(User.objects.create)(username="only")
    assert await amaterialize_retrieve(User.objects.filter(pk=user.pk)) == user


@pytest.mark.django_db(transaction=True)
async def test_an_empty_queryset_resolves_to_none() -> None:
    assert await amaterialize_retrieve(User.objects.none()) is None


async def test_anything_else_is_already_the_row() -> None:
    row = object()
    assert await amaterialize_retrieve(row) is row
