from __future__ import annotations

import dataclasses

import pytest

from django_service_specs.output.audience_projection import AudienceProjection
from django_service_specs.output.field_audience import FieldAudience
from django_service_specs.output.field_marking import FieldMarking
from django_service_specs.types.value_formatter import ValueFormatter

MONEY = ValueFormatter(str, produces="string")


def test_a_default_projection_is_empty() -> None:
    assert AudienceProjection().is_empty()


# ``is_empty`` is one ``or``-chain, so each term is held by its own case: the
# term a case names is the only one that is set in it.
@pytest.mark.parametrize(
    "projection",
    [
        pytest.param(AudienceProjection(fields={"id": FieldMarking.handle()}), id="fields"),
        pytest.param(AudienceProjection(label="title"), id="label"),
        pytest.param(AudienceProjection(choice_labels={"status": {"a": "A"}}), id="choice-labels"),
        pytest.param(
            AudienceProjection(
                nested={"author": AudienceProjection(fields={"pk": FieldMarking.hidden()})}
            ),
            id="nested",
        ),
    ],
)
def test_each_term_alone_makes_it_non_empty(projection: AudienceProjection) -> None:
    assert not projection.is_empty()


def test_an_empty_child_leaves_it_empty() -> None:
    assert AudienceProjection(nested={"author": AudienceProjection()}).is_empty()


def test_audience_defaults_to_content() -> None:
    projection = AudienceProjection(fields={"id": FieldMarking.handle()})

    assert projection.audience("id") is FieldAudience.HANDLE
    assert projection.audience("title") is FieldAudience.CONTENT


class TestFormatter:
    def test_an_unmarked_field_has_none(self) -> None:
        """The first condition of the suppression: no marking, no formatter."""
        projection = AudienceProjection(fields={"amount": FieldMarking.formatted(MONEY)})

        assert projection.formatter("other") is None

    def test_a_marked_field_has_its_markings(self) -> None:
        projection = AudienceProjection(
            fields={"amount": FieldMarking.formatted(MONEY), "id": FieldMarking.handle()}
        )

        assert projection.formatter("amount") is MONEY
        assert projection.formatter("id") is None

    def test_a_handle_has_none_however_it_was_declared(self) -> None:
        """The second condition of the suppression: a handle is another
        tool's input, and a formatted identifier is a broken one."""
        projection = AudienceProjection(
            fields={"id": FieldMarking(FieldAudience.HANDLE, formatter=MONEY)}
        )

        assert projection.formatter("id") is None


def test_a_projection_is_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        AudienceProjection().label = "title"  # type: ignore[misc]
