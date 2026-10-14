"""Tests for ``delete_model``."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ImproperlyConfigured
from django.db import connection
from django.db.models.signals import post_delete
from django.test.utils import CaptureQueriesContext

from django_service_specs.authorization.unrestricted import Unrestricted
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.parameters.parameter import Parameter
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.relations.child_spec import ChildSpec
from django_service_specs.relations.many_to_many_spec import ManyToManySpec
from django_service_specs.services.delete_model import delete_model
from django_service_specs.services.service_validation_error import ServiceValidationError
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.selector_kind import SelectorKind
from tests.relations_app.models import Author, Catalog, Item, Section, Tag


@pytest.fixture
def deleted() -> Iterator[list[str]]:
    """The class name of every row Django sends ``post_delete`` for."""
    seen: list[str] = []

    def receiver(sender: Any, instance: Any, **_: Any) -> None:
        seen.append(type(instance).__name__)

    post_delete.connect(receiver, weak=False)
    yield seen
    post_delete.disconnect(receiver)


def _catalog() -> Catalog:
    catalog = Catalog.objects.create(name="c")
    section = Section.objects.create(catalog=catalog, title="s")
    Item.objects.create(section=section, label="i")
    return catalog


_CASCADE = {
    "sections": ChildSpec(
        model=Section, fk="catalog", relations={"items": ChildSpec(model=Item, fk="section")}
    )
}


@pytest.mark.django_db
class TestDeleteModel:
    def test_deletes_the_row_and_returns_none(self, deleted: list[str]) -> None:
        author = Author.objects.create(name="a")
        assert delete_model(Author)(instance=author) is None
        assert not Author.objects.exists()
        assert deleted == ["Author"]

    def test_soft_delete_replaces_the_delete(self, deleted: list[str]) -> None:
        author = Author.objects.create(name="a")
        retired: list[Author] = []
        delete_model(Author, soft_delete=retired.append)(instance=author)
        assert retired == [author]
        assert Author.objects.filter(pk=author.pk).exists()
        # No row went, so Django sent nothing.
        assert deleted == []

    def test_the_rest_of_the_pool_is_absorbed(self) -> None:
        author = Author.objects.create(name="a")
        delete_model(Author)(instance=author, user=object(), extra=1)
        assert not Author.objects.exists()

    def test_the_owned_rows_go_first_deepest_first(self, deleted: list[str]) -> None:
        catalog = _catalog()
        delete_model(Catalog, relations=_CASCADE)(instance=catalog)
        assert not Section.objects.exists()
        assert not Item.objects.exists()
        # The cascade's rows are each deleted before the parent, a grandchild
        # before its own parent.
        assert deleted == ["Item", "Section", "Catalog"]

    def test_a_many_to_many_loses_only_its_membership(self) -> None:
        catalog = Catalog.objects.create(name="c")
        section = Section.objects.create(catalog=catalog, title="s")
        section.tags.add(Tag.objects.create(name="t"))
        delete_model(Section, relations={"tags": ManyToManySpec(model=Tag)})(instance=section)
        assert Tag.objects.filter(name="t").exists()

    def test_a_soft_delete_still_gets_the_cascade(self) -> None:
        catalog = _catalog()
        delete_model(Catalog, soft_delete=lambda instance: None, relations=_CASCADE)(
            instance=catalog
        )
        assert Catalog.objects.filter(pk=catalog.pk).exists()
        assert not Section.objects.exists()

    def test_the_pool_reaches_a_rows_delete_service_as_context(self) -> None:
        seen: list[Any] = []

        def delete_section(*, instance: Section, user: Any) -> None:
            seen.append(user)
            instance.delete()

        relations = {
            "sections": ChildSpec(model=Section, fk="catalog", delete_service=delete_section)
        }
        delete_model(Catalog, relations=relations)(instance=_catalog(), user="the caller")
        assert seen == ["the caller"]

    def test_an_empty_map_leaves_the_rows_to_the_database(self, deleted: list[str]) -> None:
        catalog = _catalog()
        delete_model(Catalog, relations={})(instance=catalog)
        # Django's own collector took the rows, each once.
        assert sorted(deleted) == ["Catalog", "Item", "Section"]

    def test_a_relation_that_is_not_a_spec_is_refused_when_built(self) -> None:
        with pytest.raises(ImproperlyConfigured, match="relations\\['sections'\\] is a dict"):
            delete_model(Catalog, relations={"sections": {"model": Section}})

    def test_opens_no_savepoint_of_its_own(self) -> None:
        catalog = _catalog()
        with CaptureQueriesContext(connection) as queries:
            delete_model(Catalog, relations=_CASCADE)(instance=catalog)
        assert not [q for q in queries.captured_queries if "SAVEPOINT" in q["sql"].upper()]


@pytest.mark.django_db(transaction=True)
class TestThroughDispatch:
    def test_a_refused_cascade_leaves_every_row_in_place(self) -> None:
        catalog = Catalog.objects.create(name="c")
        Section.objects.create(catalog=catalog, title="first")
        Section.objects.create(catalog=catalog, title="refused")

        def delete_section(*, instance: Section) -> None:
            if instance.title == "refused":
                raise ServiceValidationError("Not this one.")
            instance.delete()

        spec = ServiceSpec(
            service=delete_model(
                Catalog,
                relations={
                    "sections": ChildSpec(
                        model=Section, fk="catalog", delete_service=delete_section
                    )
                },
            ),
            permissions=[Unrestricted()],
            instance_selector_spec=SelectorSpec(
                kind=SelectorKind.RETRIEVE,
                selector=lambda *, pk: Catalog.objects.filter(pk=pk),
                reads=Parameters.of(Parameter("pk", "integer", required=True)),
            ),
        )
        with pytest.raises(ServiceValidationError):
            dispatch(
                spec, principal=User.objects.create(username="u"), arguments={"pk": catalog.pk}
            )
        # The run's transaction rolled the first section's delete back.
        assert sorted(Section.objects.values_list("title", flat=True)) == ["first", "refused"]
        assert Catalog.objects.filter(pk=catalog.pk).exists()
