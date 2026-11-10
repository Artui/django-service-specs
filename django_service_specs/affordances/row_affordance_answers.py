from __future__ import annotations

from typing import Any

from django_service_specs.affordances.utils import answer_row_affordances, rendered_affordances
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource


def row_affordance_answers(
    spec: ServiceSpec | SelectorSpec | SpecSource, row: Any
) -> dict[str, dict[str, Any]]:
    """Each declared name's answer for ``row``: the object ``present`` puts on it."""
    return answer_row_affordances(row, rendered_affordances(kernel_spec(spec)) or {})
