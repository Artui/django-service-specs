"""Tests for ``delete_collection``."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from django.db.models.signals import post_delete

from django_service_specs.services.delete_collection import delete_collection
from tests.relations_app.models import Author, Post


@pytest.fixture
def deleted() -> Iterator[list[Any]]:
    """The primary key of every row Django sends ``post_delete`` for."""
    seen: list[Any] = []

    def receiver(sender: Any, instance: Any, **_: Any) -> None:
        seen.append(instance.pk)

    post_delete.connect(receiver, sender=Author, weak=False)
    yield seen
    post_delete.disconnect(receiver, sender=Author)


@pytest.mark.django_db
class TestDeleteCollection:
    def test_deletes_every_row_in_the_collection_and_returns_none(self, deleted: list[Any]) -> None:
        kept = Author.objects.create(name="kept")
        gone = [Author.objects.create(name="a"), Author.objects.create(name="b")]
        result = delete_collection(Author)(collection=Author.objects.exclude(pk=kept.pk))
        assert result is None
        assert list(Author.objects.all()) == [kept]
        # A bulk delete still sends the signal for each row.
        assert sorted(deleted) == sorted(author.pk for author in gone)

    def test_the_database_cascade_runs(self) -> None:
        author = Author.objects.create(name="a")
        Post.objects.create(title="p", author=author)
        delete_collection(Author)(collection=Author.objects.all())
        # The post's foreign key cascades, as it would from a single row's delete.
        assert not Post.objects.exists()

    def test_an_empty_collection_deletes_nothing(self) -> None:
        Author.objects.create(name="kept")
        delete_collection(Author)(collection=Author.objects.none())
        assert Author.objects.count() == 1

    def test_soft_delete_replaces_the_delete(self, deleted: list[Any]) -> None:
        Author.objects.create(name="a")
        handed: list[Any] = []
        collection = Author.objects.all()
        delete_collection(Author, soft_delete=handed.append)(collection=collection)
        assert handed == [collection]
        assert Author.objects.count() == 1
        assert deleted == []

    def test_the_rest_of_the_pool_is_absorbed(self) -> None:
        Author.objects.create(name="a")
        delete_collection(Author)(collection=Author.objects.all(), user=object(), extra=1)
        assert not Author.objects.exists()
