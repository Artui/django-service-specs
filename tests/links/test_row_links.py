from __future__ import annotations

from typing import Annotated, Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from pydantic import BaseModel, Field

from django_service_specs.adapters.pydantic.pydantic_presenter import PydanticPresenter
from django_service_specs.affordances.row_affordance_answers import row_affordance_answers
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.dispatch.present import present
from django_service_specs.links.row_links import row_links
from django_service_specs.links.utils import required_reads
from django_service_specs.output.field_marking import FieldMarking
from django_service_specs.output.output import OutputField
from django_service_specs.parameters.parameters import Parameter
from django_service_specs.registry.spec_registry import SpecRegistry
from django_service_specs.schema.spec_output_schema import spec_output_schema
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.types.spec_link import SpecLink
from tests.dispatch.utils import EDIT, make_user
from tests.dispatch_app.models import Note
from tests.links.links import PK, RENAME, TITLE, Declarer, Rows, listing, service

ARCHIVED = {
    "available": False,
    "code": "note_archived",
    "reason": "An archived note cannot be renamed.",
}


def spec_of(**affordances: Any) -> SelectorSpec:
    return listing(affordances or {"rename": RENAME, "edit": SpecLink(EDIT)})


def presented(spec: SelectorSpec, user: Any) -> tuple[list[Any], list[Any]]:
    result = dispatch(spec, principal=user, arguments={})
    return list(result.value), present(spec, result)


class AliasedRow(BaseModel):
    id: Annotated[int, FieldMarking.handle()] = Field(serialization_alias="note_id")
    title: str


@pytest.fixture
def notes() -> tuple[Any, Note, Note]:
    ada = make_user("ada")
    live = Note.objects.create(owner=ada, title="live")
    archived = Note.objects.create(owner=ada, title="archived", archived=True)
    return ada, live, archived


@pytest.mark.django_db
class TestALink:
    def test_a_presented_item_answers_availability_target_and_bound_values(
        self, notes: Any
    ) -> None:
        ada, live, archived = notes
        spec = spec_of()
        _, (first, second) = presented(spec, ada)

        assert row_links(spec, first) == {
            "rename": {
                "available": True,
                "spec": RENAME,
                "arguments": {"pk": live.pk, "title": "live"},
                "required": ("pk",),
            },
            "edit": {"available": True, "spec": EDIT, "arguments": {}, "required": ()},
        }
        assert row_links(spec, second)["rename"] == {
            **ARCHIVED,
            "spec": RENAME,
            "arguments": {"pk": archived.pk, "title": "archived"},
            "required": ("pk",),
        }
        assert row_links(spec, first)["rename"]["spec"] is RENAME

    def test_it_agrees_with_row_affordance_answers(self, notes: Any) -> None:
        ada, *_ = notes
        spec = spec_of()
        rows, items = presented(spec, ada)
        for row, item in zip(rows, items, strict=True):
            answers = row_affordance_answers(spec, row)
            for links in (row_links(spec, item), row_links(spec, row)):
                assert {
                    name: {
                        k: v for k, v in link.items() if k not in ("spec", "arguments", "required")
                    }
                    for name, link in links.items()
                } == answers

    def test_a_raw_row_is_answered_and_read_by_attribute(self, notes: Any) -> None:
        ada, live, _ = notes
        spec = spec_of()
        rows, items = presented(spec, ada)
        assert row_links(spec, rows[0]) == row_links(spec, items[0])
        assert row_links(spec, rows[0])["rename"]["arguments"] == {"pk": live.pk, "title": "live"}

    def test_a_field_the_item_does_not_carry_is_left_out(self, notes: Any) -> None:
        ada, live, _ = notes
        spec = spec_of()
        _, items = presented(spec, ada)
        item = {k: v for k, v in items[0].items() if k != "title"}
        assert row_links(spec, item)["rename"]["arguments"] == {"pk": live.pk}

    def test_a_bare_spec_and_its_link_present_and_describe_alike(self, notes: Any) -> None:
        ada, *_ = notes
        bare, linked = listing({"rename": RENAME}), listing({"rename": SpecLink(RENAME)})
        assert presented(bare, ada)[1] == presented(linked, ada)[1]
        assert spec_output_schema(bare) == spec_output_schema(linked)

    def test_a_raw_mapping_row_is_answered_off_its_own_keys(self) -> None:
        spec = listing({"rename": RENAME})
        row = {"id": 7, "title": "t", "affordance__rename__note_archived": False}
        assert row_links(spec, row) == {
            "rename": {
                **ARCHIVED,
                "spec": RENAME,
                "arguments": {"pk": 7, "title": "t"},
                "required": ("pk",),
            }
        }

    def test_a_raw_row_missing_a_required_reads_field_raises(self, notes: Any) -> None:
        ada, live, _ = notes
        spec = listing({"rename": RENAME}, PydanticPresenter(AliasedRow))
        rows, items = presented(spec, ada)
        assert row_links(spec, items[0])["rename"]["arguments"] == {
            "pk": live.pk,
            "title": "live",
        }
        with pytest.raises(ImproperlyConfigured) as refused:
            row_links(spec, rows[0])
        assert str(refused.value).startswith(
            "SelectorSpec.affordances['rename'] binds a required read to ['note_id'], which a "
            "Note row does not carry."
        )

    def test_required_names_the_reads_a_transport_reverses_with(self) -> None:
        spec = listing({"rename": RENAME})
        row = {"id": 7, "title": "old", "affordances": {"rename": {"available": True}}}
        link = row_links(spec, row)["rename"]
        assert link["arguments"] == {"pk": 7, "title": "old"}
        assert link["required"] == ("pk",)
        assert {read: link["arguments"][read] for read in link["required"]} == {"pk": 7}

    def test_required_is_required_reads_and_never_an_optional_target_read(self) -> None:
        loose = service(PK, Parameter("slug", "string"), own=(TITLE,))
        affordances = {"rename": RENAME, "loose": loose, "edit": SpecLink(EDIT)}
        spec = listing(affordances, Rows(OutputField("slug", "string")))
        answers = dict.fromkeys(affordances, {"available": True})
        row = {"id": 7, "title": "t", "slug": "s", "affordances": answers}
        links = row_links(spec, row)
        assert links["loose"]["arguments"] == {"pk": 7, "slug": "s", "title": "t"}
        for name, declared in affordances.items():
            assert links[name]["required"] == required_reads(declared)
        assert links["loose"]["required"] == ("pk",)
        assert links["edit"]["required"] == ()

    def test_a_spec_presenting_no_affordances_answers_nothing(self, notes: Any) -> None:
        assert row_links(listing(None), {"id": 1}) == {}

    def test_a_link_that_cannot_bind_raises(self) -> None:
        spec = listing({"rename": SpecLink(RENAME, arguments={"pk": "slug"})})
        with pytest.raises(ImproperlyConfigured, match="binds 'pk' to 'slug'"):
            row_links(spec, {"id": 1, "affordances": {"rename": {"available": True}}})


