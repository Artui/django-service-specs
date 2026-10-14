"""Tests for ``acreate_model``."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any

import pytest
from asgiref.sync import sync_to_async

from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.relations.child_spec import ChildSpec
from django_service_specs.services.acreate_model import acreate_model
from tests.relations_app.models import Author, Catalog, Post, Section, Tag


@dataclass
class _AuthorIn:
    name: str


@dataclass
class _PostIn:
    title: str
    body: str = ""


@dataclass
class _PostWithTagsIn:
    title: str
    tags: list[Tag]


_SECTIONS = {"sections": ChildSpec(model=Section, fk="catalog")}


@pytest.mark.django_db(transaction=True)
class TestACreateModel:
    async def test_the_service_is_a_coroutine_function(self) -> None:
        assert inspect.iscoroutinefunction(acreate_model(Author))

    async def test_builds_and_saves_the_row_and_returns_it(self) -> None:
        author = await acreate_model(Author)(data=_AuthorIn(name="Ada"))
        assert type(author) is Author
        assert await Author.objects.filter(pk=author.pk, name="Ada").aexists()

    async def test_field_map_renames_input_keys(self) -> None:
        post = await acreate_model(Post, field_map={"headline": "title"})(data={"headline": "Hi"})
        assert post.title == "Hi"

    async def test_exclude_fields_drops_keys(self) -> None:
        post = await acreate_model(Post, exclude_fields=["body"])(
            data=_PostIn(title="T", body="dropped")
        )
        await post.arefresh_from_db()
        assert post.body == ""

    async def test_m2m_as_a_static_mapping(self) -> None:
        tag = await Tag.objects.acreate(name="a")
        post = await acreate_model(Post, m2m={"tags": [tag]})(data=_PostIn(title="T"))
        assert [t async for t in post.tags.all()] == [tag]

    async def test_m2m_as_a_callable_handed_the_data(self) -> None:
        tag = await Tag.objects.acreate(name="a")
        service = acreate_model(Post, exclude_fields=["tags"], m2m=lambda data: {"tags": data.tags})
        post = await service(data=_PostWithTagsIn(title="T", tags=[tag]))
        assert [t async for t in post.tags.all()] == [tag]

    async def test_the_rest_of_the_pool_is_absorbed(self) -> None:
        author = await acreate_model(Author)(data=_AuthorIn(name="Grace"), user=object())
        assert author.name == "Grace"

    async def test_relations_write_the_nested_rows(self) -> None:
        catalog = await acreate_model(Catalog, relations=_SECTIONS)(
            data={"name": "c", "sections": [{"title": "a"}, {"title": "b"}]}
        )
        titles = await sync_to_async(
            lambda: sorted(catalog.sections.values_list("title", flat=True))
        )()
        assert titles == ["a", "b"]

    async def test_the_pool_reaches_a_row_service_as_context(self) -> None:
        seen: list[Any] = []

        async def create_section(*, data: dict[str, Any], user: Any) -> Section:
            seen.append(user)
            return await Section.objects.acreate(**data)

        relations = {
            "sections": ChildSpec(model=Section, fk="catalog", create_service=create_section)
        }
        await acreate_model(Catalog, relations=relations)(
            data={"name": "c", "sections": [{"title": "a"}]}, user="the caller"
        )
        assert seen == ["the caller"]

    async def test_a_null_row_is_refused(self) -> None:
        with pytest.raises(InvalidArguments):
            await acreate_model(Catalog, relations=_SECTIONS)(
                data={"name": "c", "sections": [None]}
            )
