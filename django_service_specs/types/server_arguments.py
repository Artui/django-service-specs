from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True)
class ServerArguments:
    """Values a transport supplies for a spec's declared parameters, and names it takes from no
    one."""

    values: Mapping[str, Any] = field(default_factory=dict, hash=False)
    withheld: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if isinstance(self.withheld, str):
            raise TypeError(
                f"ServerArguments.withheld is a collection of names, not one string: "
                f"write frozenset({{{self.withheld!r}}})."
            )
        # ``object.__setattr__`` because the dataclass is frozen.
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))
        object.__setattr__(self, "withheld", frozenset(self.withheld))

    def __reduce__(self) -> tuple[Any, ...]:
        # A read-only view, pickled or copied, is rebuilt through ``__post_init__``.
        return (type(self), (dict(self.values), self.withheld))

    def names(self) -> frozenset[str]:
        """Every name the binding takes from the caller: the bound and the withheld together."""
        return frozenset(self.values) | self.withheld
