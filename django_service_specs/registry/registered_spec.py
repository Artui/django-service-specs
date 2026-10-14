"""``RegisteredSpec`` - one named, tagged entry in a ``SpecRegistry``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from django_service_specs.specs.selector_spec import SelectorSpec
    from django_service_specs.specs.service_spec import ServiceSpec
    from django_service_specs.specs.spec_source import SpecSource


@dataclass(frozen=True)
class RegisteredSpec:
    """A spec under its canonical name, with free-form tags.

    The value type held by
    [`SpecRegistry`][django_service_specs.registry.spec_registry.SpecRegistry]. It
    carries only the part of an operation that is **invariant across
    transports** - which spec, what it is called, and how it is grouped.
    Per-transport configuration (an HTTP view's URL kwargs, an MCP tool's
    annotations, an agent adapter's own metadata) stays at the binding that
    configures it, not here.

    Fields:

    - **``name``** - the canonical name for this operation. Unique within the
      registry that holds it; two independent registries are separate
      namespaces and may reuse a name.
    - **``spec``** - a
      [`ServiceSpec`][django_service_specs.specs.service_spec.ServiceSpec] (a
      write) or a
      [`SelectorSpec`][django_service_specs.specs.selector_spec.SelectorSpec] (a
      read), or a
      [`SpecSource`][django_service_specs.specs.spec_source.SpecSource] that
      compiles to one, **kept as registered**: a transport reads the spec it
      runs through
      [`kernel_spec`][django_service_specs.specs.kernel_spec.kernel_spec], and
      the object itself is still there to be asked what only it knows. The
      kind is deliberately **not** stored as its own field: it is derived by
      ``isinstance`` on the compiled spec wherever it is needed, so a stored
      discriminator can never drift from the object it describes.
    - **``tags``** - a frozen set of free-form labels used to derive filtered
      views (``registry.by_tag("public")``). Tags carry boolean-ish facts -
      ``"read"``, ``"admin"``, ``"destructive"`` - that every transport can
      interpret in its own vocabulary.
    """

    name: str
    spec: ServiceSpec | SelectorSpec | SpecSource
    tags: frozenset[str] = frozenset()

    @property
    def agent_contract(self) -> Any:
        """The registered object's own ``agent_contract()``, or ``None`` when it has none.

        Read-only, and never a field: a declaration lives on the spec, never
        on the registry entry, so nothing is passed here and the entry only
        asks. A ``ServiceSpec`` or ``SelectorSpec`` has none and answers
        ``None``; an object registered from djangorestframework-services
        answers the contract its current release builds from what the spec
        declares, for the transports published against that release. Typed
        ``Any`` because the value is that object's, of a type this package
        does not name. Asked on every read, so it is never stale.
        """
        answer = getattr(self.spec, "agent_contract", None)
        return answer() if callable(answer) else None
