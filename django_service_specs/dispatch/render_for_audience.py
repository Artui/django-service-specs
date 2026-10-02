"""``render_for_audience`` - present a dispatch result for an agent audience."""

from __future__ import annotations

from typing import Any

from django_service_specs.dispatch.dispatch_result import DispatchResult
from django_service_specs.dispatch.present import present
from django_service_specs.output.audience_projection import AudienceProjection
from django_service_specs.output.audience_projection_for_spec import audience_projection_for_spec
from django_service_specs.output.project_payload import project_payload
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec


def render_for_audience(
    spec: ServiceSpec | SelectorSpec,
    result: DispatchResult,
    *,
    projection: AudienceProjection | None = None,
) -> Any:
    """[`present`][django_service_specs.dispatch.present.present] plus the agent projection.

    The one call an agent transport makes instead of ``present``, so an MCP
    server, an in-process toolset and anything added later shape payloads
    identically rather than each growing its own post-processor. ``spec`` and
    ``result`` mean exactly what they mean to ``present``, which this calls
    first: the projection applies to the presented value and never to the
    value it was presented from.

    ``projection`` is the output's resolved markings. Omit it and one is read
    off the spec; a transport that registers its tools up front builds it
    once with
    [`audience_projection_for_spec`][django_service_specs.output.audience_projection_for_spec.audience_projection_for_spec],
    a mount's overrides included, and passes it in. ``None`` is therefore not
    a way out of projecting: a caller naming no audience calls ``present``,
    which is what every HTTP response is.

    To serve one page, page the result's value first and present the page's
    rows: ``render_for_audience(spec, replace(result, value=page.items))``,
    then [`envelope`][django_service_specs.types.output_page.OutputPage.envelope]
    what comes back. The envelope's keys belong to no ``Output``, so the
    projection must never walk them.

    A selector spec's declared ``affordances`` pass through whole: the
    ``affordances`` object ``present`` adds to each row is a key no ``Output``
    declares, so the projection has nothing to say about it, and an agent
    reads ``available``, the ``code`` a client branches on, and the ``reason``
    - the sentence a model relays when it explains why an action is not
    possible, written for exactly that reader.

    Render an agent's **answer** with this. A pipeline that feeds one spec's
    output into the next keeps presenting with ``present``, or the handles the
    next step reads by will have been projected away.

    From async code, project what
    [`apresent`][django_service_specs.dispatch.apresent.apresent] returns:
    ``project_payload(await apresent(spec, result), projection)``. Presenting
    may query and runs in the executor; projecting reads only the presented
    data and the declaration, so it is safe on the event loop.

    Raises:
        ValueError: ``kind="not_found"``, as ``present``.
    """
    payload: Any = present(spec, result)
    if projection is None:
        projection = audience_projection_for_spec(spec)
    return project_payload(payload, projection)
