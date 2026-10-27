"""``row_affordance_answers`` - what can be done to one row, read off the row."""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.affordances.utils import answer_row_affordances, rendered_affordances
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource
from django_service_specs.specs.utils import callable_name


def row_affordance_answers(
    spec: ServiceSpec | SelectorSpec | SpecSource, row: Any
) -> dict[str, dict[str, Any]]:
    """Each declared name's answer for ``row``: the object ``present`` puts on it.

    ``dispatch`` answers a selector's affordances for every row it returns, as
    ``affordance__<name>__<code>`` values on the row. A page that holds those
    rows rather than presented dicts - a queryset's instances, a table's rows -
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

    Raises:
        ImproperlyConfigured: ``spec`` presents no affordances, which is
            refused rather than answered ``{}`` so that a page asking whether
            an action is available cannot read every action as absent from a
            spec that never declared them - the check ``present`` makes before
            adding the object. An explicit empty ``affordances`` mapping
            presents an empty object, and answers ``{}``. Or ``row`` carries
            no answer for a declared name, because it did not come through the
            selector declaring them.
    """
    spec = kernel_spec(spec)
    affordances = rendered_affordances(spec)
    # ``None`` and not falsy, as ``present`` tests it, so a page and a
    # presented row agree on which specs carry answers: an empty mapping is a
    # declaration (test_an_empty_mapping_is_a_declaration_and_answers_empty).
    if affordances is None:
        # A service spec's own conditions are the ones it is checked against;
        # naming that is the way out for the likeliest cause.
        callable_of = spec.service if isinstance(spec, ServiceSpec) else spec.selector
        raise ImproperlyConfigured(
            f"{type(spec).__name__} for {callable_name(callable_of)} presents no affordances, "
            "so there is no answer to read from a row. A SelectorSpec declares them in its "
            "affordances mapping, and a ServiceSpec presents its output_selector_spec's: "
            "the affordances a ServiceSpec declares itself are conditions it is checked "
            "against, never presented."
        )
    return answer_row_affordances(row, affordances)
