"""``Parameter`` - one thing an operation takes, as a declaration."""

from __future__ import annotations

from dataclasses import KW_ONLY, dataclass
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.types.unset import UNSET

if TYPE_CHECKING:
    # Only for the annotations: ``Parameters`` imports this module, so a runtime
    # import here would be circular, and the annotations are strings under
    # ``from __future__ import annotations`` anyway.
    from django_service_specs.parameters.parameters import Parameters

JSON_TYPES = frozenset({"string", "integer", "number", "boolean", "array", "object"})
"""The types a parameter may declare: JSON's own, because that is what crosses
every wire this kernel has - a JSON-RPC call, a queue row, and argv once
``coerce_flat`` has read it."""

FORMATS = frozenset({"decimal", "date-time", "date"})
"""The Python values a string argument decodes into. Each is a value JSON cannot
carry, so it travels as a string and the Validator decodes it."""


@dataclass(frozen=True)
class Parameter:
    """One thing an operation takes, as a declaration every transport reads.

    JSON Schema, argv, the closed argument set and the shape check are all
    derived from it, so a transport describes itself from the declaration
    rather than from whichever validation library the spec happens to use.

    ``name`` and ``type`` are positional because every declaration has both;
    everything else is keyword-only.

    ``items`` is an array's element: a JSON type name for a flat list, or the
    ``Parameters`` of the object each element is. ``fields`` is the same for a
    parameter whose own type is ``object``. Nesting is what lets a relation
    write declare its rows: an author with its books says what a book is, where
    a flat ``items="object"`` would say nothing and let a malformed row through.

    ``default`` is [`UNSET`][django_service_specs.types.unset.UNSET] when none is
    declared, so a default of ``None`` stays a real default. It is reported, not
    applied: whether an omitted argument arrives as the default, as ``None`` or
    not at all is the validating library's behaviour, and each adapter reports
    what its library does.

    There are no bounds (``maxLength``, ``minimum``) yet. The Validator enforces
    those; adding them here is additive.
    """

    name: str
    type: str
    _: KW_ONLY
    required: bool = False
    format: str | None = None
    items: str | Parameters | None = None
    fields: Parameters | None = None
    choices: tuple[Any, ...] | None = None
    default: Any = UNSET
    nullable: bool = False
    help: str | None = None

    def __post_init__(self) -> None:
        # A declaration that no reader can act on is refused where it is written,
        # so the error names the parameter rather than surfacing later as a
        # schema or a shape check that quietly ignores half of it.
        where = f"Parameter {self.name!r}"
        if self.type not in JSON_TYPES:
            raise ImproperlyConfigured(
                f"{where}: type {self.type!r} is not a JSON type; use one of {sorted(JSON_TYPES)}."
            )
        if self.format is not None:
            if self.format not in FORMATS:
                raise ImproperlyConfigured(
                    f"{where}: format {self.format!r} is not one of {sorted(FORMATS)}."
                )
            if self.type != "string":
                raise ImproperlyConfigured(
                    f"{where}: a format describes a string; this parameter is {self.type!r}."
                )
        if self.items is not None:
            if self.type != "array":
                raise ImproperlyConfigured(f"{where}: items describes an array's element.")
            if isinstance(self.items, str) and self.items not in JSON_TYPES:
                raise ImproperlyConfigured(
                    f"{where}: items {self.items!r} is not a JSON type; "
                    "pass a type name or the Parameters of an object."
                )
        if self.fields is not None and self.type != "object":
            raise ImproperlyConfigured(f"{where}: fields describes an object's own parameters.")
        if self.choices is not None:
            # Normalized rather than refused, so a list reads as naturally as a
            # tuple and the frozen declaration stays hashable.
            object.__setattr__(self, "choices", tuple(self.choices))

    @property
    def nested(self) -> Parameters | None:
        """The Parameters inside this one: an object's fields, or an array's rows."""
        if self.type == "object":
            return self.fields
        if self.type == "array" and not isinstance(self.items, str):
            return self.items
        return None
