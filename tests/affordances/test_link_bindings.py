from __future__ import annotations

import gc
import sys
from dataclasses import dataclass
from typing import Annotated, Any

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_service_specs.adapters.dataclass.dataclass_presenter import DataclassPresenter
from django_service_specs.affordances.link_bindings import link_bindings
from django_service_specs.output.field_marking import FieldMarking
from django_service_specs.output.output import OutputField
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.spec_link import SpecLink
from tests.affordances.links import (
    PK,
    RENAME,
    TENANT,
    NoOutput,
    Rows,
    listing,
    service,
    target,
    tenant_of,
)
from tests.dispatch.utils import EDIT, OPEN, Record


class TestInference:
    def test_a_required_read_binds_the_handle_field_and_a_same_name_read_its_field(self) -> None:
        assert link_bindings(listing({"rename": RENAME})) == {
            "rename": {"pk": "id", "title": "title"}
        }

    def test_a_bare_spec_and_its_link_bind_alike(self) -> None:
        assert link_bindings(listing({"rename": SpecLink(RENAME)})) == link_bindings(
            listing({"rename": RENAME})
        )

    def test_a_same_name_field_wins_over_the_handle(self) -> None:
        spec = listing({"rename": RENAME}, presenter=Rows(OutputField("pk", "integer")))
        assert link_bindings(spec) == {"rename": {"pk": "pk", "title": "title"}}

    def test_an_explicit_argument_wins_over_both(self) -> None:
        spec = listing({"rename": SpecLink(RENAME, arguments={"pk": "id", "title": "id"})})
        assert link_bindings(spec) == {"rename": {"pk": "id", "title": "id"}}

    def test_an_optional_read_with_no_field_of_its_name_is_left_unbound(self) -> None:
        spec = listing({"rename": service(PK, own=(PK.__class__("note", "string"),))})
        assert link_bindings(spec) == {"rename": {"pk": "id"}}

    def test_a_read_the_targets_kwargs_fills_is_not_required(self) -> None:
        filled = service().derive(instance_selector_spec=target(PK, TENANT, kwargs=tenant_of))
        assert link_bindings(listing({"rename": filled})) == {"rename": {"pk": "id"}}

    def test_a_target_with_no_reads_binds_nothing(self) -> None:
        assert link_bindings(listing({"edit": EDIT})) == {"edit": {}}

    def test_a_service_spec_binds_through_its_output_selector(self) -> None:
        spec = ServiceSpec(
            service=Record(),
            permissions=OPEN,
            output_selector_spec=listing({"rename": RENAME}).derive(permissions=None),
        )
        assert link_bindings(spec) == {"rename": {"pk": "id", "title": "title"}}

    def test_a_spec_presenting_no_affordances_binds_nothing(self) -> None:
        assert link_bindings(listing(None)) == {}
        assert link_bindings(listing({})) == {}
        assert link_bindings(ServiceSpec(service=Record(), permissions=OPEN)) == {}

    def test_with_no_output_only_explicit_arguments_bind(self) -> None:
        spec = listing({"rename": SpecLink(RENAME, arguments={"pk": "anything"})}, NoOutput())
        assert link_bindings(spec) == {"rename": {"pk": "anything"}}


