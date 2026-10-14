"""Tests for ``adelete_collection``."""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from django_service_specs.services.adelete_collection import adelete_collection
from tests.relations_app.models import Author


@pytest.mark.django_db(transaction=True)
class TestADeleteCollection:
    async def test_the_service_is_a_coroutine_function(self) -> None:
        assert inspect.iscoroutinefunction(adelete_collection(Author))

    async def test_deletes_every_row_in_the_collection_and_returns_none(self) -> None:
        kept = await Author.objects.acreate(name="kept")
        await Author.objects.acreate(name="a")
        result = await adelete_collection(Author)(collection=Author.objects.exclude(pk=kept.pk))
        assert result is None
        assert [author async for author in Author.objects.all()] == [kept]

    async def test_an_empty_collection_deletes_nothing(self) -> None:
        await Author.objects.acreate(name="kept")
        await adelete_collection(Author)(collection=Author.objects.none())
        assert await Author.objects.acount() == 1

    async def test_soft_delete_replaces_the_delete(self) -> None:
        await Author.objects.acreate(name="a")
        handed: list[Any] = []
        collection = Author.objects.all()

        async def archive(rows: Any) -> None:
            handed.append(rows)

        await adelete_collection(Author, soft_delete=archive)(collection=collection, user=object())
        assert handed == [collection]
        assert await Author.objects.acount() == 1
