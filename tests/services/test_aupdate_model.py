"""Tests for ``aupdate_model``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from asgiref.sync import async_to_sync, sync_to_async
from django.db import connection
from django.test.utils import CaptureQueriesContext

from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.relations.child_spec import ChildSpec
from django_service_specs.services.aupdate_model import aupdate_model
from django_service_specs.services.is_async import is_async
from tests.relations_app.models import Catalog, Post, Section, Tag
from tests.services.utils import savepoints_during


@dataclass
class _PostIn:
    title: str
    body: str = ""


@dataclass
class _PostWithTagsIn:
    title: str
    tags: list[Tag]


_SECTIONS = {"sections": ChildSpec(model=Section, fk="catalog")}


def _update_sql(service: Any, **kwargs: Any) -> str:
    """The one ``UPDATE`` the service runs.

    Called from sync code through ``async_to_sync``, so the helper's ORM hops
    come back to this thread and its connection, which the capture watches.
    """
    with CaptureQueriesContext(connection) as queries:
        async_to_sync(service)(**kwargs)
    [sql] = [q["sql"] for q in queries.captured_queries if q["sql"].startswith("UPDATE")]
    return sql


@pytest.mark.django_db
class TestUpdateFieldsIsHandedOn:
    def test_true_saves_only_what_changed(self) -> None:
        post = Post.objects.create(title="old", body="b")
        sql = _update_sql(aupdate_model(Post), instance=post, data={"title": "x"})
        assert '"title"' in sql
        assert '"body"' not in sql

    def test_false_saves_every_field(self) -> None:
        post = Post.objects.create(title="old", body="b")
        sql = _update_sql(
            aupdate_model(Post, update_fields=False), instance=post, data={"title": "y"}
        )
        assert '"views"' in sql

    def test_a_list_saves_those(self) -> None:
        post = Post.objects.create(title="old", body="b")
        service = aupdate_model(Post, update_fields=["title", "body"])
        sql = _update_sql(service, instance=post, data={"title": "z"})
        assert '"body"' in sql
        assert '"views"' not in sql


@pytest.mark.django_db(transaction=True)
class TestAUpdateModel:
    async def test_dispatch_reads_the_service_as_async(self) -> None:
        assert is_async(aupdate_model(Post))

    async def test_writes_the_data_onto_the_row_and_returns_it(self) -> None:
        post = await Post.objects.acreate(title="old")
        assert await aupdate_model(Post)(instance=post, data=_PostIn(title="new")) is post
        await post.arefresh_from_db()
        assert post.title == "new"

    async def test_field_map_renames_input_keys(self) -> None:
        post = await Post.objects.acreate(title="old")
        await aupdate_model(Post, field_map={"headline": "title"})(
            instance=post, data={"headline": "new"}
        )
        assert post.title == "new"

    async def test_exclude_fields_drops_keys(self) -> None:
        post = await Post.objects.acreate(title="old", body="kept")
        await aupdate_model(Post, exclude_fields=["body"])(
            instance=post, data=_PostIn(title="new", body="x")
        )
        await post.arefresh_from_db()
        assert (post.title, post.body) == ("new", "kept")

    async def test_m2m_as_a_static_mapping(self) -> None:
        post = await Post.objects.acreate(title="old")
        tag = await Tag.objects.acreate(name="a")
        await aupdate_model(Post, m2m={"tags": [tag]})(instance=post, data=_PostIn(title="old"))
        assert [t async for t in post.tags.all()] == [tag]

    async def test_m2m_as_a_callable_handed_the_data(self) -> None:
        post = await Post.objects.acreate(title="old")
        tag = await Tag.objects.acreate(name="a")
        service = aupdate_model(Post, exclude_fields=["tags"], m2m=lambda data: {"tags": data.tags})
        await service(instance=post, data=_PostWithTagsIn(title="old", tags=[tag]))
        assert [t async for t in post.tags.all()] == [tag]

    async def test_the_rest_of_the_pool_is_absorbed(self) -> None:
        post = await Post.objects.acreate(title="old")
        await aupdate_model(Post)(instance=post, data={"title": "new"}, user=object())
        assert post.title == "new"

    async def test_relations_reconcile_the_nested_rows(self) -> None:
        catalog = await Catalog.objects.acreate(name="c")
        kept = await Section.objects.acreate(catalog=catalog, title="kept")
        await Section.objects.acreate(catalog=catalog, title="dropped")
        await aupdate_model(Catalog, relations=_SECTIONS)(
            instance=catalog,
            data={"sections": [{"pk": kept.pk, "title": "kept"}, {"title": "new"}]},
        )
        titles = await sync_to_async(
            lambda: sorted(catalog.sections.values_list("title", flat=True))
        )()
        assert titles == ["kept", "new"]

    async def test_the_pool_reaches_a_row_service_as_context(self) -> None:
        seen: list[Any] = []

        async def create_section(*, data: dict[str, Any], user: Any) -> Section:
            seen.append(user)
            return await Section.objects.acreate(**data)

        relations = {
            "sections": ChildSpec(model=Section, fk="catalog", create_service=create_section)
        }
        catalog = await Catalog.objects.acreate(name="c")
        await aupdate_model(Catalog, relations=relations)(
            instance=catalog, data={"sections": [{"title": "a"}]}, user="the caller"
        )
        assert seen == ["the caller"]

    async def test_a_null_row_is_refused(self) -> None:
        catalog = await Catalog.objects.acreate(name="c")
        with pytest.raises(InvalidArguments):
            await aupdate_model(Catalog, relations=_SECTIONS)(
                instance=catalog, data={"sections": [None]}
            )


@pytest.mark.django_db
def test_opens_no_savepoint_of_its_own() -> None:
    catalog = Catalog.objects.create(name="c")
    service = async_to_sync(aupdate_model(Catalog, relations=_SECTIONS))
    data = {"sections": [{"title": "a"}]}
    assert savepoints_during(lambda: service(instance=catalog, data=data)) == []
