from __future__ import annotations

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_service_specs.mutations.acreate_from_input import acreate_from_input
from django_service_specs.mutations.aupdate_from_input import aupdate_from_input
from django_service_specs.mutations.create_from_input import create_from_input
from django_service_specs.mutations.update_from_input import update_from_input
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.relations.child_spec import ChildSpec
from django_service_specs.relations.forward_relation_spec import ForwardRelationSpec
from django_service_specs.relations.generic_relation_spec import GenericRelationSpec
from django_service_specs.relations.many_to_many_spec import ManyToManySpec
from django_service_specs.relations.reverse_one_to_one_spec import ReverseOneToOneSpec
from django_service_specs.services.service_validation_error import ServiceValidationError
from tests.relations_app.models import Attachment, Author, Catalog, Post, Profile, Section, Tag


@pytest.mark.django_db
class TestAMatchedRowMayCarryItsOwnKey:
    """One case per kind: match on the key, then write through the same row."""

    def test_forward_relation(self) -> None:
        author = Author.objects.create(name="Ursula")
        post = Post.objects.create(title="t", author=Author.objects.create(name="other"))

        update_from_input(
            post,
            {"author": {"pk": str(author.pk), "name": "renamed"}},
            relations={"author": ForwardRelationSpec(model=Author, scope=Author.objects.all())},
        )

        author.refresh_from_db()
        assert author.name == "renamed"

    def test_many_to_many(self) -> None:
        tag = Tag.objects.create(name="django")
        post = Post.objects.create(title="t")

        update_from_input(
            post,
            {"tags": [{"pk": str(tag.pk), "name": "renamed"}]},
            relations={"tags": ManyToManySpec(model=Tag, scope=Tag.objects.all())},
        )

        tag.refresh_from_db()
        assert tag.name == "renamed"
        assert list(post.tags.all()) == [tag]

    def test_reverse_foreign_key_child(self) -> None:
        catalog = Catalog.objects.create(name="c")
        section = Section.objects.create(catalog=catalog, title="s")

        update_from_input(
            catalog,
            {"sections": [{"pk": section.pk, "title": "renamed"}]},
            relations={"sections": ChildSpec(model=Section, fk="catalog")},
        )

        section.refresh_from_db()
        assert section.title == "renamed"

    def test_generic_relation(self) -> None:
        catalog = Catalog.objects.create(name="c")
        create_from_input(
            Catalog,
            {"name": "c2", "attachments": [{"label": "a"}]},
            relations={"attachments": GenericRelationSpec(model=Attachment)},
        )
        attachment = Attachment.objects.create(owner=catalog, label="a")

        update_from_input(
            catalog,
            {"attachments": [{"pk": attachment.pk, "label": "renamed"}]},
            relations={"attachments": GenericRelationSpec(model=Attachment)},
        )

        attachment.refresh_from_db()
        assert attachment.label == "renamed"

    def test_reverse_one_to_one(self) -> None:
        author = Author.objects.create(name="Ursula")
        profile = Profile.objects.create(author=author, bio="b")

        update_from_input(
            author,
            {"profile": {"pk": profile.pk, "bio": "renamed"}},
            relations={"profile": ReverseOneToOneSpec(model=Profile, fk="author")},
        )

        profile.refresh_from_db()
        assert profile.bio == "renamed"


@pytest.mark.django_db(transaction=True)
class TestTheAsyncWritersAgree:
    async def test_a_matched_row_may_carry_its_own_key(self) -> None:
        author = await Author.objects.acreate(name="Ursula")
        post = await Post.objects.acreate(title="t")

        await aupdate_from_input(
            post,
            {"author": {"pk": str(author.pk), "name": "renamed"}},
            relations={"author": ForwardRelationSpec(model=Author, scope=Author.objects.all())},
        )

        await author.arefresh_from_db()
        assert author.name == "renamed"

    async def test_a_matched_rows_write_fails_as_that_row(self) -> None:
        author = await Author.objects.acreate(name="Ursula")
        post = await Post.objects.acreate(title="t", author=author)

        with pytest.raises(InvalidArguments) as excinfo:
            await aupdate_from_input(
                author,
                {"posts": [{"pk": post.pk, "views": "not-a-number"}]},
                relations={"posts": ChildSpec(model=Post, fk="author")},
            )

        [message] = excinfo.value.detail["posts"][0]["non_field_errors"]
        assert "not-a-number" in message

    async def test_the_create_path_still_refuses_an_unmatched_key(self) -> None:
        with pytest.raises(ServiceValidationError):
            await acreate_from_input(
                Post,
                {"title": "t", "author": {"pk": 4242, "name": "x"}},
                relations={"author": ForwardRelationSpec(model=Author, scope=Author.objects.all())},
            )


