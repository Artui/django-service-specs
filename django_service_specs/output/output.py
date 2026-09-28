"""``Output`` - what an operation returns, as a declaration."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.output.output_field import OutputField


@dataclass(frozen=True)
class Output:
    """The ordered fields of an operation's output, read without rendering anything.

    Readers that never render: an agent tool's output schema, a capability
    manifest, a command's table header when there are no rows, a confirmation
    page's target display. Ordered, because a table's columns are, and the
    order is declaration order.

    Paired with [`Parameters`][django_service_specs.parameters.parameters.Parameters]:
    that is what goes in, this is what comes out.
    """

    fields: tuple[OutputField, ...] = ()

    def __post_init__(self) -> None:
        fields = tuple(self.fields)
        object.__setattr__(self, "fields", fields)
        names = [f.name for f in fields]
        twice = sorted({name for name in names if names.count(name) > 1})
        if twice:
            raise ImproperlyConfigured(f"Output declares {twice} more than once.")

    def __iter__(self) -> Iterator[OutputField]:
        return iter(self.fields)

    def __len__(self) -> int:
        return len(self.fields)

    def names(self) -> tuple[str, ...]:
        """Every field name, in declaration order."""
        return tuple(f.name for f in self.fields)

    def get(self, name: str) -> OutputField | None:
        """The field declared as ``name``, or ``None``."""
        return next((f for f in self.fields if f.name == name), None)
