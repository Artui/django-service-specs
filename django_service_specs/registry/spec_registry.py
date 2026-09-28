"""``SpecRegistry`` - a named, taggable home for a project's spec set."""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.registry.registered_spec import RegisteredSpec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec


class SpecRegistry:
    """A ``name -> spec`` map with tags, stable ordering, and filtered views.

    One declaration site for the operations a project exposes over more than
    one transport, so the transports read one source instead of each
    enumerating specs and drifting. It holds only the **invariant** part of an
    operation - which spec, its canonical name, its tags; per-transport
    configuration stays at the binding that owns it. Adapters read a registry
    at configuration time to build their binding tables; nothing consults one
    per dispatch.

    ```python
    registry = SpecRegistry()
    registry.register("list_orders", orders_spec, tags=("read", "public"))
    registry.register("refund_order", refund_spec, tags=("write", "admin"))

    public = registry.by_tag("public")   # a new registry - a snapshot
    ```

    **There is no global registry**: a consumer holds as many of its own
    instances as it likes, with no shared state between them. Registries are
    mutable - ``register`` adds - but every derivation (``by_tag``,
    ``subset``, ``merge``) returns a **new** registry holding a snapshot of
    the selected entries, sharing the spec objects rather than copying them.
    A derived view never mutates its source, and a later ``register()`` on the
    source does **not** appear in a view derived earlier.
    """

    def __init__(self, entries: Iterable[RegisteredSpec] = ()) -> None:
        """Build a registry, optionally seeded with existing entries.

        Args:
            entries: Entries to seed, in order, validated exactly as
                ``register`` validates.
        """
        self._entries: dict[str, RegisteredSpec] = {}
        for entry in entries:
            self._add(entry)

    def register(
        self,
        name: str,
        spec: ServiceSpec | SelectorSpec,
        *,
        tags: Iterable[str] = (),
    ) -> None:
        """Add a spec under ``name``.

        Args:
            name: The canonical name. Must be unused **in this registry** - a
                duplicate raises rather than overwriting, so a copy-pasted
                declaration fails at import time instead of silently
                shadowing an operation.
            spec: A ``ServiceSpec`` (write) or ``SelectorSpec`` (read).
            tags: Free-form labels, deduplicated into a frozen set.

        Raises:
            ValueError: ``name`` is already registered here.
            TypeError: ``spec`` is neither a ``ServiceSpec`` nor a
                ``SelectorSpec``.
            ImproperlyConfigured: ``spec.permissions is None``. Off HTTP there
                is no view whose policy an undeclared spec could inherit, so
                registering one that means to be open must say so with
                ``permissions=[Unrestricted()]``; the alternative is a spec
                that dispatch would refuse on every call.
        """
        self._add(RegisteredSpec(name=name, spec=spec, tags=frozenset(tags)))

    def get(self, name: str) -> RegisteredSpec | None:
        """Return the entry registered under ``name``, or ``None``."""
        return self._entries.get(name)

    def all(self) -> tuple[RegisteredSpec, ...]:
        """Every entry, in registration order, so a transport's listing is stable."""
        return tuple(self._entries.values())

    def mutations(self) -> tuple[RegisteredSpec, ...]:
        """The ``ServiceSpec`` entries, in registration order."""
        return tuple(e for e in self._entries.values() if isinstance(e.spec, ServiceSpec))

    def queries(self) -> tuple[RegisteredSpec, ...]:
        """The ``SelectorSpec`` entries, in registration order."""
        return tuple(e for e in self._entries.values() if isinstance(e.spec, SelectorSpec))

    def by_tag(self, *tags: str) -> SpecRegistry:
        """A new registry holding the entries carrying **any** of ``tags``.

        Union, not intersection - chain calls for an intersection
        (``reg.by_tag("read").by_tag("public")``). No tags matches nothing.
        """
        wanted = frozenset(tags)
        return SpecRegistry(e for e in self._entries.values() if e.tags & wanted)

    def subset(self, *names: str) -> SpecRegistry:
        """A new registry holding the named entries, in the order given.

        Raises:
            KeyError: A name is not registered here - a typo is a
                configuration error, not a quietly smaller surface.
        """
        return SpecRegistry(self._require(name) for name in names)

    def merge(self, *others: SpecRegistry) -> SpecRegistry:
        """A new registry combining this one with ``others``, in order.

        Names are unique per registry, so independent registries may reuse
        one; merging is the single place that reuse becomes a conflict.

        Raises:
            ValueError: The same name appears in more than one input.
        """
        return SpecRegistry(
            entry for source in (self, *others) for entry in source._entries.values()
        )

    def specs(self) -> dict[str, ServiceSpec | SelectorSpec]:
        """A fresh ``name -> spec`` dict - the shape adapters already accept.

        Pass ``registry.specs()`` wherever a ``dict[str, spec]`` goes today.
        Mutating the returned dict does not affect the registry.
        """
        return {name: entry.spec for name, entry in self._entries.items()}

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, name: str) -> bool:
        return name in self._entries

    def __iter__(self) -> Iterator[RegisteredSpec]:
        return iter(self._entries.values())

    def _add(self, entry: RegisteredSpec) -> None:
        if entry.name in self._entries:
            raise ValueError(f"{entry.name!r} is already registered in this SpecRegistry.")
        if not isinstance(entry.spec, ServiceSpec | SelectorSpec):
            raise TypeError(
                f"{entry.name!r}: expected a ServiceSpec or SelectorSpec, got "
                f"{type(entry.spec).__name__}."
            )
        if entry.spec.permissions is None:
            raise ImproperlyConfigured(
                f"{entry.name!r} declares no permissions. Pass permissions=[Unrestricted()] "
                "to mean that anyone may run it."
            )
        self._entries[entry.name] = entry

    def _require(self, name: str) -> RegisteredSpec:
        entry = self._entries.get(name)
        if entry is None:
            raise KeyError(f"{name!r} is not registered in this SpecRegistry.")
        return entry
