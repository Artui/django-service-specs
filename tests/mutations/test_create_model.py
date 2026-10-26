"""Tests for ``create_model``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ImproperlyConfigured
from django.db import connection
from django.test.utils import CaptureQueriesContext

from django_service_specs.adapters.dataclass.dataclass_validator import DataclassValidator
from django_service_specs.authorization.unrestricted import Unrestricted
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.mutations.create_model import create_model
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.relations.child_spec import ChildSpec
from django_service_specs.specs.service_spec import ServiceSpec
from tests.mutations.utils import bound_call
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


@pytest.mark.django_db
class TestCreateModel:
    def test_builds_and_saves_the_row(self) -> None:
        author = create_model(Author)(data=_AuthorIn(name="Ada"))
        assert isinstance(author, Author)
        assert author.pk is not None
        assert Author.objects.filter(name="Ada").exists()

    def test_returns_the_row_not_the_change_result(self) -> None:
        author = create_model(Author)(data=_AuthorIn(name="Linus"))
        assert type(author) is Author

    def test_field_map_renames_input_keys(self) -> None:
        post = create_model(Post, field_map={"headline": "title"})(data={"headline": "Hi"})
        assert post.title == "Hi"

    def test_exclude_fields_drops_keys(self) -> None:
        post = create_model(Post, exclude_fields=["body"])(data=_PostIn(title="T", body="dropped"))
        post.refresh_from_db()
        assert post.body == ""

    def test_m2m_as_a_static_mapping(self) -> None:
        tag = Tag.objects.create(name="a")
        post = create_model(Post, m2m={"tags": [tag]})(data=_PostIn(title="T"))
        assert list(post.tags.all()) == [tag]

    def test_m2m_as_a_callable_handed_the_data(self) -> None:
        tag = Tag.objects.create(name="a")
        service = create_model(Post, exclude_fields=["tags"], m2m=lambda data: {"tags": data.tags})
        post = service(data=_PostWithTagsIn(title="T", tags=[tag]))
        assert list(post.tags.all()) == [tag]

    def test_the_rest_of_the_pool_is_absorbed(self) -> None:
        author = create_model(Author)(data=_AuthorIn(name="Grace"), user=object(), extra=1)
        assert author.name == "Grace"

    def test_relations_write_the_nested_rows(self) -> None:
        catalog = create_model(Catalog, relations=_SECTIONS)(
            data={"name": "c", "sections": [{"title": "a"}, {"title": "b"}]}
        )
        assert sorted(catalog.sections.values_list("title", flat=True)) == ["a", "b"]

    def test_the_pool_reaches_a_row_service_as_context(self) -> None:
        seen: list[Any] = []

        def create_section(*, data: dict[str, Any], user: Any) -> Section:
            seen.append(user)
            return Section.objects.create(**data)

        relations = {
            "sections": ChildSpec(model=Section, fk="catalog", create_service=create_section)
        }
        create_model(Catalog, relations=relations)(
            data={"name": "c", "sections": [{"title": "a"}]}, user="the caller"
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
        bound_call(
            create_model(Catalog, relations=relations),
            data={"name": "c", "sections": [{"title": "a"}]},
            call_context=context,
        )
        assert len(seen) == 1
        assert seen[0] is context

    def test_the_call_s_request_reaches_a_row_service_that_names_it(self) -> None:
        """Read off the context handed on, as the service above is handed it."""
        seen: list[Any] = []
        request = object()

        def create_section(*, data: dict[str, Any], request: Any, view: Any) -> Section:
            seen.append((request, view))
            return Section.objects.create(**data)

        relations = {
            "sections": ChildSpec(model=Section, fk="catalog", create_service=create_section)
        }
        bound_call(
            create_model(Catalog, relations=relations),
            data={"name": "c", "sections": [{"title": "a"}]},
            call_context={"request": request},
        )
        assert seen == [(request, None)]

    def test_a_row_service_taking_only_kwargs_is_not_handed_the_call_context(self) -> None:
        # The by-name rule holds one level down: the helper hands the call's
        # context on, and a nested catch-all is still never given it.
        seen: list[dict[str, Any]] = []

        def create_section(*, data: dict[str, Any], **kwargs: Any) -> Section:
            seen.append(kwargs)
            return Section.objects.create(**data)

        relations = {
            "sections": ChildSpec(model=Section, fk="catalog", create_service=create_section)
        }
        bound_call(
            create_model(Catalog, relations=relations),
            data={"name": "c", "sections": [{"title": "a"}]},
            call_context={},
            user="ada",
        )
        assert len(seen) == 1
        assert seen[0]["user"] == "ada"
        assert "call_context" not in seen[0]

    def test_a_null_row_is_refused(self) -> None:
        with pytest.raises(InvalidArguments):
            create_model(Catalog, relations=_SECTIONS)(data={"name": "c", "sections": [None]})
        assert not Section.objects.exists()

    def test_a_relation_that_is_not_a_spec_is_refused(self) -> None:
        with pytest.raises(ImproperlyConfigured, match="relations\\['sections'\\] is a dict"):
            create_model(Catalog, relations={"sections": {"model": Section}})(data={"name": "c"})

    def test_opens_no_savepoint_of_its_own(self) -> None:
        # The run's transaction covers the row and every nested write; a block
        # here would cost a savepoint inside it and guarantee nothing more.
        with CaptureQueriesContext(connection) as queries:
            create_model(Catalog, relations=_SECTIONS)(
                data={"name": "c", "sections": [{"title": "a"}]}
            )
        assert not [q for q in queries.captured_queries if "SAVEPOINT" in q["sql"].upper()]

    def test_dispatch_runs_it_with_the_principal_in_its_pool(self) -> None:
        user = User.objects.create(username="u")
        spec = ServiceSpec(
            service=create_model(Author),
            permissions=[Unrestricted()],
            validator=DataclassValidator(_AuthorIn),
        )
        result = dispatch(spec, principal=user, arguments={"name": "Ada"})
        assert isinstance(result.value, Author)
        assert Author.objects.get().name == "Ada"
