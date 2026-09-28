"""The relation taxonomy: one map, one ordering rule, one driver.

``relations=`` is the one map for every kind, and the order rows are written in
comes off the spec *class* — never off the order the mapping happens to be
spelled in.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_service_specs.mutations.acreate_from_input import acreate_from_input
from django_service_specs.mutations.aupdate_from_input import aupdate_from_input
from django_service_specs.mutations.create_from_input import create_from_input
from django_service_specs.mutations.update_from_input import update_from_input
from django_service_specs.mutations.utils import (
    POST_SAVE_PHASES,
    post_save_relations,
    relation_map,
    relations_in_phase,
)
from django_service_specs.relations.child_spec import ChildSpec
from django_service_specs.relations.relation_phase import RelationPhase
from django_service_specs.relations.relation_spec import RelationSpec
from tests.relations_app.models import Catalog, Item, Note, Section


class _GenericKind(RelationSpec):
    """A kind the driver has no writer for — stands in for a future one."""

    write_phase = RelationPhase.GENERIC


class _M2MKind(RelationSpec):
    write_phase = RelationPhase.M2M


class _ForwardKind(RelationSpec):
    write_phase = RelationPhase.FORWARD


_SECTIONS = ChildSpec(model=Section, fk="catalog")
_NOTES = ChildSpec(model=Note, fk="catalog")


class TestWriteOrderComesOffTheClass:
    def test_phases_run_in_the_taxonomy_order_not_the_mappings(self) -> None:
        declared: dict[str, RelationSpec] = {
            "m2m": _M2MKind(),
            "generic": _GenericKind(),
            "sections": _SECTIONS,
        }
        assert [name for name, _ in post_save_relations(declared)] == [
            "sections",
            "generic",
            "m2m",
        ]

    def test_declaration_order_still_decides_within_one_phase(self) -> None:
        declared: dict[str, RelationSpec] = {"notes": _NOTES, "sections": _SECTIONS}
        assert [name for name, _ in post_save_relations(declared)] == ["notes", "sections"]
        assert [name for name, _ in post_save_relations(dict(reversed(declared.items())))] == [
            "sections",
            "notes",
        ]

    def test_forward_is_not_a_post_save_phase(self) -> None:
        declared: dict[str, RelationSpec] = {"author": _ForwardKind(), "sections": _SECTIONS}
        assert [name for name, _ in post_save_relations(declared)] == ["sections"]
        assert RelationPhase.FORWARD not in POST_SAVE_PHASES
        assert [name for name, _ in relations_in_phase(declared, RelationPhase.FORWARD)] == [
            "author"
        ]

    def test_the_phase_belongs_to_the_class_not_the_instance(self) -> None:
        assert ChildSpec.write_phase is RelationPhase.REVERSE
        assert ChildSpec(model=Section, fk="catalog").write_phase is RelationPhase.REVERSE


class TestOneMap:
    def test_no_map_is_no_relations(self) -> None:
        assert relation_map(None) == {}

    def test_a_non_spec_value_is_refused_naming_the_relation(self) -> None:
        with pytest.raises(ImproperlyConfigured, match=r"relations\['sections'\] is a dict"):
            relation_map({"sections": {"model": Section}})  # type: ignore[arg-type]
        with pytest.raises(ImproperlyConfigured, match=r"relations\['sections'\] is a str"):
            relation_map({"sections": "Section"})  # type: ignore[arg-type]


@pytest.mark.django_db
class TestTheDriverIsTheSameOnEveryPath:
    def test_relations_writes_a_child_collection_on_create(self) -> None:
        payload: dict[str, Any] = {"name": "c", "sections": [{"title": "s"}]}
        result = create_from_input(Catalog, payload, relations={"sections": _SECTIONS})
        assert result.get_child_change("sections").created == (result.instance.sections.get().pk,)

    def test_relations_writes_a_child_collection_on_update(self) -> None:
        catalog = Catalog.objects.create(name="c")
        section = Section.objects.create(catalog=catalog, title="old")
        result = update_from_input(
            catalog,
            {"sections": [{"pk": section.pk, "title": "new"}]},
            relations={"sections": _SECTIONS},
        )
        assert result.get_child_change("sections").updated == (section.pk,)
        section.refresh_from_db()
        assert section.title == "new"

    def test_two_collections_in_one_map(self) -> None:
        result = create_from_input(
            Catalog,
            {"name": "c", "sections": [{"title": "s"}], "notes": [{"body": "n"}]},
            relations={"sections": _SECTIONS, "notes": _NOTES},
        )
        assert result.instance.sections.count() == 1
        assert result.instance.notes.count() == 1

    def test_an_unwritable_kind_names_the_relation(self) -> None:
        with pytest.raises(ImproperlyConfigured) as excinfo:
            create_from_input(Catalog, {"name": "c"}, relations={"tags": _M2MKind()})
        message = str(excinfo.value)
        assert "relations['tags']: _M2MKind is not a relation kind" in message

    def test_an_unwritable_forward_kind_is_refused_in_its_own_phase(self) -> None:
        with pytest.raises(ImproperlyConfigured, match=r"relations\['owner'\]: _ForwardKind"):
            create_from_input(Catalog, {"name": "c"}, relations={"owner": _ForwardKind()})

    def test_a_grandchild_is_declared_in_the_childs_relations(self) -> None:
        result = create_from_input(
            Catalog,
            {"name": "c", "sections": [{"title": "s", "items": [{"label": "i"}]}]},
            relations={
                "sections": ChildSpec(
                    model=Section,
                    fk="catalog",
                    relations={"items": ChildSpec(model=Item, fk="section")},
                )
            },
        )
        assert Item.objects.get().label == "i"
        assert result.instance.sections.get().items.count() == 1


@pytest.mark.django_db(transaction=True)
class TestTheDriverIsTheSameOnTheAsyncPath:
    async def test_relations_writes_a_child_collection(self) -> None:
        result = await acreate_from_input(
            Catalog,
            {"name": "c", "sections": [{"title": "s"}]},
            relations={"sections": _SECTIONS},
        )
        assert await result.instance.sections.acount() == 1

    async def test_update_reconciles_through_the_same_map(self) -> None:
        catalog = await Catalog.objects.acreate(name="c")
        section = await Section.objects.acreate(catalog=catalog, title="old")
        result = await aupdate_from_input(
            catalog,
            {"sections": [{"pk": section.pk, "title": "new"}]},
            relations={"sections": _SECTIONS},
        )
        assert result.get_child_change("sections").updated == (section.pk,)

    async def test_an_unwritable_kind_names_the_relation(self) -> None:
        with pytest.raises(ImproperlyConfigured, match=r"relations\['tags'\]: _M2MKind"):
            await acreate_from_input(Catalog, {"name": "c"}, relations={"tags": _M2MKind()})

    async def test_an_unwritable_forward_kind_is_refused_in_its_own_phase(self) -> None:
        with pytest.raises(ImproperlyConfigured, match=r"relations\['owner'\]: _ForwardKind"):
            await acreate_from_input(Catalog, {"name": "c"}, relations={"owner": _ForwardKind()})
