"""``operation_affordances`` - the affordances a spec declares that need no row."""

from __future__ import annotations

from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.affordance import Affordance
from django_service_specs.types.utils import is_row_condition


def operation_affordances(spec: ServiceSpec | SelectorSpec) -> tuple[Affordance, ...]:
    """The operation-scope affordances ``spec`` declares, in declaration order.

    The callable ones: the conditions answered without a row. A condition on the
    row is left out, and so is anything on a ``SelectorSpec``, which answers
    ``()``: its ``affordances`` maps names to *other* operations, to be answered
    for its rows, and reading that mapping as the selector's own conditions
    would answer a question about some other operation. A spec declaring none
    answers ``()`` too.

    A transport uses this to decide cheaply whether there is anything to ask at
    list time before it builds a pool: most operations declare nothing, and an
    empty answer means
    [`unmet_operation_affordance`][django_service_specs.affordances.unmet_operation_affordance.unmet_operation_affordance]
    would return ``None`` without running anything. That function selects its
    conditions here, so a transport's shortcut and the answer it skips cannot
    disagree about which conditions there are.
    """
    if isinstance(spec, SelectorSpec):
        return ()
    return tuple(
        affordance for affordance in spec.affordances or () if not is_row_condition(affordance.when)
    )
