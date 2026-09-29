"""``spec_output_schema`` - the JSON Schema of what a spec's dispatch presents."""

from __future__ import annotations

from typing import Any

from django_service_specs.schema.output_schema import output_schema
from django_service_specs.schema.utils import allow_null
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec


def spec_output_schema(spec: ServiceSpec | SelectorSpec) -> dict[str, Any] | None:
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
    """
    output = spec.output()
    if output is None:
        return None
    item = output_schema(output)
    if isinstance(spec, SelectorSpec):
        kind, may_be_none = spec.kind, spec.allow_none
    elif spec.output_selector_spec is not None:
        kind, may_be_none = spec.output_selector_spec.kind, True
    else:
        return item
    if kind is SelectorKind.LIST:
        return {"type": "array", "items": item}
    return allow_null(item) if may_be_none else item
