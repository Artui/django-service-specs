"""``ServerArguments`` - declared parameters the server answers for, so no caller does."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True)
class ServerArguments:
    """Values a transport supplies for a spec's declared parameters, and names it takes from no one.

    For a mount or a toolset that knows something the caller must not choose:
    the project an agent's run is scoped to, a sibling capture the caller may
    not reach for instead. Each name is a parameter the spec declares, so every
    reader of the call - the permission check, the selector, a ``kwargs``
    provider - sees one value, the server's.

    - ``values`` are supplied for the call and outrank the caller: whatever
      the caller sent under one of these names is dropped and the value here
      takes its place. A bound value satisfies a ``required`` parameter and
      replaces a declared default.
    - ``withheld`` names are neither offered nor taken: the caller's value is
      dropped and nothing takes its place, so the parameter is absent and the
      callable's own default answers, as for any argument nobody sent.

    It is a value and does nothing on its own. A transport calls
    [`check_server_arguments`][django_service_specs.dispatch.check_server_arguments.check_server_arguments]
    once, when it is built, so a binding that cannot mean what it says fails
    at startup;
    [`apply_server_arguments`][django_service_specs.dispatch.apply_server_arguments.apply_server_arguments]
    on each call, before dispatch; and subtracts
    [`names`][django_service_specs.types.server_arguments.ServerArguments.names]
    from the input schema it builds, beside
    [`server_owned_keys`][django_service_specs.specs.server_owned_keys.server_owned_keys],
    so the caller is never asked for a name the server answers.

    ``values`` is copied into a read-only mapping of its own when the value is
    built, because the check runs once and the binding is applied on every
    call after: a key added later, to the mapping a caller passed in or to the
    binding's own, would reach the call unchecked. It still copies and pickles
    like any other value a transport holds, rebuilt through the constructor.
    It takes no part in the hash, as ``Parameter.default`` does not, so a binding is hashable whatever its values are while equality
    still compares them. ``withheld`` is held as a ``frozenset``, a ``set``
    included, and a bare ``str`` is refused, since ``frozenset("pk")`` is a set
    of characters rather than one name.
    """

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
        # A read-only view neither pickles nor deep-copies, so both rebuild the
        # value from a plain copy of its values, through ``__post_init__``
        # again: test_it_copies_and_pickles_like_any_value_a_transport_holds.
        return (type(self), (dict(self.values), self.withheld))

    def names(self) -> frozenset[str]:
        """Every name the binding takes from the caller: the bound and the withheld together.

        What a transport subtracts from the ``properties`` and the ``required``
        of the input schema it advertises, so the caller is offered none of them.
        """
        return frozenset(self.values) | self.withheld
