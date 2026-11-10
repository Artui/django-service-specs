from __future__ import annotations

import copy
import math
import uuid
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import KW_ONLY, dataclass, field
from typing import Any

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.types.unset import UNSET
from django_service_specs.types.utils import PARAMETER_SCHEMA_KEYWORDS, is_json_native

JSON_TYPES = frozenset({"string", "integer", "number", "boolean", "array", "object"})
"""The types a parameter may declare: JSON's own, because that is what crosses
every wire this kernel has - a JSON-RPC call, a queue row, and argv once
``coerce_flat`` has read it."""

PARAMETER_TYPES = JSON_TYPES | {"file", "any"}
"""The types a parameter may declare: JSON's, ``file`` and ``any``.

A file is what a multipart body carries beside its fields, and what a Python
caller hands a command or a task as a Django ``File``. It is no JSON type, so a
JSON caller cannot send one, and it is a parameter's alone: what comes out of an
operation is still one of the JSON types.

``any`` is a parameter that declares no type: what an unannotated argument
takes, a key that may be ``3`` or ``"abc"``. It is a parameter's alone too, and
no array's element, since an array with no ``items`` takes any element already."""

FORMATS = frozenset({"decimal", "date-time", "date", "uuid"})
"""The Python values a string argument decodes into. Each is a value JSON cannot
carry, so it travels as a string and the Validator decodes it.

``uuid`` is an identifier's: the shape check refuses a string that spells no
UUID - ``"null"``, ``"undefined"``, the parameter's own name - as an ordinary
refusal of the arguments, where a lookup handed one would raise Django's
``ValidationError`` from inside the ORM, which no transport maps. A UUID
that passes is handed on in its canonical spelling, and a declared choice is
held in it too, so a listed id matches in any spelling it is sent in."""


def canonical_choices(
    fmt: str | None, pairs: Iterable[tuple[Any, Any]]
) -> tuple[tuple[Any, Any], ...]:
    """The ``pairs`` of each choice, in the spelling a value of ``fmt`` is handed on in."""
    kept: list[tuple[Any, Any]] = []
    seen: set[str] = set()
    for choice, paired in pairs:
        canonical = _uuid_spelling(fmt, choice)
        if canonical is None:
            kept.append((choice, paired))
        elif canonical not in seen:
            seen.add(canonical)
            kept.append((canonical, paired))
    return tuple(kept)


def checked_json_schema_extra(
    where: str, extra: Any, owned: Mapping[str, tuple[str, ...]]
) -> dict[str, Any] | None:
    """``extra`` as a declaration's own ``dict``, or ``None``; refused if no schema carries it."""
    if extra is None:
        return None
    if not isinstance(extra, Mapping):
        raise ImproperlyConfigured(
            f"{where}: json_schema_extra is {type(extra).__name__}, not a mapping of JSON Schema "
            "keywords to their values."
        )
    named = [key for key in extra if not isinstance(key, str)]
    if named:
        raise ImproperlyConfigured(
            f"{where}: json_schema_extra keys must be strings; got {named!r}. Each is a JSON "
            "Schema keyword."
        )
    stated = sorted(owned.keys() & extra.keys())
    if stated:
        each = " ".join(
            f"json_schema_extra states {key!r}, which the schema takes from "
            f"{' and '.join(owned[key])}."
            for key in stated
        )
        raise ImproperlyConfigured(
            f"{where}: {each} Declare each on its field: json_schema_extra carries only the "
            "keywords no field spells, so the schema never advertises what the declaration "
            "does not say."
        )
    for key, value in extra.items():
        if not is_json_native(value):
            raise ImproperlyConfigured(
                f"{where}: json_schema_extra[{key!r}] is no JSON value: it holds a value of a "
                "type JSON cannot carry, at some depth. Every transport encodes the schema as "
                "JSON; state it as a string, number, boolean, null, list or object."
            )
    return copy.deepcopy(dict(extra))


def _uuid_spelling(fmt: str | None, choice: Any) -> str | None:
    """The canonical spelling of a ``uuid`` choice, or ``None`` for one this leaves as listed."""
    if fmt != "uuid" or not isinstance(choice, str):
        return None
    try:
        return str(uuid.UUID(choice))
    except ValueError:
        return None


