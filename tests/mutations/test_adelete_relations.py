"""``adelete_relations`` - the async cascade, as a delete service awaits it.

The same three things ``test_delete_relations`` holds for the sync entry: the
report, the map refused as the write helpers refuse it, and ``context``
reaching the row services, which must be ``async def`` here.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_service_specs.mutations.adelete_relations import adelete_relations
from django_service_specs.mutations.change_result import ChangeResult
from django_service_specs.relations.child_spec import ChildSpec
from django_service_specs.relations.forward_relation_spec import ForwardRelationSpec
from django_service_specs.relations.reverse_one_to_one_spec import ReverseOneToOneSpec
from tests.relations_app.models import Author, Catalog, Item, Note, Post, Profile, Section


@pytest.mark.django_db(transaction=True)
class TestTheReport:
    async def test_collections_under_children_and_one_row_kinds_under_relations(
        self,
    ) -> None:
        catalog = await Catalog.objects.acreate(name="c")
        section = await Section.objects.acreate(catalog=catalog, title="s")
        await Item.objects.acreate(section=section, label="i")
        author = await Author.objects.acreate(name="a")
        profile = await Profile.objects.acreate(author=author, bio="b")
        post = await Post.objects.acreate(title="t", author=author)

        from_catalog = await adelete_relations(
            catalog,
            relations={
                "sections": ChildSpec(
                    Section, "catalog", relations={"items": ChildSpec(Item, "section")}
                )
            },
        )
        from_author = await adelete_relations(
            author, relations={"profile": ReverseOneToOneSpec(Profile, "author")}
        )
        from_post = await adelete_relations(post, relations={"author": ForwardRelationSpec(Author)})

        assert isinstance(from_catalog, ChangeResult)
        assert (from_catalog.instance, from_catalog.created) == (catalog, False)
        assert from_catalog.changes == ()
        sections = from_catalog.get_child_change("sections")
        assert sections is not None
        assert sections.deleted == (section.pk,)
        assert not await Item.objects.aexists()
        profile_change = from_author.get_relation_change("profile")
        assert profile_change is not None
        assert (profile_change.outcome, profile_change.pk) == ("unlinked", profile.pk)
        forward = from_post.get_relation_change("author")
        assert forward is not None
        assert forward.outcome == "untouched"


@pytest.mark.django_db(transaction=True)
class TestTheMap:
    async def test_a_value_that_is_not_a_relation_spec_is_refused(self) -> None:
        catalog = await Catalog.objects.acreate(name="c")
        not_a_spec: Any = {"model": Section, "fk": "catalog"}

        with pytest.raises(ImproperlyConfigured, match=r"relations\['sections'\] is a dict"):
            await adelete_relations(catalog, relations={"sections": not_a_spec})


@pytest.mark.django_db(transaction=True)
class TestContext:
    async def test_context_reaches_an_async_row_service(self) -> None:
        catalog = await Catalog.objects.acreate(name="c")
        note = await Note.objects.acreate(catalog=catalog, body="n")
        seen: list[tuple[Any, Any, str]] = []

        async def archive(*, instance: Note, parent: Catalog, tenant: str) -> None:
            seen.append((instance.pk, parent.pk, tenant))
            await instance.adelete()

        result = await adelete_relations(
            catalog,
            relations={"notes": ChildSpec(Note, "catalog", delete_service=archive)},
            context={"tenant": "acme"},
        )

        assert seen == [(note.pk, catalog.pk, "acme")]
        change = result.get_child_change("notes")
        assert change is not None
        assert change.removed == (note.pk,)
