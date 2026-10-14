"""Tests for ``adelete_collection``."""

from __future__ import annotations

from typing import Any

import pytest
from asgiref.sync import async_to_sync

from django_service_specs.mutations.adelete_collection import adelete_collection
from django_service_specs.types.is_async import is_async
from tests.mutations.utils import savepoints_during
from tests.relations_app.models import Author


@pytest.mark.django_db(transaction=True)
class TestADeleteCollection:
    async def test_dispatch_reads_the_service_as_async(self) -> None:
        assert is_async(adelete_collection(Author))

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


@pytest.mark.django_db
def test_opens_no_savepoint_of_its_own() -> None:
    Author.objects.create(name="a")
    service = async_to_sync(adelete_collection(Author))
    assert savepoints_during(lambda: service(collection=Author.objects.all())) == []
