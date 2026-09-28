"""``present`` - render what a dispatch produced, through the spec's presenter."""

from __future__ import annotations

from typing import Any

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

    Raises:
        ValueError: ``kind="not_found"``. Presenting nothing as a success is the
            bug this refuses; the transport answers a not-found in its own
            terms (a 404, an exit code, a tool error) and never presents it.
    """
    if result.kind == "not_found":
        raise ValueError(
            "A not-found result has nothing to present. Answer it as the transport's own "
            "not-found before presenting."
        )
    presenter = spec.presenter_for_output() if isinstance(spec, ServiceSpec) else spec.presenter
    value = result.value
    if result.kind == "list":
        items = list(value)
        return items if presenter is None else [presenter.present(item) for item in items]
    # One branch to coverage, so each condition is held by its own test:
    # test_a_none_value_is_not_handed_to_the_presenter (the first) and
    # test_an_instance_with_no_presenter_is_returned_as_it_is (the second).
    if value is None or presenter is None:
        return value
    return presenter.present(value)
