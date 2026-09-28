from __future__ import annotations

from django_service_specs.output.field_audience import FieldAudience
from django_service_specs.output.field_marking import FieldMarking


def test_constructors_name_the_audience() -> None:
    assert FieldMarking() == FieldMarking(FieldAudience.CONTENT, None)
    assert FieldMarking.handle("opaque") == FieldMarking(FieldAudience.HANDLE, "opaque")
    assert FieldMarking.hidden() == FieldMarking(FieldAudience.HIDDEN)
    assert FieldMarking.label() == FieldMarking(FieldAudience.LABEL)


def test_audience_is_a_json_friendly_string() -> None:
    assert FieldAudience.HANDLE == "handle"