class TestRefusals:
    def refusal(self, spec: Any) -> str:
        with pytest.raises(ImproperlyConfigured) as refused:
            link_bindings(spec)
        return str(refused.value)

    def test_a_required_read_left_unbound(self) -> None:
        two = service(PK, PK.__class__("slug", "string", required=True))
        assert self.refusal(listing({"rename": two})) == (
            "SelectorSpec.affordances['rename'] leads to a spec requiring ['pk', 'slug'], and no "
            "output field is named for them or marked HANDLE. Bind them: "
            "SpecLink(spec, arguments={read: field})."
        )

    def test_a_required_read_and_no_handle_field(self) -> None:
        @dataclass
        class Plain:
            title: str

        message = self.refusal(listing({"rename": RENAME}, DataclassPresenter(Plain)))
        assert "requiring ['pk'], and no output field is named for them or marked HANDLE" in message

    def test_a_required_read_with_no_output(self) -> None:
        assert self.refusal(listing({"rename": RENAME}, NoOutput())) == (
            "SelectorSpec.affordances['rename'] leads to a spec requiring ['pk'], and the spec "
            "declares no output, so only SpecLink arguments bind. Bind them: "
            "SpecLink(spec, arguments={read: field})."
        )

    def test_an_ambiguous_match_of_two_handle_fields(self) -> None:
        second = OutputField("uuid", "string", marking=FieldMarking.handle())
        assert self.refusal(listing({"rename": RENAME}, Rows(second))) == (
            "SelectorSpec.affordances['rename'] leaves 'pk' to the output's HANDLE field, and it "
            "marks ['id', 'uuid']. Name one: SpecLink(spec, arguments={'pk': ...})."
        )

    def test_a_field_the_output_does_not_declare(self) -> None:
        link = SpecLink(RENAME, arguments={"pk": "slug"})
        assert self.refusal(listing({"rename": link})) == (
            "SelectorSpec.affordances['rename'] binds 'pk' to 'slug', which the output does not "
            "declare; it declares ['id', 'title', 'owner_id']."
        )

    def test_a_hidden_field_named_explicitly(self) -> None:
        link = SpecLink(RENAME, arguments={"pk": "owner_id"})
        assert self.refusal(listing({"rename": link})) == (
            "SelectorSpec.affordances['rename'] binds 'pk' to 'owner_id', which the output marks "
            "HIDDEN. A link's arguments reach its caller, and a hidden field is plumbing."
        )

    def test_a_hidden_field_is_never_inferred(self) -> None:
        owner = service(PK.__class__("owner_id", "integer", required=True))
        assert link_bindings(listing({"owner": owner})) == {"owner": {"owner_id": "id"}}
        both = service(PK, PK.__class__("owner_id", "integer", required=True))
        assert "requiring ['pk', 'owner_id']" in self.refusal(listing({"both": both}))

    def test_every_problem_is_named_in_one_message(self) -> None:
        message = self.refusal(
            listing(
                {
                    "rename": SpecLink(RENAME, arguments={"pk": "slug"}),
                    "move": SpecLink(RENAME, arguments={"pk": "owner_id"}),
                }
            )
        )
        assert "['rename'] binds 'pk' to 'slug'" in message
        assert "['move'] binds 'pk' to 'owner_id'" in message


class TestTheCache:
    def test_bindings_are_answered_once_and_handed_out_as_copies(self) -> None:
        presenter = Rows()
        calls: list[None] = []
        answer = presenter.output

        def counted() -> Any:
            calls.append(None)
            return answer()

        presenter.output = counted  # ty: ignore[invalid-assignment]
        spec = listing({"rename": RENAME}, presenter)
        first = link_bindings(spec)
        first["rename"]["pk"] = "changed"
        assert link_bindings(spec) == {"rename": {"pk": "id", "title": "title"}}
        assert len(calls) == 1

    def test_a_refusal_is_not_kept_so_a_later_output_binds(self) -> None:
        @dataclass
        class Row:
            id: Annotated[int, FieldMarking.handle()]
            owner: Later  # noqa: F821

        spec = listing({"rename": RENAME}, DataclassPresenter(Row))
        with pytest.raises(ImproperlyConfigured, match="not importable"):
            link_bindings(spec)
        globals()["Later"] = int
        try:
            assert link_bindings(spec) == {"rename": {"pk": "id"}}
        finally:
            del globals()["Later"]

    def test_an_entry_goes_with_its_spec(self) -> None:
        spec = listing({"rename": RENAME})
        link_bindings(spec)
        key = id(spec)
        assert key in sys.modules[link_bindings.__module__]._BOUND
        del spec
        gc.collect()
        assert key not in sys.modules[link_bindings.__module__]._BOUND


def test_construction_never_reads_the_output() -> None:
    @dataclass
    class Row:
        id: Annotated[int, FieldMarking.handle()]
        owner: NotYet  # noqa: F821

    listing(
        {"rename": SpecLink(RENAME, arguments={"pk": "id", "title": "missing"})},
        DataclassPresenter(Row),
    )
