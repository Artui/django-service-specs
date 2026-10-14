"""``SpecSource``: each entry point the registry page names is declared to take a source too."""

from __future__ import annotations

import inspect

import pytest

import django_service_specs
from django_service_specs.dispatch.grant import Grant
from django_service_specs.http.utils import SpecViewBase

# The entry points docs/registry.md names as taking a source.
ENTRY_POINTS = [
    "adispatch",
    "adispatch_request",
    "aenforce_affordances",
    "apresent",
    "audience_projection_for_spec",
    "aunmet_operation_affordance",
    "authorize",
    "authorize_scope",
    "authorize_target",
    "bind_arguments",
    "can_present_nothing",
    "check_call",
    "check_requested_input",
    "dispatch",
    "dispatch_request",
    "enforce_affordances",
    "kernel_spec",
    "operation_affordances",
    "present",
    "present_for_audience",
    "resolve_target",
    "server_owned_keys",
    "shape_queryset",
    "spec_input_schema",
    "spec_output_schema",
    "unmet_operation_affordance",
]


@pytest.mark.parametrize("name", ENTRY_POINTS)
def test_each_named_entry_point_is_annotated_to_take_a_source(name: str) -> None:
    # What a type checker reads: a function that compiles a source but is
    # annotated for a spec alone makes every caller holding a declaration
    # write a cast, or call kernel_spec itself and lose nothing it could see.
    annotation = (
        inspect.signature(getattr(django_service_specs, name)).parameters["spec"].annotation
    )

    assert "SpecSource" in str(annotation)


def test_a_grant_is_annotated_to_hold_a_source() -> None:
    assert "SpecSource" in str(Grant.__dataclass_fields__["spec"].type)


def test_a_spec_view_is_annotated_to_serve_a_source() -> None:
    # SpecView and AsyncSpecView both take their ``spec`` from here.
    assert "SpecSource" in SpecViewBase.__annotations__["spec"]