@pytest.mark.django_db
class TestOnlyTheKeyIsDropped:
    def test_a_natural_match_key_still_renames_the_row_it_matched(self) -> None:
        # The narrow reading: an identifier is dropped, a description is not.
        catalog = Catalog.objects.create(name="c")
        section = Section.objects.create(catalog=catalog, title="original")

        update_from_input(
            catalog,
            {"sections": [{"title": "original"}, {"title": "second"}]},
            relations={"sections": ChildSpec(model=Section, fk="catalog", match_key="title")},
        )

        section.refresh_from_db()
        assert section.title == "original"
        assert Section.objects.filter(catalog=catalog).count() == 2

    def test_excluding_the_key_by_hand_is_harmless(self) -> None:
        # ``exclude_fields=[match_key]`` names a key the write drops anyway.
        author = Author.objects.create(name="Ursula")
        post = Post.objects.create(title="t")

        update_from_input(
            post,
            {"author": {"pk": str(author.pk), "name": "renamed"}},
            relations={
                "author": ForwardRelationSpec(
                    model=Author, scope=Author.objects.all(), exclude_fields=["pk"]
                )
            },
        )

        author.refresh_from_db()
        assert author.name == "renamed"

    def test_an_unmatched_key_is_still_refused_rather_than_dropped(self) -> None:
        # Dropping it on the *create* path would write a row under a key the caller never chose.
        catalog = Catalog.objects.create(name="c")

        with pytest.raises(ServiceValidationError) as excinfo:
            update_from_input(
                catalog,
                {"sections": [{"pk": 4242, "title": "x"}]},
                relations={"sections": ChildSpec(model=Section, fk="catalog")},
            )

        assert "did not match" in str(excinfo.value.detail)

    def test_a_key_the_row_never_sent_is_not_invented(self) -> None:
        # Nothing is read off the instance to stand in for the absent key.
        author = Author.objects.create(name="Ursula")
        post = Post.objects.create(title="t", author=author)

        update_from_input(
            post,
            {"author": {"name": "second"}},
            relations={"author": ForwardRelationSpec(model=Author)},
        )

        author.refresh_from_db()
        assert author.name == "Ursula"
        post.refresh_from_db()
        assert post.author is not None
        assert post.author.name == "second"


@pytest.mark.django_db
class TestAFieldMapOntoTheKeyIsRefusedWhereItWouldBeUnreachable:
    """The matcher does not apply ``field_map``; the primary-key guard does."""

    @pytest.mark.parametrize(
        ("spec", "kwargs"),
        [
            (ChildSpec, {"model": Section, "fk": "catalog"}),
            (ForwardRelationSpec, {"model": Author}),
            (ManyToManySpec, {"model": Tag}),
            (GenericRelationSpec, {"model": Attachment}),
        ],
    )
    def test_every_kind_that_matches_by_key_refuses_it(
        self, spec: type, kwargs: dict[str, object]
    ) -> None:
        with pytest.raises(ImproperlyConfigured) as excinfo:
            spec(field_map={"ident": "pk"}, **kwargs)

        assert "onto the primary key" in str(excinfo.value)

    def test_a_natural_match_key_leaves_the_same_mapping_usable(self) -> None:
        # ``ident`` is then an alias the guard reads and the matcher never needed.
        catalog = Catalog.objects.create(name="c")
        section = Section.objects.create(catalog=catalog, title="s")

        update_from_input(
            catalog,
            {"sections": [{"title": "s", "ident": section.pk}]},
            relations={
                "sections": ChildSpec(
                    model=Section, fk="catalog", match_key="title", field_map={"ident": "pk"}
                )
            },
        )

        assert Section.objects.filter(catalog=catalog).count() == 1

    def test_the_reverse_one_to_one_has_no_match_key_to_collide_with(self) -> None:
        # It finds its row through ``fk``.
        ReverseOneToOneSpec(model=Profile, fk="author", field_map={"ident": "pk"})


@pytest.mark.django_db
class TestARowsWriteFailsAsThatRow:
    def test_a_django_value_error_is_named_rather_than_escaping(self) -> None:
        # The backstop.
        author = Author.objects.create(name="Ursula")

        with pytest.raises(InvalidArguments) as excinfo:
            update_from_input(
                author,
                {"posts": [{"title": "a"}, {"title": "b", "views": "not-a-number"}]},
                relations={"posts": ChildSpec(model=Post, fk="author")},
            )

        detail = excinfo.value.detail
        assert list(detail["posts"]) == [1]
        [message] = detail["posts"][1]["non_field_errors"]
        assert "not-a-number" in message

    def test_a_matched_row_fails_as_that_row_too(self) -> None:
        # The update writer has its own translation.
        author = Author.objects.create(name="Ursula")
        post = Post.objects.create(title="t", author=author)

        with pytest.raises(InvalidArguments) as excinfo:
            update_from_input(
                author,
                {"posts": [{"pk": post.pk, "views": "not-a-number"}]},
                relations={"posts": ChildSpec(model=Post, fk="author")},
            )

        [message] = excinfo.value.detail["posts"][0]["non_field_errors"]
        assert "not-a-number" in message

    def test_a_row_services_own_value_error_is_left_alone(self) -> None:
        # Opaque caller code.
        def update_service(*, instance: Section, data: dict[str, object]) -> Section:
            raise ValueError("a bug in my service")

        catalog = Catalog.objects.create(name="c")
        section = Section.objects.create(catalog=catalog, title="s")

        with pytest.raises(ValueError, match="a bug in my service"):
            update_from_input(
                catalog,
                {"sections": [{"pk": section.pk, "title": "renamed"}]},
                relations={
                    "sections": ChildSpec(
                        model=Section, fk="catalog", update_service=update_service
                    )
                },
            )
