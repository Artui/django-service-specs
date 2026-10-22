"""Tests for ``update_model``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from django_service_specs.mutations.update_model import update_model
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.relations.child_spec import ChildSpec
from tests.mutations.utils import bound_call
from tests.relations_app.models import Catalog, Post, Section, Tag


@dataclass
class _PostIn:
    title: str
    body: str = ""


@dataclass
class _PostWithTagsIn:
    title: str
    tags: list[Tag]


_SECTIONS = {"sections": ChildSpec(model=Section, fk="catalog")}


def _updates(queries: CaptureQueriesContext) -> list[str]:
    return [q["sql"] for q in queries.captured_queries if q["sql"].startswith("UPDATE")]


@pytest.mark.django_db
class TestUpdateModel:
    def test_writes_the_data_onto_the_row(self) -> None:
        post = Post.objects.create(title="old")
        update_model(Post)(instance=post, data=_PostIn(title="new"))
        post.refresh_from_db()
        assert post.title == "new"

    def test_returns_the_row_not_the_change_result(self) -> None:
        post = Post.objects.create(title="old")
        assert update_model(Post)(instance=post, data=_PostIn(title="new")) is post

    def test_field_map_renames_input_keys(self) -> None:
        post = Post.objects.create(title="old")
        update_model(Post, field_map={"headline": "title"})(instance=post, data={"headline": "new"})
        assert post.title == "new"

    def test_exclude_fields_drops_keys(self) -> None:
        post = Post.objects.create(title="old", body="kept")
        update_model(Post, exclude_fields=["body"])(
            instance=post, data=_PostIn(title="new", body="x")
        )
        post.refresh_from_db()
        assert (post.title, post.body) == ("new", "kept")

    def test_m2m_as_a_static_mapping(self) -> None:
        post = Post.objects.create(title="old")
        tag = Tag.objects.create(name="a")
        update_model(Post, m2m={"tags": [tag]})(instance=post, data=_PostIn(title="old"))
        assert list(post.tags.all()) == [tag]

    def test_m2m_as_a_callable_handed_the_data(self) -> None:
        post = Post.objects.create(title="old")
        tag = Tag.objects.create(name="a")
        service = update_model(Post, exclude_fields=["tags"], m2m=lambda data: {"tags": data.tags})
        service(instance=post, data=_PostWithTagsIn(title="old", tags=[tag]))
        assert list(post.tags.all()) == [tag]

    def test_update_fields_true_saves_only_what_changed(self) -> None:
        post = Post.objects.create(title="old", body="b")
        with CaptureQueriesContext(connection) as queries:
            update_model(Post)(instance=post, data={"title": "new"})
        [sql] = _updates(queries)
        assert '"title"' in sql
        assert '"body"' not in sql

    def test_update_fields_false_saves_every_field(self) -> None:
        post = Post.objects.create(title="old", body="b")
        with CaptureQueriesContext(connection) as queries:
            update_model(Post, update_fields=False)(instance=post, data={"title": "new"})
        [sql] = _updates(queries)
        assert '"body"' in sql

    def test_update_fields_as_a_list_saves_those(self) -> None:
        post = Post.objects.create(title="old", body="b")
        with CaptureQueriesContext(connection) as queries:
            update_model(Post, update_fields=["title", "body"])(
                instance=post, data={"title": "new"}
            )
        [sql] = _updates(queries)
        assert '"body"' in sql
        assert '"views"' not in sql

    def test_the_rest_of_the_pool_is_absorbed(self) -> None:
        post = Post.objects.create(title="old")
        update_model(Post)(instance=post, data={"title": "new"}, user=object(), extra=1)
        assert post.title == "new"

    def test_relations_reconcile_the_nested_rows(self) -> None:
        catalog = Catalog.objects.create(name="c")
        kept = Section.objects.create(catalog=catalog, title="kept")
        Section.objects.create(catalog=catalog, title="dropped")
        update_model(Catalog, relations=_SECTIONS)(
            instance=catalog,
            data={"sections": [{"pk": kept.pk, "title": "kept"}, {"title": "new"}]},
        )
        assert sorted(catalog.sections.values_list("title", flat=True)) == ["kept", "new"]

    def test_the_pool_reaches_a_row_service_as_context(self) -> None:
        seen: list[Any] = []

        def create_section(*, data: dict[str, Any], user: Any) -> Section:
            seen.append(user)
            return Section.objects.create(**data)

        relations = {
            "sections": ChildSpec(model=Section, fk="catalog", create_service=create_section)
        }
        catalog = Catalog.objects.create(name="c")
        update_model(Catalog, relations=relations)(
            instance=catalog, data={"sections": [{"title": "a"}]}, user="the caller"
        )
        assert seen == ["the caller"]

    def test_the_call_context_reaches_a_row_service_that_names_it(self) -> None:
        seen: list[Any] = []
        context: dict[str, Any] = {}

        def create_section(*, data: dict[str, Any], call_context: Any = None) -> Section:
            seen.append(call_context)
            return Section.objects.create(**data)

        relations = {
            "sections": ChildSpec(model=Section, fk="catalog", create_service=create_section)
        }
        catalog = Catalog.objects.create(name="c")
        bound_call(
            update_model(Catalog, relations=relations),
            instance=catalog,
            data={"sections": [{"title": "a"}]},
            call_context=context,
        )
        assert len(seen) == 1
        assert seen[0] is context

    def test_a_null_row_is_refused(self) -> None:
        catalog = Catalog.objects.create(name="c")
        with pytest.raises(InvalidArguments):
            update_model(Catalog, relations=_SECTIONS)(instance=catalog, data={"sections": [None]})

    def test_opens_no_savepoint_of_its_own(self) -> None:
        catalog = Catalog.objects.create(name="c")
        with CaptureQueriesContext(connection) as queries:
            update_model(Catalog, relations=_SECTIONS)(
                instance=catalog, data={"sections": [{"title": "a"}]}
            )
        assert not [q for q in queries.captured_queries if "SAVEPOINT" in q["sql"].upper()]
