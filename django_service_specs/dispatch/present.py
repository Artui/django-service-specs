from __future__ import annotations

import inspect
from typing import Any

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.affordances.utils import rendered_affordances, with_affordances
from django_service_specs.dispatch.dispatch_result import DispatchResult
from django_service_specs.dispatch.utils import sync_result
from django_service_specs.output.presentation_context import PresentationContext
from django_service_specs.output.presenter import Presenter
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource


def present(spec: ServiceSpec | SelectorSpec | SpecSource, result: DispatchResult) -> Any:
    """Render ``result.value`` as JSON-like data, the way ``spec`` declares it."""
    spec = kernel_spec(spec)
    if result.kind == "not_found":
        raise ValueError(
            "A not-found result has nothing to present. Answer it as the transport's own "
            "not-found before presenting."
        )
    presenter = spec.presenter_for_output() if isinstance(spec, ServiceSpec) else spec.presenter
    affordances = rendered_affordances(spec)
    if presenter is None and affordances is not None:
        raise ImproperlyConfigured(
            "affordances are projected into each presented object, and this spec declares "
            "no presenter to present one. Declare a presenter."
        )
    value = result.value
    if result.kind == "list":
        items = list(value)
        if presenter is None:
            return items
        payload = _presented_rows(presenter, items, result.context)
        if affordances is None:
            return payload
        return with_affordances(payload, items, affordances, many=True)
    if value is None or presenter is None:
        return value
    presented = _presented(presenter, value, result.context)
    if affordances is None:
        return presented
    return with_affordances(presented, value, affordances, many=False)


def _presented(presenter: Presenter, value: Any, context: PresentationContext | None) -> Any:
    """``presenter.presented(value, context)``, refusing an answer still to be awaited."""
    return _row(presenter, presenter.presented(value, context))


def _presented_rows(
    presenter: Presenter, items: list[Any], context: PresentationContext | None
) -> list[Any]:
    """``presenter.presented_rows(items, context)``, refusing an answer that does not line up."""
    asked = f"{type(presenter).__qualname__}.presented_rows"
    answer = sync_result(
        presenter.presented_rows(tuple(items), context), asked=asked, seat="A presenter"
    )
    if not isinstance(answer, list):
        raise ImproperlyConfigured(
            f"{asked} answered with {type(answer).__name__!r} where a list is expected. "
            "Return one presented value per row, in the order given."
        )
    if len(answer) != len(items):
        raise ImproperlyConfigured(
            f"{asked} answered with a list of {len(answer)} for {len(items)} rows. Return "
            "one presented value per row, in the order given: affordances are added to "
            "each presented row by its position."
        )
    try:
        return [_row(presenter, row) for row in answer]
    except ImproperlyConfigured:
        for row in answer:
            if inspect.iscoroutine(row):
                row.close()
        raise


def _row(presenter: Presenter, answer: Any) -> Any:
    """One presented row, refusing it while it is still to be awaited."""
    return sync_result(answer, asked=f"{type(presenter).__qualname__}.present", seat="A presenter")