@dataclass(frozen=True)
class Parameter:
    """One thing an operation takes, as a declaration every transport reads."""

    name: str
    type: str
    _: KW_ONLY
    required: bool = False
    format: str | None = None
    items: str | Parameters | None = None
    items_nullable: bool = False
    fields: Parameters | None = None
    choices: tuple[Any, ...] | None = None
    choice_labels: tuple[tuple[Any, str], ...] | None = field(default=None, hash=False)
    minimum: int | float | None = None
    maximum: int | float | None = None
    min_length: int | None = None
    max_length: int | None = None
    default: Any = field(default=UNSET, hash=False)
    nullable: bool = False
    help: str | None = None
    json_schema_extra: dict[str, Any] | None = field(default=None, hash=False)
    reflected: bool = False

    def __post_init__(self) -> None:
        # Refused where written, so the error names the parameter it is about.
        where = f"Parameter {self.name!r}"
        object.__setattr__(
            self,
            "json_schema_extra",
            checked_json_schema_extra(where, self.json_schema_extra, PARAMETER_SCHEMA_KEYWORDS),
        )
        if self.type not in PARAMETER_TYPES:
            raise ImproperlyConfigured(
                f"{where}: type {self.type!r} is not a JSON type, a file or any; "
                f"use one of {sorted(PARAMETER_TYPES)}."
            )
        if self.format is not None:
            if self.format not in FORMATS:
                raise ImproperlyConfigured(
                    f"{where}: format {self.format!r} is not one of {sorted(FORMATS)}."
                )
            if self.type == "array":
                self._check_element_format(where)
            elif self.type != "string":
                raise ImproperlyConfigured(
                    f"{where}: a format describes a string; this parameter is {self.type!r}."
                )
        if self.items is not None:
            if self.type != "array":
                raise ImproperlyConfigured(f"{where}: items describes an array's element.")
            if self.items == "any":
                raise ImproperlyConfigured(
                    f"{where}: an array with no items takes any element already; declare no items."
                )
            if isinstance(self.items, str) and self.items not in PARAMETER_TYPES:
                raise ImproperlyConfigured(
                    f"{where}: items {self.items!r} is not a JSON type or a file; "
                    "pass a type name or the Parameters of an object."
                )
        if self.items_nullable and self.items is None:
            raise ImproperlyConfigured(
                f"{where}: items_nullable describes a declared element; declare items."
            )
        if self.fields is not None and self.type != "object":
            raise ImproperlyConfigured(f"{where}: fields describes an object's own parameters.")
        if self.choices is not None:
            pairs = canonical_choices(self.format, ((choice, None) for choice in self.choices))
            choices = tuple(choice for choice, _ in pairs)
            object.__setattr__(self, "choices", choices)
            if "file" in (self.type, self.items):
                raise ImproperlyConfigured(
                    f"{where}: a file is never one of a list of values; declare no choices."
                )
            if self.type == "any":
                raise ImproperlyConfigured(
                    f"{where}: an untyped value is matched by no list; declare its type to list "
                    "choices."
                )
        if self.choice_labels is not None:
            self._normalize_choice_labels(where, self.choice_labels)
        if self.minimum is not None or self.maximum is not None:
            self._check_bounds(where)
        if self.min_length is not None or self.max_length is not None:
            self._check_lengths(where)

    def _check_bounds(self, where: str) -> None:
        """Refuse a bound no reader can act on: a non-number, or one on a non-number value."""
        for label, bound in (("minimum", self.minimum), ("maximum", self.maximum)):
            if bound is not None and not (
                type(bound) is int or (type(bound) is float and math.isfinite(bound))
            ):
                raise ImproperlyConfigured(
                    f"{where}: {label} {bound!r} is not a finite int or float."
                )
        if self.type == "array":
            if self.items not in ("integer", "number") and self.format != "decimal":
                raise ImproperlyConfigured(
                    f"{where}: a bound on an array describes each element, which must be a "
                    "number or a decimal string; declare items 'integer' or 'number', or "
                    "items 'string' with format 'decimal'."
                )
        elif self.type not in ("integer", "number") and self.format != "decimal":
            raise ImproperlyConfigured(
                f"{where}: a bound describes a number or a decimal string; "
                f"this parameter is {self.type!r}."
            )
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ImproperlyConfigured(
                f"{where}: minimum {self.minimum!r} is past maximum {self.maximum!r}."
            )

    def _check_element_format(self, where: str) -> None:
        """Refuse a format on an array whose element cannot carry it."""
        if self.items != "string":
            raise ImproperlyConfigured(
                f"{where}: a format on an array describes each element, which must be a "
                "string; declare items 'string'."
            )
        if self.format != "decimal":
            raise ImproperlyConfigured(
                f"{where}: an array's element takes no format but 'decimal'; "
                f"{self.format!r} describes a string parameter alone."
            )

    def _check_lengths(self, where: str) -> None:
        """Refuse a length no reader can act on: no count, or one on a value that is no array."""
        for label, length in (("min_length", self.min_length), ("max_length", self.max_length)):
            if length is not None and not (type(length) is int and length >= 0):
                raise ImproperlyConfigured(
                    f"{where}: {label} {length!r} is not a non-negative int."
                )
        if self.type != "array":
            raise ImproperlyConfigured(
                f"{where}: a length describes an array; this parameter is {self.type!r}."
            )
        if (
            self.min_length is not None
            and self.max_length is not None
            and self.min_length > self.max_length
        ):
            raise ImproperlyConfigured(
                f"{where}: min_length {self.min_length!r} is past max_length {self.max_length!r}."
            )

    def _normalize_choice_labels(
        self, where: str, labels: Mapping[Any, str] | Iterable[tuple[Any, str]]
    ) -> None:
        """Store ``choice_labels`` as pairs, refusing a label for no declared choice."""
        pairs = canonical_choices(
            self.format, labels.items() if isinstance(labels, Mapping) else labels
        )
        if self.choices is None:
            raise ImproperlyConfigured(
                f"{where}: choice_labels name declared choices; declare choices."
            )
        stray = [value for value, _label in pairs if value not in self.choices]
        if stray:
            raise ImproperlyConfigured(
                f"{where}: choice_labels label {stray!r}, which choices do not list."
            )
        object.__setattr__(self, "choice_labels", pairs)

    @property
    def nested(self) -> Parameters | None:
        """The Parameters inside this one: an object's fields, or an array's rows."""
        if self.type == "object":
            return self.fields
        if self.type == "array" and not isinstance(self.items, str):
            return self.items
        return None


@dataclass(frozen=True)
class Parameters:
    """An ordered set of [`Parameter`][django_service_specs.parameters.parameters.Parameter]."""

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
