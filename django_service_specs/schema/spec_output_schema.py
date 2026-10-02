"""``spec_output_schema`` - the JSON Schema of what a spec's dispatch presents."""

from __future__ import annotations

from typing import Any

from django_service_specs.output.annotate_output_schema import annotate_output_schema
from django_service_specs.output.audience_projection import AudienceProjection
from django_service_specs.schema.output_schema import output_schema
from django_service_specs.schema.utils import allow_null
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec


def spec_output_schema(
    spec: ServiceSpec | SelectorSpec,
    *,
    paginate: bool = False,
    projection: AudienceProjection | None = None,
    handle_description: str | None = None,
) -> dict[str, Any] | None:
    """The JSON Schema of what [`present`][django_service_specs.dispatch.present.present] returns for ``spec``.

    ``None`` when ``spec.output()`` is ``None``: a spec with no presenter
    declares nothing about what it returns, and a shape invented for it would
    be a guess every client then trusts.

    Otherwise the item's [`output_schema`][django_service_specs.schema.output_schema.output_schema],
    shaped by what dispatch returns for this kind of spec:

    - **A LIST selector spec**, or a service spec whose output selector is a
      LIST, presents every row: ``{"type": "array", "items": <item>}``.
    - **A RETRIEVE selector spec with ``allow_none``** presents ``None`` for a
      missing row, so the item's type gains ``"null"``. Without ``allow_none``
      a missing row is not-found, which a transport answers in its own terms
      and never presents, so the item stays as it is.
    - **A service spec whose output selector is a RETRIEVE** gains ``"null"``
      whatever its ``allow_none`` says: once the service has run, a re-read
      that finds nothing is ``None`` rather than not-found, because reporting
      not-found would tell the caller a committed write did not happen.
    - **A service spec with no output selector** presents what the service
      returned, described by its presenter as the item. Whether a service may
      return ``None`` is not in its declaration, so it is not stated.

    ``paginate`` describes a list served one page at a time, as
    [`paginate_output`][django_service_specs.dispatch.paginate_output.paginate_output]
    and [`OutputPage.envelope`][django_service_specs.types.output_page.OutputPage.envelope]
    shape it: ``{"items": [...], "page": n, "totalPages": n, "hasNext": b}``,
    every key required. It changes only a list's schema, since one row has no
    pages, so a transport may pass it for every spec it serves paged.

    ``projection`` describes what
    [`render_for_audience`][django_service_specs.dispatch.render_for_audience.render_for_audience]
    hands back rather than what ``present`` does, through
    [`annotate_output_schema`][django_service_specs.output.annotate_output_schema.annotate_output_schema]:
    hidden fields left out, labelled choices restated in their displays, and a
    marking's wording as a field's ``"description"``. It lands on the
    **item**, wherever the item sits, because the array and the paging
    envelope are this function's own shapes and belong to no ``Output``. Omit
    it, as every caller naming no audience does, and the schema is the full
    declaration. ``handle_description`` is the wording for a handle whose
    marking declares none, and defaults to none: what a reader should do with
    an identifier depends on the reader, and the transport is what knows.
    """
    output = spec.output()
    if output is None:
        return None
    item: dict[str, Any] = output_schema(output)
    if projection is not None:
        # On the item before anything wraps it: the projection walks declared
        # fields, and the array and the envelope declare none.
        item = (
            annotate_output_schema(item, projection, handle_description=handle_description) or item
        )
    if isinstance(spec, SelectorSpec):
        kind, may_be_none = spec.kind, spec.allow_none
    elif spec.output_selector_spec is not None:
        kind, may_be_none = spec.output_selector_spec.kind, True
    else:
        return item
    if kind is SelectorKind.LIST:
        array: dict[str, Any] = {"type": "array", "items": item}
        return _paged(array) if paginate else array
    return allow_null(item) if may_be_none else item


def _paged(array: dict[str, Any]) -> dict[str, Any]:
    """The paging envelope around ``array``, as ``OutputPage.envelope`` writes it.

    No ``additionalProperties``, as on every output object: a transport may add
    keys of its own to what it sends.
    """
    return {
        "type": "object",
        "properties": {
            "items": array,
            "page": {"type": "integer"},
            "totalPages": {"type": "integer"},
            "hasNext": {"type": "boolean"},
        },
        "required": ["items", "page", "totalPages", "hasNext"],
    }