@pytest.mark.django_db
class TestNamesFromARegistry:
    def test_a_registered_target_is_named_and_an_unregistered_one_is_not(self, notes: Any) -> None:
        ada, *_ = notes
        spec = spec_of()
        registry = SpecRegistry()
        registry.register("rename_note", RENAME)
        _, items = presented(spec, ada)

        links = row_links(spec, items[0], registry=registry)
        assert links["rename"]["name"] == "rename_note"
        assert "name" not in links["edit"]
        assert "name" not in row_links(spec, items[0])["rename"]

    def test_a_replaced_entry_still_names_the_spec_the_affordance_holds(self, notes: Any) -> None:
        ada, *_ = notes
        spec = spec_of()
        registry = SpecRegistry()
        registry.register("rename_note", RENAME)
        variant = registry.replace("rename_note", RENAME.derive(idempotent=True))
        _, items = presented(spec, ada)
        assert row_links(spec, items[0], registry=variant)["rename"]["name"] == "rename_note"

    def test_a_target_under_two_names_raises(self, notes: Any) -> None:
        ada, *_ = notes
        spec = spec_of()
        registry = SpecRegistry()
        registry.register("rename_note", RENAME)
        registry.register("rename", RENAME)
        _, items = presented(spec, ada)
        with pytest.raises(ValueError, match="no one name"):
            row_links(spec, items[0], registry=registry)

    def test_a_target_that_is_no_service_spec_is_never_named(self, notes: Any) -> None:
        ada, *_ = notes
        spec = spec_of(other=Declarer())
        _, items = presented(spec, ada)
        links = row_links(spec, items[0], registry=SpecRegistry())
        assert links == {
            "other": {
                "available": True,
                "spec": spec.affordances["other"],  # ty: ignore[non-subscriptable]
                "arguments": {},
                "required": (),
            }
        }
