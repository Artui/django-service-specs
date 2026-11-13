from __future__ import annotations

import inspect
from typing import Any

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.affordances.utils import (
    rendered_affordances,
    rendering_selector,
    with_affordances,
)
from django_service_specs.dispatch.dispatch_result import DispatchResult
from django_service_specs.dispatch.utils import sync_result
from django_service_specs.output.presentation_context import PresentationContext
from django_service_specs.output.presenter import Presenter
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource


def present(spec: ServiceSpec | SelectorSpec | SpecSource, result: DispatchResult) -> Any:
    """Render ``result.value`` as JSON-like data, the way ``spec`` declares it.

    The presenter is a selector spec's own, or a service spec's
    ``presenter_for_output()``: its own, or its output selector's when it
    declares none.

    - ``kind="list"``: every item through the presenter's ``presented_rows()``
      in one call, which presents each in turn unless the presenter batches
      over them. To serve a page, hand ``present`` a result holding the page's
      rows, and those are the rows it receives. With no
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
    them costs no query. A spec declaring none presents what its presenter
    answers, untouched.

    **The call's context.** Each value is handed to the presenter's
    ``presented()``, or a list's to its ``presented_rows()``, with
    ``result.context``, the
    [`PresentationContext`][django_service_specs.output.presentation_context.PresentationContext]
    dispatch built for the call, or ``None`` on a result it did not build.
    ``presented()`` is ``present()`` unless overridden, so a Presenter that
    reads nothing of the call needs only ``present()``. Every value of one
    result is handed the same context, so a list's rows, and a nested
    presenter a presenter hands it on to, share its ``call_context`` - the
    dict the transport created for the call - and read the arguments that
    shape the output from its ``shapes``. A spec declaring no ``shapes`` and
    a presenter reading neither present exactly as before.

    Raises:
        ValueError: ``kind="not_found"``. Presenting nothing as a success is the
            bug this refuses; the transport answers a not-found in its own
            terms (a 404, an exit code, a tool error) and never presents it.
        ImproperlyConfigured: The spec declares ``affordances`` and no presenter
            to present them through; a presented row is not an object, or
            already has an ``affordances`` key; or a row carries no answer,
            because it did not come through the selector that declares them.
            Also a presenter answering with a coroutine or an async generator,
            which is never awaited, so it is refused rather than handed back
            as the payload; and a ``presented_rows()`` answering with anything
            but a list of one presented value per row.
    """
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
    selector = rendering_selector(spec)
    row_object = selector.row_object if selector is not None else None
    value = result.value
    if result.kind == "list":
        items = list(value)
        if presenter is None:
            return items
        payload = _presented_rows(presenter, items, result.context)
        if affordances is None:
            return payload
        return with_affordances(payload, items, affordances, many=True, row_object=row_object)
    if value is None or presenter is None:
        return value
    presented = _presented(presenter, value, result.context)
    if affordances is None:
        return presented
    return with_affordances(presented, value, affordances, many=False, row_object=row_object)


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
