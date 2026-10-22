"""Tests for ``adelete_model``."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from asgiref.sync import async_to_sync
from django.core.exceptions import ImproperlyConfigured
from django.db.models.signals import post_delete

from django_service_specs.mutations.adelete_model import adelete_model
from django_service_specs.relations.child_spec import ChildSpec
from django_service_specs.types.is_async import is_async
from tests.mutations.utils import bound_call, savepoints_during
from tests.relations_app.models import Author, Catalog, Item, Section


@pytest.fixture
def deleted() -> Iterator[list[str]]:
    """The class name of every row Django sends ``post_delete`` for."""
    seen: list[str] = []

    def receiver(sender: Any, instance: Any, **_: Any) -> None:
        seen.append(type(instance).__name__)

    post_delete.connect(receiver, weak=False)
    yield seen
    post_delete.disconnect(receiver)


async def _catalog() -> Catalog:
    catalog = await Catalog.objects.acreate(name="c")
    section = await Section.objects.acreate(catalog=catalog, title="s")
    await Item.objects.acreate(section=section, label="i")
    return catalog


_CASCADE = {
    "sections": ChildSpec(
        model=Section, fk="catalog", relations={"items": ChildSpec(model=Item, fk="section")}
    )
}


@pytest.mark.django_db(transaction=True)
class TestADeleteModel:
    async def test_dispatch_reads_the_service_as_async(self) -> None:
        assert is_async(adelete_model(Author))

    async def test_deletes_the_row_and_returns_none(self, deleted: list[str]) -> None:
        author = await Author.objects.acreate(name="a")
        assert await adelete_model(Author)(instance=author) is None
        assert not await Author.objects.aexists()
        assert deleted == ["Author"]

    async def test_soft_delete_replaces_the_delete(self, deleted: list[str]) -> None:
        author = await Author.objects.acreate(name="a")
        retired: list[Author] = []

        async def retire(instance: Author) -> None:
            retired.append(instance)

        await adelete_model(Author, soft_delete=retire)(instance=author)
        assert retired == [author]
        assert await Author.objects.filter(pk=author.pk).aexists()
        assert deleted == []

    async def test_the_rest_of_the_pool_is_absorbed(self) -> None:
        author = await Author.objects.acreate(name="a")
        await adelete_model(Author)(instance=author, user=object())
        assert not await Author.objects.aexists()

    async def test_the_owned_rows_go_first_deepest_first(self, deleted: list[str]) -> None:
        catalog = await _catalog()
        await adelete_model(Catalog, relations=_CASCADE)(instance=catalog)
        assert not await Section.objects.aexists()
        assert deleted == ["Item", "Section", "Catalog"]

    async def test_a_soft_delete_still_gets_the_cascade(self) -> None:
        catalog = await _catalog()

        async def keep(instance: Catalog) -> None: ...

        await adelete_model(Catalog, soft_delete=keep, relations=_CASCADE)(instance=catalog)
        assert await Catalog.objects.filter(pk=catalog.pk).aexists()
        assert not await Section.objects.aexists()

    async def test_the_pool_reaches_a_rows_delete_service_as_context(self) -> None:
        seen: list[Any] = []

        async def delete_section(*, instance: Section, user: Any) -> None:
            seen.append(user)
            await instance.adelete()

        relations = {
            "sections": ChildSpec(model=Section, fk="catalog", delete_service=delete_section)
        }
        await adelete_model(Catalog, relations=relations)(instance=await _catalog(), user="caller")
        assert seen == ["caller"]

    async def test_the_call_context_reaches_a_rows_delete_service_that_names_it(self) -> None:
        seen: list[Any] = []
        context: dict[str, Any] = {}

        async def delete_section(*, instance: Section, call_context: Any = None) -> None:
            seen.append(call_context)
            await instance.adelete()

        relations = {
            "sections": ChildSpec(model=Section, fk="catalog", delete_service=delete_section)
        }
        await bound_call(
            adelete_model(Catalog, relations=relations),
            instance=await _catalog(),
            call_context=context,
        )
        assert len(seen) == 1
        assert seen[0] is context

    async def test_an_empty_map_leaves_the_rows_to_the_database(self, deleted: list[str]) -> None:
        await adelete_model(Catalog, relations={})(instance=await _catalog())
        assert sorted(deleted) == ["Catalog", "Item", "Section"]

    def test_a_relation_that_is_not_a_spec_is_refused_when_built(self) -> None:
        with pytest.raises(ImproperlyConfigured, match="relations\\['sections'\\] is a dict"):
            adelete_model(Catalog, relations={"sections": {"model": Section}})


@pytest.mark.django_db
def test_opens_no_savepoint_of_its_own() -> None:
    catalog = Catalog.objects.create(name="c")
    section = Section.objects.create(catalog=catalog, title="s")
    Item.objects.create(section=section, label="i")
    service = async_to_sync(adelete_model(Catalog, relations=_CASCADE))
    assert savepoints_during(lambda: service(instance=catalog)) == []
