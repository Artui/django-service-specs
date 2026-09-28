"""``delete_relations`` - the cascade, as a delete service calls it.

The rule itself (what is owned, what is only pointed at, the order) is held by
``test_delete_cascade``, against the shared core. These hold what the public
entry adds on top: the write helpers' signature and report, the map refused as
the write helpers refuse it, and ``context`` reaching the row services.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_service_specs.mutations.change_result import ChangeResult
from django_service_specs.mutations.delete_relations import delete_relations
from django_service_specs.relations.child_spec import ChildSpec
from django_service_specs.relations.forward_relation_spec import ForwardRelationSpec
from django_service_specs.relations.many_to_many_spec import ManyToManySpec
from django_service_specs.relations.reverse_one_to_one_spec import ReverseOneToOneSpec
from tests.relations_app.models import Author, Catalog, Item, Note, Post, Profile, Section, Tag


@pytest.mark.django_db
class TestTheReport:
    def test_collections_report_under_children_as_a_write_does(self) -> None:
        catalog = Catalog.objects.create(name="c")
        section = Section.objects.create(catalog=catalog, title="s")
        Item.objects.create(section=section, label="i")

        result = delete_relations(
            catalog,
            relations={
                "sections": ChildSpec(
                    Section, "catalog", relations={"items": ChildSpec(Item, "section")}
                )
            },
        )

        assert isinstance(result, ChangeResult)
        assert (result.instance, result.created, result.changes) == (catalog, False, ())
        change = result.get_child_change("sections")
        assert change is not None
        assert change.deleted == (section.pk,)
        assert result.relations == ()
        assert bool(result)
        # The instance itself is the service's to delete, after the cascade.
        assert Catalog.objects.filter(pk=catalog.pk).exists()
        assert not Item.objects.exists()

    def test_one_row_kinds_report_under_relations(self) -> None:
        author = Author.objects.create(name="a")
        profile = Profile.objects.create(author=author, bio="b")
        post = Post.objects.create(title="t", author=author)
        tag = Tag.objects.create(name="shared")
        post.tags.add(tag)

        from_author = delete_relations(
            author, relations={"profile": ReverseOneToOneSpec(Profile, "author")}
        )
        from_post = delete_relations(
            post,
            relations={
                "author": ForwardRelationSpec(Author),
                "tags": ManyToManySpec(Tag),
            },
        )

        profile_change = from_author.get_relation_change("profile")
        assert profile_change is not None
        assert (profile_change.outcome, profile_change.pk) == ("unlinked", profile.pk)
        author_change = from_post.get_relation_change("author")
        assert author_change is not None
        assert author_change.outcome == "untouched"
        tags_change = from_post.get_child_change("tags")
        assert tags_change is not None
        assert tags_change.unlinked == (tag.pk,)
        assert Tag.objects.filter(pk=tag.pk).exists()

    def test_a_map_with_nothing_to_remove_reports_nothing(self) -> None:
        catalog = Catalog.objects.create(name="c")

        result = delete_relations(catalog, relations={"sections": ChildSpec(Section, "catalog")})

        assert not result


@pytest.mark.django_db
class TestTheMap:
    def test_a_value_that_is_not_a_relation_spec_is_refused_as_a_write_refuses_it(
        self,
    ) -> None:
        catalog = Catalog.objects.create(name="c")
        section = Section.objects.create(catalog=catalog, title="s")
        not_a_spec: Any = {"model": Section, "fk": "catalog"}

        with pytest.raises(ImproperlyConfigured, match=r"relations\['sections'\] is a dict"):
            delete_relations(catalog, relations={"sections": not_a_spec})
        # Refused before anything was removed.
        assert Section.objects.filter(pk=section.pk).exists()

    def test_relations_is_keyword_only_like_the_write_helpers(self) -> None:
        catalog = Catalog.objects.create(name="c")
        call: Any = delete_relations

        with pytest.raises(TypeError):
            call(catalog, {"sections": ChildSpec(Section, "catalog")})


@pytest.mark.django_db
class TestContext:
    def test_context_reaches_every_row_service(self) -> None:
        catalog = Catalog.objects.create(name="c")
        note = Note.objects.create(catalog=catalog, body="n")
        seen: list[tuple[Any, Any, str]] = []

        def archive(*, instance: Note, parent: Catalog, tenant: str) -> None:
            seen.append((instance.pk, parent.pk, tenant))
            instance.delete()

        result = delete_relations(
            catalog,
            relations={"notes": ChildSpec(Note, "catalog", delete_service=archive)},
            context={"tenant": "acme"},
        )

        assert seen == [(note.pk, catalog.pk, "acme")]
        change = result.get_child_change("notes")
        assert change is not None
        assert change.removed == (note.pk,)
