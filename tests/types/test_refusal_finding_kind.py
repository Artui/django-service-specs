from __future__ import annotations

from django_service_specs.types.refusal_finding_kind import RefusalFindingKind


def test_each_kind_is_the_value_a_transport_filters_by() -> None:
    # A transport may filter by the plain string, so renaming a value is a
    # breaking change this pins.
    assert {member.name: member.value for member in RefusalFindingKind} == {
        "UNANSWERED": "unanswered",
        "BARE_BASE": "bare_base",
        "SHADOWED_ROW": "shadowed_row",
    }
    assert RefusalFindingKind.BARE_BASE == "bare_base"
