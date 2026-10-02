from __future__ import annotations

from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_service_specs.output.audience_projection import AudienceProjection
from django_service_specs.output.audience_projection_for_spec import audience_projection_for_spec
from django_service_specs.output.field_audience import FieldAudience
from django_service_specs.output.field_marking import FieldMarking
from django_service_specs.output.output import Output
from django_service_specs.output.output_field import OutputField
from django_service_specs.output.presenter import Presenter
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from tests.dispatch.utils import OPEN, notes_of
from tests.output.utils import PRIORITIES, InvoicePresenter

STATUS_LABELS = {"PENDING_REVIEW": "Awaiting review", "PAID": "Paid"}


class Declares(Presenter):
    def __init__(self, output: Output) -> None:
        self._output = output

    def output(self) -> Output:
        return self._output

    def present(self, value: Any) -> Any:
        return value


def listing(presenter: Presenter | None) -> SelectorSpec:
    return SelectorSpec(
        kind=SelectorKind.LIST, selector=notes_of, permissions=OPEN, presenter=presenter
    )


def write(**_: Any) -> None:
    return None


def of(*fields: OutputField) -> AudienceProjection:
    return audience_projection_for_spec(listing(Declares(Output(fields))))


def test_reads_every_marking_choice_and_child_off_the_output() -> None:
    """The same projection the DRF-based walk reads off a serializer declaring
    these fields with these markings."""
    projection = audience_projection_for_spec(listing(InvoicePresenter()))

    assert {name: m.audience for name, m in projection.fields.items()} == {
        "id": FieldAudience.HANDLE,
        "number": FieldAudience.LABEL,
        "etag": FieldAudience.HIDDEN,
        "kind": FieldAudience.HANDLE,
    }
    assert projection.fields["number"].description == "The invoice number."
    assert projection.label == "number"
    assert projection.choice_labels == {
        "status": STATUS_LABELS,
        "kind": STATUS_LABELS,
        "tags": STATUS_LABELS,
        "priority": dict(PRIORITIES),
        "urgency": dict(PRIORITIES),
    }
    assert set(projection.nested) == {"lines", "customer"}
    assert projection.nested["lines"] == AudienceProjection(
        fields={"internal_cost": FieldMarking.hidden()}
    )
    assert projection.nested["customer"] == AudienceProjection(
        fields={"name": FieldMarking.label(), "secret": FieldMarking.hidden()}, label="name"
    )


def test_a_display_that_only_restates_its_value_is_not_a_label() -> None:
    projection = of(OutputField("n", "integer", choices=((1, "1"), (2, "Two"))))

    assert projection.choice_labels == {"n": {2: "Two"}}


def test_choices_whose_displays_add_nothing_are_not_collected() -> None:
    assert of(OutputField("n", "integer", choices=((1, "1"),))).is_empty()


def test_a_child_with_nothing_to_project_is_left_out() -> None:
    child = Output((OutputField("sku", "string"),))

    projection = of(
        OutputField("line", "object", fields=child),
        OutputField("lines", "array", items=child),
        OutputField("tags", "array", items="string"),
    )

    assert projection.is_empty()


def test_a_service_reads_the_presenter_it_is_presented_with() -> None:
    reread = listing(InvoicePresenter())
    spec = ServiceSpec(service=write, permissions=OPEN, output_selector_spec=reread)

    assert audience_projection_for_spec(spec) == audience_projection_for_spec(reread)


def test_a_spec_with_no_output_projects_nothing() -> None:
    assert audience_projection_for_spec(listing(None)) == AudienceProjection()


class TestLabels:
    def test_two_labels_are_refused(self) -> None:
        with pytest.raises(ImproperlyConfigured, match=r"Output: both 'a' and 'b' are marked"):
            of(
                OutputField("a", "string", marking=FieldMarking.label()),
                OutputField("b", "string", marking=FieldMarking.label()),
            )

    def test_two_labels_in_a_child_are_refused_by_its_path(self) -> None:
        child = Output(
            (
                OutputField("a", "string", marking=FieldMarking.label()),
                OutputField("b", "string", marking=FieldMarking.label()),
            )
        )
        grandchild = Output((OutputField("deeper", "object", fields=child),))

        with pytest.raises(ImproperlyConfigured, match=r"Output field 'author.deeper': both"):
            of(OutputField("author", "object", fields=grandchild))

    def test_one_label_beside_other_markings_is_the_label(self) -> None:
        projection = of(
            OutputField("id", "integer", marking=FieldMarking.handle()),
            OutputField("title", "string", marking=FieldMarking.label()),
        )

        assert projection.label == "title"


class TestOverrides:
    """A mount's own markings, layered over the declaration's."""

    def spec(self) -> SelectorSpec:
        return listing(
            Declares(
                Output(
                    (
                        OutputField("id", "integer", marking=FieldMarking.hidden()),
                        OutputField("title", "string", marking=FieldMarking.label()),
                        OutputField("status", "string", choices=(("a", "A"),)),
                    )
                )
            )
        )

    def test_an_override_replaces_the_declared_marking(self) -> None:
        projection = audience_projection_for_spec(
            self.spec(), overrides={"id": FieldMarking.handle()}
        )

        assert projection.audience("id") is FieldAudience.HANDLE
        assert projection.audience("title") is FieldAudience.LABEL
        assert projection.choice_labels == {"status": {"a": "A"}}

    def test_an_override_may_move_the_label(self) -> None:
        projection = audience_projection_for_spec(
            self.spec(), overrides={"title": FieldMarking(), "id": FieldMarking.label()}
        )

        assert projection.label == "id"

    def test_an_override_may_take_the_label_away(self) -> None:
        projection = audience_projection_for_spec(self.spec(), overrides={"title": FieldMarking()})

        assert projection.label is None

    def test_an_override_leaving_two_labels_is_refused_in_the_mounts_name(self) -> None:
        with pytest.raises(ImproperlyConfigured, match=r"Tool 'notes': overrides leave"):
            audience_projection_for_spec(
                self.spec(), overrides={"id": FieldMarking.label()}, name="Tool 'notes'"
            )

    def test_an_unnamed_mount_is_still_named_in_the_refusal(self) -> None:
        with pytest.raises(ImproperlyConfigured, match=r"^agent projection: overrides leave"):
            audience_projection_for_spec(self.spec(), overrides={"id": FieldMarking.label()})

    def test_an_override_reaches_a_spec_with_no_output(self) -> None:
        projection = audience_projection_for_spec(
            listing(None), overrides={"id": FieldMarking.hidden()}
        )

        assert projection.audience("id") is FieldAudience.HIDDEN

    def test_no_overrides_is_the_declaration_itself(self) -> None:
        spec = self.spec()

        assert audience_projection_for_spec(spec, overrides={}) == audience_projection_for_spec(
            spec
        )
