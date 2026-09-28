"""``Parameters`` - everything an operation takes, in declaration order."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.parameters.parameter import Parameter


@dataclass(frozen=True)
class Parameters:
    """An ordered set of [`Parameter`][django_service_specs.parameters.parameter.Parameter].

    A spec's Parameters are assembled from several sources - its target
    selector's ``reads``, its Validator's ``parameters()`` - and ``+`` is how.
    **A name declared twice is refused**, at construction and at ``+`` alike:
    two sources claiming one argument is a spec bug, and a last-wins merge
    would hide which of the two declarations a transport describes and which
    one the argument reaches.

    Any iterable of parameters is accepted and stored as a tuple, so the
    declaration stays hashable and ordered.
    """

    items: tuple[Parameter, ...] = ()

    def __post_init__(self) -> None:
        items = tuple(self.items)
        object.__setattr__(self, "items", items)
        names = [p.name for p in items]
        twice = sorted({name for name in names if names.count(name) > 1})
        if twice:
            raise ImproperlyConfigured(f"Parameters declare {twice} more than once.")

    def __iter__(self) -> Iterator[Parameter]:
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    def __add__(self, other: Parameters) -> Parameters:
        clash = self.names() & other.names()
        if clash:
            raise ImproperlyConfigured(
                f"Parameters {sorted(clash)} are declared by two sources. Rename one, "
                "or declare the argument in one place."
            )
        return Parameters(self.items + other.items)

    def names(self) -> frozenset[str]:
        """Every declared name, for the closed argument set."""
        return frozenset(p.name for p in self.items)

    def get(self, name: str) -> Parameter | None:
        """The parameter declared as ``name``, or ``None``."""
        return next((p for p in self.items if p.name == name), None)

    @classmethod
    def of(cls, *parameters: Parameter) -> Parameters:
        """``Parameters.of(a, b)``: the same as ``Parameters((a, b))``, read aloud."""
        return cls(parameters)
