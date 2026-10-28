"""``row_affordance_answers`` - what can be done to one row, read off the row."""

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
    """Each declared name's answer for ``row``: the object ``present`` puts on it.

    ``dispatch`` answers a selector's affordances for every row it returns, as
    ``affordance__<name>__<code>`` values on the row. A page that holds those
    rows rather than presented dicts - a queryset's instances, a table's records -
    reads them here, whichever kind of spec it holds: a ``SelectorSpec``, a
    ``ServiceSpec`` (read through its output selector, whose ``affordances``
    are the ones presented), or a
    [`SpecSource`][django_service_specs.specs.spec_source.SpecSource].

    The result maps each name to ``{"available": bool}``, plus ``code`` and
    ``reason`` when it is ``False``. Each name reports the first condition the
    row does not meet, in declaration order, as the call would refuse. A
    ``None`` answer is a condition on the row asked of a row that no longer
    exists: ``{"available": False}`` with no code and no reason, and the walk
    stops there. It is the same reading ``present`` and ``with_affordances``
    make of a row, because they call the same function.

    A spec that presents no affordances answers ``{}``, as ``present`` leaves
    the ``affordances`` key out of what it presents. A caller asking about a name
    the answer does not hold must treat it as not declared; the answer cannot
    tell a name the spec never declared from a spec that declares none.

    Raises:
        ImproperlyConfigured: ``row`` carries no answer for a declared name
            that has a condition, because it did not come through the selector
            declaring them. A name whose spec declares no conditions reads no
            flag, and is available for any row.
    """
    # ``or {}`` is the whole of the no-affordances case: a spec presenting none
    # has no mapping at all, and an empty mapping is no different to a reader
    # (test_a_spec_presenting_none_answers_empty fails without it).
    return answer_row_affordances(row, rendered_affordances(kernel_spec(spec)) or {})
