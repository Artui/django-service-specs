"""``OutputField`` - one field of what an operation returns."""

from __future__ import annotations

from dataclasses import KW_ONLY, dataclass
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.output.field_marking import FieldMarking
from django_service_specs.parameters.parameter import FORMATS, JSON_TYPES

if TYPE_CHECKING:
    # Annotation-only: ``Output`` imports this module.
    from django_service_specs.output.output import Output


@dataclass(frozen=True)
class OutputField:
    """One field of an operation's output, declared without rendering anything.

    The output-side counterpart of [`Parameter`][django_service_specs.parameters.parameter.Parameter],
    carrying what a reader needs that names and types alone do not give:

    - ``label``: a readable header. Libraries disagree here (one invents ``Id``
      from ``id``, others give nothing), so the adapter supplies what its
      library has and ``None`` means it has none.
    - ``choices``: **value-and-display pairs**, because a table shows the
      display and a schema states it as a title, and a bare value list gives
      neither.
    - ``always_present``: whether the key is in every rendered row. A rendering
      rule rather than a type - one library drops a read-only key it cannot
      read where another always emits it - so the adapter supplies it, and a
      schema lists only always-present keys as required.
    - ``marking``: how an agent audience is shown the field.

    ``fields`` and ``items`` describe a nested object and an array's element,
    and ``items_nullable`` whether a ``null`` may stand in for an element, as on
    ``Parameter``.
    """

    name: str
    type: str
    _: KW_ONLY
    format: str | None = None
    nullable: bool = False
    label: str | None = None
    choices: tuple[tuple[Any, str], ...] | None = None
    always_present: bool = True
    marking: FieldMarking | None = None
    fields: Output | None = None
    items: str | Output | None = None
    items_nullable: bool = False

    def __post_init__(self) -> None:
        where = f"OutputField {self.name!r}"
        if self.type not in JSON_TYPES:
            raise ImproperlyConfigured(
                f"{where}: type {self.type!r} is not a JSON type; use one of {sorted(JSON_TYPES)}."
            )
        if self.format is not None:
            if self.format not in FORMATS:
                raise ImproperlyConfigured(
                    f"{where}: format {self.format!r} is not one of {sorted(FORMATS)}."
                )
            # As on Parameter: every format names what a string decodes into,
            # and a schema states it beside the type, so on any other type it
            # would describe a value the output never holds.
            if self.type != "string":
                raise ImproperlyConfigured(
                    f"{where}: a format describes a string; this field is {self.type!r}."
                )
        if self.fields is not None and self.type != "object":
            raise ImproperlyConfigured(f"{where}: fields describes an object's own fields.")
        if self.items is not None and self.type != "array":
            raise ImproperlyConfigured(f"{where}: items describes an array's element.")
        if self.items_nullable and self.items is None:
            raise ImproperlyConfigured(
                f"{where}: items_nullable describes a declared element; declare items."
            )
        if self.choices is not None:
            pairs = tuple(tuple(pair) for pair in self.choices)
            if any(len(pair) != 2 for pair in pairs):
                raise ImproperlyConfigured(
                    f"{where}: choices are (value, display) pairs, so a reader can show "
                    "the display and a schema can state it."
                )
            object.__setattr__(self, "choices", pairs)
