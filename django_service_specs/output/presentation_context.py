"""``PresentationContext`` - what a Presenter may know about the call besides the value."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True)
class PresentationContext:
    """The principal a call ran for, the target it acted on, and its resolved seeds.

    The output-side counterpart of
    [`ValidationContext`][django_service_specs.validation.validation_context.ValidationContext].
    Dispatch builds one per call and carries it on the
    [`DispatchResult`][django_service_specs.dispatch.dispatch_result.DispatchResult],
    and [`present`][django_service_specs.dispatch.present.present] hands it to
    [`Presenter.presented()`][django_service_specs.output.presenter.Presenter.presented]
    with every value it presents, so a library that renders under a context -
    a field defaulting to the current user, a link built from the request - can
    read the call it is rendering for.

    - ``principal`` is who the call ran for.
    - ``target`` is the row or the queryset a service spec resolved, ``None``
      for a create and for a selector spec, whose rows are the value itself.
    - ``ambient`` is the call's base pool, read-only: ``user``, ``progress``
      and every registered seed, such as an HTTP adapter's ``request``. Never
      an argument, a validated value or a provider's key.
    """

    principal: Any
    target: Any = None
    # Excluded from equality, as on ``ValidationContext``: a mapping proxy
    # cannot be hashed, and two contexts of one call are one context.
    ambient: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}), compare=False)
