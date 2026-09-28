"""What a row's write raises, and where the caller finds it.

A service in a relation slot raises about *its* row. These assert the error
arrives under the relation that carried it — at the right position when the
relation holds many rows, keyed by its ``int`` index — and that what the service
actually said survives the trip. The tree itself is
``test_relation_error_shape.py``'s business.

The services here refuse the row marked ``"rude"`` and write the others, so a
reported position is measured against rows that really did pass.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

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
from tests.relations_app.models import (
    Attachment,
    Author,
    Catalog,
    Item,
    Post,
    Profile,
    Section,
    Tag,
)

_RUDE: dict[str, Any] = {"title": ["Too rude."]}


def _writes_all_but_the_rude_row(model: Any, detail: Any = None) -> Any:
    """A create service that refuses one row of an incoming set and writes the rest."""

    def service(*, data: dict[str, Any]) -> Any:
        if "rude" in data.values():
            raise ServiceValidationError(_RUDE if detail is None else detail)
        return model.objects.create(**data)

    return service


def _awrites_all_but_the_rude_row(model: Any, detail: Any = None) -> Any:
    """The async twin of :func:`_writes_all_but_the_rude_row`."""

    async def service(*, data: dict[str, Any]) -> Any:
        if "rude" in data.values():
            raise ServiceValidationError(_RUDE if detail is None else detail)
        return await model.objects.acreate(**data)

    return service


def _refuses(detail: Any = None) -> Any:
    """A row service that refuses whatever it is handed."""

    def service(**_: Any) -> None:
        raise ServiceValidationError(_RUDE if detail is None else detail)

    return service


def _arefuses(detail: Any = None) -> Any:
    """The async twin of :func:`_refuses`."""

    async def service(**_: Any) -> None:
        raise ServiceValidationError(_RUDE if detail is None else detail)

    return service


@pytest.mark.django_db
class TestACollectionSaysWhichRow:
    def test_a_create_lands_at_its_index(self) -> None:
        with pytest.raises(ServiceValidationError) as excinfo:
            create_from_input(
                Catalog,
                {"name": "c", "sections": [{"title": "ok"}, {"title": "rude"}, {"title": "fine"}]},
                relations={
                    "sections": ChildSpec(
                        model=Section,
                        fk="catalog",
                        create_service=_writes_all_but_the_rude_row(Section),
                    )
                },
            )
        # Keyed by the failing row's index in the payload, and by nothing else:
        # the rows that passed are not listed.
        assert excinfo.value.detail == {"sections": {1: _RUDE}}

    def test_an_update_lands_at_its_index(self) -> None:
        catalog = Catalog.objects.create(name="c")
        section = Section.objects.create(catalog=catalog, title="old")

        with pytest.raises(ServiceValidationError) as excinfo:
            update_from_input(
                catalog,
                {"sections": [{"title": "new"}, {"pk": section.pk, "title": "rude"}]},
                relations={
                    "sections": ChildSpec(model=Section, fk="catalog", update_service=_refuses())
                },
            )
        assert excinfo.value.detail == {"sections": {1: _RUDE}}

    def test_a_generic_relation_reports_the_same_way(self) -> None:
        with pytest.raises(ServiceValidationError) as excinfo:
            create_from_input(
                Catalog,
                {"name": "c", "attachments": [{"label": "ok"}, {"label": "rude"}]},
                relations={
                    "attachments": GenericRelationSpec(
                        model=Attachment,
                        create_service=_writes_all_but_the_rude_row(
                            Attachment, {"label": ["Nope."]}
                        ),
                    )
                },
            )
        assert excinfo.value.detail == {"attachments": {1: {"label": ["Nope."]}}}

    def test_a_many_to_many_target_reports_the_same_way(self) -> None:
        catalog = Catalog.objects.create(name="c")
        section = Section.objects.create(catalog=catalog, title="s")

        with pytest.raises(ServiceValidationError) as excinfo:
            update_from_input(
                section,
                {"tags": [{"name": "ok"}, {"name": "rude"}]},
                relations={
                    "tags": ManyToManySpec(
                        model=Tag, create_service=_writes_all_but_the_rude_row(Tag)
                    )
                },
            )
        assert excinfo.value.detail == {"tags": {1: _RUDE}}


@pytest.mark.django_db
class TestASingularRelationSaysItsName:
    def test_a_reverse_one_to_one_reports_under_the_relation(self) -> None:
        with pytest.raises(ServiceValidationError) as excinfo:
            create_from_input(
                Author,
                {"name": "a", "profile": {"bio": "..."}},
                relations={
                    "profile": ReverseOneToOneSpec(
                        model=Profile,
                        fk="author",
                        create_service=_refuses({"bio": ["Too long."]}),
                    )
                },
            )
        # No index: the relation holds one row, so there is no position to give.
        assert excinfo.value.detail == {"profile": {"bio": ["Too long."]}}

    def test_a_forward_relation_reports_under_the_relation(self) -> None:
        with pytest.raises(ServiceValidationError) as excinfo:
            create_from_input(
                Post,
                {"title": "t", "author": {"name": "a"}},
                relations={
                    "author": ForwardRelationSpec(
                        model=Author, create_service=_refuses({"name": ["Too short."]})
                    )
                },
            )
        assert excinfo.value.detail == {"author": {"name": ["Too short."]}}

    def test_an_update_service_reports_under_the_relation(self) -> None:
        author = Author.objects.create(name="a")
        Profile.objects.create(author=author, bio="before")

        with pytest.raises(ServiceValidationError) as excinfo:
            update_from_input(
                author,
                {"profile": {"bio": "after"}},
                relations={
                    "profile": ReverseOneToOneSpec(
                        model=Profile,
                        fk="author",
                        update_service=_refuses({"bio": ["Too long."]}),
                    )
                },
            )
        assert excinfo.value.detail == {"profile": {"bio": ["Too long."]}}

    def test_the_parents_own_field_is_told_apart_from_the_rows(self) -> None:
        # The collision this exists to end: a service refusing a section's
        # ``title`` used to arrive looking exactly like the catalog's own.
        with pytest.raises(ServiceValidationError) as excinfo:
            create_from_input(
                Catalog,
                {"name": "c", "sections": [{"title": "rude"}]},
                relations={
                    "sections": ChildSpec(model=Section, fk="catalog", create_service=_refuses())
                },
            )
        assert excinfo.value.detail == {"sections": {0: _RUDE}}


@pytest.mark.django_db
class TestTheNamesNest:
    def test_a_grandchilds_error_carries_both_relations(self) -> None:
        with pytest.raises(ServiceValidationError) as excinfo:
            create_from_input(
                Catalog,
                {
                    "name": "c",
                    "sections": [{"title": "s", "items": [{"label": "ok"}, {"label": "rude"}]}],
                },
                relations={
                    "sections": ChildSpec(
                        model=Section,
                        fk="catalog",
                        relations={
                            "items": ChildSpec(
                                model=Item,
                                fk="section",
                                create_service=_writes_all_but_the_rude_row(
                                    Item, {"label": ["No."]}
                                ),
                            )
                        },
                    )
                },
            )
        # In the order a reader walks them: the parent's relation outermost.
        assert excinfo.value.detail == {"sections": {0: {"items": {1: {"label": ["No."]}}}}}

    def test_the_primary_key_guard_is_not_named_twice(self) -> None:
        # It addresses its own refusal, so the row writer leaves it alone: the
        # relation and the row once each, then the message.
        catalog = Catalog.objects.create(name="c")

        with pytest.raises(ServiceValidationError) as excinfo:
            update_from_input(
                catalog,
                {"sections": [{"pk": 4242, "title": "t"}]},
                relations={"sections": ChildSpec(model=Section, fk="catalog")},
            )
        detail = excinfo.value.detail
        assert isinstance(detail, dict)
        assert list(detail) == ["sections"]
        assert list(detail["sections"]) == [0]
        [message] = detail["sections"][0]["non_field_errors"]
        assert message.startswith("references Section [4242]")

    def test_a_grandchilds_unmatched_reference_carries_both_rows(self) -> None:
        with pytest.raises(ServiceValidationError) as excinfo:
            create_from_input(
                Catalog,
                {
                    "name": "c",
                    "sections": [
                        {"title": "a"},
                        {"title": "b", "items": [{"label": "ok"}, {"pk": 4242, "label": "x"}]},
                    ],
                },
                relations={
                    "sections": ChildSpec(
                        model=Section,
                        fk="catalog",
                        relations={"items": ChildSpec(model=Item, fk="section")},
                    )
                },
            )
        detail = excinfo.value.detail
        assert isinstance(detail, dict)
        assert list(detail["sections"]) == [1]
        assert list(detail["sections"][1]) == ["items"]
        assert list(detail["sections"][1]["items"]) == [1]
        [message] = detail["sections"][1]["items"][1]["non_field_errors"]
        assert message.startswith("references Item [4242]")


@pytest.mark.django_db(transaction=True)
class TestAnUnmatchedReferenceSaysWhichRow:
    """The primary-key guard addresses its row the way every other row failure does.

    Read through the row's ``int`` index. The row's complaint is the message
    alone, under ``non_field_errors``: the guard names the relation once, not
    again inside the row.
    """

    def test_the_refused_row_is_addressed_by_its_index(self) -> None:
        catalog = Catalog.objects.create(name="c")
        stranger = Section.objects.create(catalog=Catalog.objects.create(name="other"), title="s")

        with pytest.raises(ServiceValidationError) as excinfo:
            update_from_input(
                catalog,
                {"sections": [{"title": "new"}, {"pk": stranger.pk, "title": "mine"}]},
                relations={"sections": ChildSpec(model=Section, fk="catalog")},
            )
        detail = excinfo.value.detail
        assert isinstance(detail, dict)
        assert list(detail) == ["sections"]
        [message] = detail["sections"][1]["non_field_errors"]
        assert message.startswith(f"references Section [{stranger.pk}], which this write")

    async def test_the_async_path_addresses_it_too(self) -> None:
        catalog = await Catalog.objects.acreate(name="c")
        other = await Catalog.objects.acreate(name="other")
        stranger = await Section.objects.acreate(catalog=other, title="s")

        with pytest.raises(ServiceValidationError) as excinfo:
            await aupdate_from_input(
                catalog,
                {"sections": [{"title": "new"}, {"pk": stranger.pk, "title": "mine"}]},
                relations={"sections": ChildSpec(model=Section, fk="catalog")},
            )
        detail = excinfo.value.detail
        assert isinstance(detail, dict)
        [message] = detail["sections"][1]["non_field_errors"]
        assert message.startswith(f"references Section [{stranger.pk}], which this write")

    def test_a_key_outside_scope_is_addressed_by_its_index(self) -> None:
        # The other refusal of the library's own that a row can earn: a scoped
        # kind's match key naming nothing it may write.
        catalog = Catalog.objects.create(name="c")
        section = Section.objects.create(catalog=catalog, title="s")

        with pytest.raises(ServiceValidationError) as excinfo:
            update_from_input(
                section,
                {"tags": [{"name": "new"}, {"pk": 4242, "name": "x"}]},
                relations={"tags": ManyToManySpec(model=Tag, scope=Tag.objects.all())},
            )
        detail = excinfo.value.detail
        assert isinstance(detail, dict)
        assert list(detail) == ["tags"]
        [message] = detail["tags"][1]["non_field_errors"]
        assert message.startswith("No Tag with pk=4242 is available to write")

    async def test_the_async_scope_refusal_is_addressed_too(self) -> None:
        catalog = await Catalog.objects.acreate(name="c")
        section = await Section.objects.acreate(catalog=catalog, title="s")

        with pytest.raises(ServiceValidationError) as excinfo:
            await aupdate_from_input(
                section,
                {"tags": [{"name": "new"}, {"pk": 4242, "name": "x"}]},
                relations={"tags": ManyToManySpec(model=Tag, scope=Tag.objects.all())},
            )
        detail = excinfo.value.detail
        assert isinstance(detail, dict)
        [message] = detail["tags"][1]["non_field_errors"]
        assert message.startswith("No Tag with pk=4242 is available to write")


@pytest.mark.django_db
class TestWhatTheServiceSaidSurvives:
    def test_a_string_detail_is_the_rows_own_message(self) -> None:
        with pytest.raises(ServiceValidationError) as excinfo:
            create_from_input(
                Catalog,
                {"name": "c", "sections": [{"title": "t"}]},
                relations={
                    "sections": ChildSpec(
                        model=Section, fk="catalog", create_service=_refuses("Too rude.")
                    )
                },
            )
        # A message about the row rather than a field of it: under
        # ``non_field_errors`` inside the row, as a one-item list.
        assert excinfo.value.detail == {"sections": {0: {"non_field_errors": ["Too rude."]}}}

    def test_a_list_detail_is_the_rows_own_messages(self) -> None:
        with pytest.raises(ServiceValidationError) as excinfo:
            create_from_input(
                Author,
                {"name": "a", "profile": {"bio": "..."}},
                relations={
                    "profile": ReverseOneToOneSpec(
                        model=Profile,
                        fk="author",
                        create_service=_refuses(["Too long.", "Too loud."]),
                    )
                },
            )
        # A single row has no index, so the messages sit under the relation.
        assert excinfo.value.detail == {"profile": {"non_field_errors": ["Too long.", "Too loud."]}}

    def test_invalid_arguments_from_a_row_service_stays_invalid_arguments(self) -> None:
        # A row service that validates its row refuses the arguments, and naming
        # the relation is no reason to turn that into a business refusal.
        def service(**_: Any) -> None:
            raise InvalidArguments({"title": ["Too rude."]})

        with pytest.raises(InvalidArguments) as excinfo:
            create_from_input(
                Catalog,
                {"name": "c", "sections": [{"title": "t"}]},
                relations={
                    "sections": ChildSpec(model=Section, fk="catalog", create_service=service)
                },
            )
        assert excinfo.value.detail == {"sections": {0: {"title": ["Too rude."]}}}

    def test_an_error_that_is_not_about_validation_is_left_alone(self) -> None:
        def service(**_: Any) -> None:
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            create_from_input(
                Catalog,
                {"name": "c", "sections": [{"title": "t"}]},
                relations={
                    "sections": ChildSpec(model=Section, fk="catalog", create_service=service)
                },
            )


@pytest.mark.django_db(transaction=True)
class TestTheAsyncPathReportsIdentically:
    async def test_an_async_create_lands_at_its_index(self) -> None:
        with pytest.raises(ServiceValidationError) as excinfo:
            await acreate_from_input(
                Catalog,
                {"name": "c", "sections": [{"title": "ok"}, {"title": "rude"}]},
                relations={
                    "sections": ChildSpec(
                        model=Section,
                        fk="catalog",
                        create_service=_awrites_all_but_the_rude_row(Section),
                    )
                },
            )
        assert excinfo.value.detail == {"sections": {1: _RUDE}}

    async def test_an_async_update_reports_under_the_relation(self) -> None:
        author = await Author.objects.acreate(name="a")
        await Profile.objects.acreate(author=author, bio="before")

        with pytest.raises(ServiceValidationError) as excinfo:
            await aupdate_from_input(
                author,
                {"profile": {"bio": "after"}},
                relations={
                    "profile": ReverseOneToOneSpec(
                        model=Profile,
                        fk="author",
                        update_service=_arefuses({"bio": ["Too long."]}),
                    )
                },
            )
        assert excinfo.value.detail == {"profile": {"bio": ["Too long."]}}

    async def test_an_async_grandchild_carries_both_relations(self) -> None:
        with pytest.raises(ServiceValidationError) as excinfo:
            await acreate_from_input(
                Catalog,
                {
                    "name": "c",
                    "sections": [{"title": "s", "items": [{"label": "ok"}, {"label": "rude"}]}],
                },
                relations={
                    "sections": ChildSpec(
                        model=Section,
                        fk="catalog",
                        relations={
                            "items": ChildSpec(
                                model=Item,
                                fk="section",
                                create_service=_awrites_all_but_the_rude_row(
                                    Item, {"label": ["No."]}
                                ),
                            )
                        },
                    )
                },
            )
        assert excinfo.value.detail == {"sections": {0: {"items": {1: {"label": ["No."]}}}}}


@pytest.mark.django_db
class TestDjangosOwnWriteFailuresRefuseTheArguments:
    """What Django raises when a row's data cannot be written, on the helper path.

    None of it carries a tree, so each becomes a refusal of the arguments with
    Django's message as the row's own; the ``ValueError`` arm is pinned in
    ``test_matched_row_shaping.py``.
    """

    def test_a_key_the_model_has_no_field_for_is_named_at_its_row(self) -> None:
        # ``TypeError`` from the model's constructor.
        with pytest.raises(InvalidArguments) as excinfo:
            create_from_input(
                Catalog,
                {"name": "c", "sections": [{"title": "ok"}, {"title": "t", "bogus": 1}]},
                relations={"sections": ChildSpec(model=Section, fk="catalog")},
            )

        assert list(excinfo.value.detail["sections"]) == [1]
        [message] = excinfo.value.detail["sections"][1]["non_field_errors"]
        assert "bogus" in message

    def test_a_value_the_field_cannot_coerce_is_named_by_its_message(self) -> None:
        # A ``ValidationError`` from the field's ``to_python``, read for its
        # messages rather than for the repr of the list ``str()`` would give.
        with pytest.raises(InvalidArguments) as excinfo:
            create_from_input(
                Author,
                {"name": "a", "posts": [{"title": "t", "published": "maybe"}]},
                relations={"posts": ChildSpec(model=Post, fk="author")},
            )

        [message] = excinfo.value.detail["posts"][0]["non_field_errors"]
        assert message.startswith("“maybe”")

    def test_a_field_keyed_validation_error_keeps_its_fields(self) -> None:
        # A model whose ``save()`` runs ``full_clean()`` names the field, and the
        # row's tree addresses it the way a validator would.
        refusal = ValidationError({"title": ["Not this one."]})

        with (
            patch.object(Section, "save", side_effect=refusal),
            pytest.raises(InvalidArguments) as excinfo,
        ):
            create_from_input(
                Catalog,
                {"name": "c", "sections": [{"title": "t"}]},
                relations={"sections": ChildSpec(model=Section, fk="catalog")},
            )

        assert excinfo.value.detail == {"sections": {0: {"title": ["Not this one."]}}}

    def test_an_integrity_error_is_left_alone(self) -> None:
        # A constraint is a conflict with rows that exist rather than a shape,
        # and the backend's message can quote another row's values.
        conflict = IntegrityError("UNIQUE constraint failed")

        with (
            patch.object(Section, "save", side_effect=conflict),
            pytest.raises(IntegrityError) as excinfo,
        ):
            create_from_input(
                Catalog,
                {"name": "c", "sections": [{"title": "t"}]},
                relations={"sections": ChildSpec(model=Section, fk="catalog")},
            )

        assert excinfo.value is conflict


def _nested_items(**item_spec: Any) -> dict[str, ChildSpec]:
    """``sections`` written by the helpers, each carrying ``items`` per ``item_spec``."""
    return {
        "sections": ChildSpec(
            model=Section,
            fk="catalog",
            relations={"items": ChildSpec(model=Item, fk="section", **item_spec)},
        )
    }


@pytest.mark.django_db
class TestCallerCodeIsNeverTranslated:
    """A bug in caller code two levels down is not the outer row's data failing.

    Every helper-path row translates Django's write failures, and a nested row's
    caller code raises into the ``try`` of every row above it. Each test puts the
    caller code one level below a row the helpers write, which is the only place
    the translation could reach it, and asserts the caller gets back the very
    exception it raised.
    """

    def test_a_create_service_under_a_created_row(self) -> None:
        bug = TypeError("a bug in my service")

        def service(**_: Any) -> None:
            raise bug

        with pytest.raises(TypeError) as excinfo:
            create_from_input(
                Catalog,
                {"name": "c", "sections": [{"title": "s", "items": [{"label": "i"}]}]},
                relations=_nested_items(create_service=service),
            )

        assert excinfo.value is bug

    def test_a_create_service_under_a_matched_row(self) -> None:
        # The update writer's translation, reached through a matched section.
        bug = ValueError("a bug in my service")
        catalog = Catalog.objects.create(name="c")
        section = Section.objects.create(catalog=catalog, title="s")

        def service(**_: Any) -> None:
            raise bug

        with pytest.raises(ValueError) as excinfo:
            update_from_input(
                catalog,
                {"sections": [{"pk": section.pk, "items": [{"label": "i"}]}]},
                relations=_nested_items(create_service=service),
            )

        assert excinfo.value is bug

    def test_a_scope_callable_under_a_created_row(self) -> None:
        bug = TypeError("a bug in my scope")
        tag = Tag.objects.create(name="t")

        def scope() -> Any:
            raise bug

        with pytest.raises(TypeError) as excinfo:
            create_from_input(
                Author,
                {"name": "a", "posts": [{"title": "p", "tags": [{"pk": tag.pk}]}]},
                relations={
                    "posts": ChildSpec(
                        model=Post,
                        fk="author",
                        relations={"tags": ManyToManySpec(model=Tag, scope=scope)},
                    )
                },
            )

        assert excinfo.value is bug

    def test_an_m2m_callable_under_a_created_row(self) -> None:
        bug = ValidationError("a bug in my m2m callable")

        def m2m(row: Any) -> dict[str, Any]:
            raise bug

        with pytest.raises(ValidationError) as excinfo:
            create_from_input(
                Post,
                {"title": "p", "author": {"name": "a", "posts": [{"title": "q"}]}},
                relations={
                    "author": ForwardRelationSpec(
                        model=Author,
                        relations={"posts": ChildSpec(model=Post, fk="author", m2m=m2m)},
                    )
                },
            )

        assert excinfo.value is bug


@pytest.mark.django_db(transaction=True)
class TestTheAsyncPathLeavesCallerCodeAlone:
    async def test_a_create_service_under_a_created_row(self) -> None:
        bug = TypeError("a bug in my service")

        async def service(**_: Any) -> None:
            raise bug

        with pytest.raises(TypeError) as excinfo:
            await acreate_from_input(
                Catalog,
                {"name": "c", "sections": [{"title": "s", "items": [{"label": "i"}]}]},
                relations=_nested_items(create_service=service),
            )

        assert excinfo.value is bug

    async def test_a_create_service_under_a_matched_row(self) -> None:
        bug = ValueError("a bug in my service")
        catalog = await Catalog.objects.acreate(name="c")
        section = await Section.objects.acreate(catalog=catalog, title="s")

        async def service(**_: Any) -> None:
            raise bug

        with pytest.raises(ValueError) as excinfo:
            await aupdate_from_input(
                catalog,
                {"sections": [{"pk": section.pk, "items": [{"label": "i"}]}]},
                relations=_nested_items(create_service=service),
            )

        assert excinfo.value is bug

    async def test_djangos_own_failure_is_still_translated(self) -> None:
        # The mark is what separates the two, so the async helper path must
        # still translate what nobody marked.
        with pytest.raises(InvalidArguments) as excinfo:
            await acreate_from_input(
                Catalog,
                {"name": "c", "sections": [{"title": "t", "bogus": 1}]},
                relations={"sections": ChildSpec(model=Section, fk="catalog")},
            )

        [message] = excinfo.value.detail["sections"][0]["non_field_errors"]
        assert "bogus" in message
