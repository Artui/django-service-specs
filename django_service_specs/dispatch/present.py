"""``present`` - render what a dispatch produced, through the spec's presenter."""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.affordances.utils import rendered_affordances, with_affordances
from django_service_specs.dispatch.dispatch_result import DispatchResult
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec


def present(spec: ServiceSpec | SelectorSpec, result: DispatchResult) -> Any:
    """Render ``result.value`` as JSON-like data, the way ``spec`` declares it.

    The presenter is a selector spec's own, or a service spec's
    ``presenter_for_output()``: its own, or its output selector's when it
    declares none.

    - ``kind="list"``: each item through the presenter, into a list. With no
      presenter the items are returned as they are, but still in a list: a
      queryset is evaluated here rather than handed back lazily, because
      ``apresent``'s caller is on the event loop, where the first iteration of
      an unevaluated queryset is a query Django refuses to run.
    - ``kind="instance"``: the value through the presenter. With no presenter,
      or a value of ``None`` - an ``allow_none`` retrieve that found nothing, a
      service that returned nothing - the value as it is. ``None`` is not a
      row, and asking a presenter to render one produces either a crash or an
      object of blank fields indistinguishable from a real row.

    **Affordances.** When the selector spec presented through declares
    ``affordances`` - a selector spec's own, or a service spec's output
    selector's, never a service spec's own, which are what its call is checked
    against - each presented object gains an ``affordances`` key: per declared
    name, ``{"available": true}``, or ``{"available": false, "code": ...,
    "reason": ...}`` naming the first condition the row does not meet, or a
    bare ``{"available": false}`` for a row deleted before its answers were
    asked, which fails no condition and so has no sentence to report. ``None``
    is not a row and carries none. The answers are read off the rows as the
    selector's dispatch left them - annotations on a queryset's rows, or the
    answers it attached to rows a selector returned directly - so presenting
    them costs no query. A spec declaring none presents exactly as before.

    Raises:
        ValueError: ``kind="not_found"``. Presenting nothing as a success is the
            bug this refuses; the transport answers a not-found in its own
            terms (a 404, an exit code, a tool error) and never presents it.
        ImproperlyConfigured: The spec declares ``affordances`` and no presenter
            to present them through; a presented row is not an object, or
            already has an ``affordances`` key; or a row carries no answer,
            because it did not come through the selector that declares them.
    """
    if result.kind == "not_found":
        raise ValueError(
            "A not-found result has nothing to present. Answer it as the transport's own "
            "not-found before presenting."
        )
    presenter = spec.presenter_for_output() if isinstance(spec, ServiceSpec) else spec.presenter
    affordances = rendered_affordances(spec)
    # Before anything is presented, so a spec declaring answers with nothing to
    # present them through is refused whatever the value, ``None`` included.
    # One branch to coverage, so each condition is held by its own test:
    # test_each_presented_row_carries_its_answers (the first) and
    # test_a_service_spec_with_its_own_affordances_and_no_output_selector_is_untouched
    # (the second).
    if presenter is None and affordances is not None:
        raise ImproperlyConfigured(
            "affordances are projected into each presented object, and this spec declares "
            "no presenter to present one. Declare a presenter."
        )
    value = result.value
    if result.kind == "list":
        # Materialised once, so the rows walked for the answers are the rows
        # presented, in the same order.
        items = list(value)
        if presenter is None:
            return items
        payload = [presenter.present(item) for item in items]
        if affordances is None:
            return payload
        return with_affordances(payload, items, affordances, many=True)
    # One branch to coverage, so each condition is held by its own test:
    # test_a_none_value_is_not_handed_to_the_presenter (the first) and
    # test_an_instance_with_no_presenter_is_returned_as_it_is (the second).
    if value is None or presenter is None:
        return value
    presented = presenter.present(value)
    if affordances is None:
        return presented
    return with_affordances(presented, value, affordances, many=False)
