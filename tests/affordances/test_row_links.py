from __future__ import annotations

from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_service_specs.affordances.row_affordance_answers import row_affordance_answers
from django_service_specs.affordances.row_links import row_links
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.dispatch.present import present
from django_service_specs.registry.spec_registry import SpecRegistry
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.types.spec_link import SpecLink
from tests.affordances.links import RENAME, Declarer, listing
from tests.dispatch.utils import EDIT, make_user
from tests.dispatch_app.models import Note

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
            },
            "edit": {"available": True, "spec": EDIT, "arguments": {}},
        }
        assert row_links(spec, second)["rename"] == {
            **ARCHIVED,
            "spec": RENAME,
            "arguments": {"pk": archived.pk, "title": "archived"},
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
                    name: {k: v for k, v in link.items() if k not in ("spec", "arguments")}
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
            "other": {"available": True, "spec": spec.affordances["other"], "arguments": {}}
        }  # ty: ignore[non-subscriptable]
