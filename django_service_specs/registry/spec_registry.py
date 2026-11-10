from __future__ import annotations

from collections.abc import Iterable, Iterator

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.registry.registered_spec import RegisteredSpec
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource


class SpecRegistry:
    """A ``name -> spec`` map with tags, stable ordering, and filtered views."""

    def __init__(self, entries: Iterable[RegisteredSpec] = ()) -> None:
        """Build a registry, optionally seeded with existing entries."""
        self._entries: dict[str, RegisteredSpec] = {}
        for entry in entries:
            self._add(entry)

    def register(
        self,
        name: str,
        spec: ServiceSpec | SelectorSpec | SpecSource,
        *,
        tags: Iterable[str] = (),
    ) -> None:
        """Add a spec under ``name``."""
        self._add(RegisteredSpec(name=name, spec=spec, tags=frozenset(tags)))

    def get(self, name: str) -> RegisteredSpec | None:
        """Return the entry registered under ``name``, or ``None``."""
        return self._entries.get(name)

    def all(self) -> tuple[RegisteredSpec, ...]:
        """Every entry, in registration order, so a transport's listing is stable."""
        return tuple(self._entries.values())

    def mutations(self) -> tuple[RegisteredSpec, ...]:
        """The ``ServiceSpec`` entries, in registration order."""
        return tuple(
            e for e in self._entries.values() if isinstance(kernel_spec(e.spec), ServiceSpec)
        )

    def queries(self) -> tuple[RegisteredSpec, ...]:
        """The ``SelectorSpec`` entries, in registration order."""
        return tuple(
            e for e in self._entries.values() if isinstance(kernel_spec(e.spec), SelectorSpec)
        )

    def by_tag(self, *tags: str) -> SpecRegistry:
        """A new registry holding the entries carrying **any** of ``tags``."""
        wanted = frozenset(tags)
        return SpecRegistry(e for e in self._entries.values() if e.tags & wanted)

    def subset(self, *names: str) -> SpecRegistry:
        """A new registry holding the named entries, in the order given."""
        return SpecRegistry(self._require(name) for name in names)

    def merge(self, *others: SpecRegistry) -> SpecRegistry:
        """A new registry combining this one with ``others``, in order."""
        return SpecRegistry(
            entry for source in (self, *others) for entry in source._entries.values()
        )

    def replace(self, name: str, spec: ServiceSpec | SelectorSpec | SpecSource) -> SpecRegistry:
        """A new registry with ``spec`` under ``name`` in place of the spec registered there."""
        swapped = RegisteredSpec(name=name, spec=spec, tags=self._require(name).tags)
        return SpecRegistry(
            swapped if entry.name == name else entry for entry in self._entries.values()
        )

    def specs(self) -> dict[str, ServiceSpec | SelectorSpec | SpecSource]:
        """A fresh ``name -> spec`` dict - the shape adapters already accept."""
        return {name: entry.spec for name, entry in self._entries.items()}

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, name: str) -> bool:
        return name in self._entries

    def __iter__(self) -> Iterator[RegisteredSpec]:
        return iter(self._entries.values())

    def _add(self, entry: RegisteredSpec) -> None:
        # Compiled here, so a bad declaration fails at registration with its name.
        if entry.name in self._entries:
            raise ValueError(f"{entry.name!r} is already registered in this SpecRegistry.")
        try:
            spec = kernel_spec(entry.spec)
        except TypeError as refused:
            raise TypeError(f"{entry.name!r}: {refused}") from refused
        if not isinstance(spec, ServiceSpec | SelectorSpec):
            raise TypeError(
                f"{entry.name!r}: {type(spec).__name__}.as_kernel_spec() answers itself but it is "
                "neither a ServiceSpec nor a SelectorSpec."
            )
        if spec.permissions is None:
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
