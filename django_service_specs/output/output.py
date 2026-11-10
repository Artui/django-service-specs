from __future__ import annotations

from collections.abc import Iterator
from dataclasses import KW_ONLY, dataclass, field
from typing import Any

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.output.field_marking import FieldMarking
from django_service_specs.parameters.parameters import (
    FORMATS,
    JSON_TYPES,
    canonical_choices,
    checked_json_schema_extra,
)
from django_service_specs.types.utils import OUTPUT_FIELD_SCHEMA_KEYWORDS

_OUTPUT_TYPES = JSON_TYPES | {"any"}


@dataclass(frozen=True)
class OutputField:
    """One field of an operation's output, declared without rendering anything."""

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
    json_schema_extra: dict[str, Any] | None = field(default=None, hash=False)

    def __post_init__(self) -> None:
        # As on ``Parameter``: a format names how a string decodes, so other types refuse it.
        where = f"OutputField {self.name!r}"
        object.__setattr__(
            self,
            "json_schema_extra",
            checked_json_schema_extra(where, self.json_schema_extra, OUTPUT_FIELD_SCHEMA_KEYWORDS),
        )
        if self.type not in _OUTPUT_TYPES:
            raise ImproperlyConfigured(
                f"{where}: type {self.type!r} is not a JSON type; use one of "
                f"{sorted(_OUTPUT_TYPES)}."
            )
        if self.format is not None:
            if self.format not in FORMATS:
                raise ImproperlyConfigured(
                    f"{where}: format {self.format!r} is not one of {sorted(FORMATS)}."
                )
            if self.type != "string":
                raise ImproperlyConfigured(
                    f"{where}: a format describes a string; this field is {self.type!r}."
                )
        if self.fields is not None and self.type != "object":
            raise ImproperlyConfigured(f"{where}: fields describes an object's own fields.")
        if self.items is not None and self.type != "array":
            raise ImproperlyConfigured(f"{where}: items describes an array's element.")
        if self.items == "any":
            raise ImproperlyConfigured(
                f"{where}: an array with no items takes any element already; declare no items."
            )
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
            if self.type == "any":
                raise ImproperlyConfigured(
                    f"{where}: an untyped value is matched by no list; declare its type to list "
                    "choices."
                )
            object.__setattr__(self, "choices", canonical_choices(self.format, pairs))


@dataclass(frozen=True)
class Output:
    """The ordered fields of an operation's output, read without rendering anything."""

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
