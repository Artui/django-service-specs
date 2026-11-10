from __future__ import annotations

import django_service_specs.selectors


def test_the_selector_helpers_are_public() -> None:
    # A transport that runs a selector without ``dispatch`` - a chain step running each spec itself.
    names = {
        "arun_selector",
        "amaterialize_retrieve",
        "is_queryset",
        "materialize_retrieve",
        "run_selector",
        "shape_queryset",
    }
    assert names <= set(django_service_specs.selectors.__all__)
