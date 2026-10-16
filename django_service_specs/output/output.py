"""``Output`` and ``OutputField`` - what an operation returns, and each field of it.

The two share a file because each holds the other: an ``OutputField`` of type
``object`` carries the ``Output`` of its fields, and ``Output`` is made of
``OutputField``. Split across two modules, one of them could import the other
only for its annotations.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import KW_ONLY, dataclass
from typing import Any

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.output.field_marking import FieldMarking
from django_service_specs.parameters.parameters import FORMATS, JSON_TYPES, canonical_choices

_OUTPUT_TYPES = JSON_TYPES | {"any"}


@dataclass(frozen=True)
class OutputField:
    """One field of an operation's output, declared without rendering anything.

    The output-side counterpart of [`Parameter`][django_service_specs.parameters.parameters.Parameter],
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

    ``type`` is one of the JSON types, or ``any`` for a value whose JSON type
    is open - a computed field, a JSON column - which a schema then describes
    with no ``type`` at all rather than as a string it may not be. As on
    ``Parameter``, ``any`` lists no choices, since a list of values says what
    type they are, and an array of any element declares no ``items`` rather
    than ``items="any"``.
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
        # One spelling for an element of any type, and the array with no items
        # is it, as on Parameter. Held by test_refuses_a_declaration_no_reader_can_act_on.
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
            # A list of values says what type they are, as on Parameter.
            if self.type == "any":
                raise ImproperlyConfigured(
                    f"{where}: an untyped value is matched by no list; declare its type to list "
                    "choices."
                )
            # As on Parameter, two spellings of one id collapsing into the
            # first with its display, and the spelling ``str()`` gives a model's UUID,
            # so a row presenting that spelling finds its display; an output
            # value itself is not canonicalised, so another spelling passes
            # through unspoken. Held by
            # test_a_uuid_choice_is_spoken_for_the_spelling_a_model_presents.
            object.__setattr__(self, "choices", canonical_choices(self.format, pairs))


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
