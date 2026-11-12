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

    ``nullable`` is the parameter's own: whether the argument may be ``null``.
    ``items_nullable`` is its element's: whether a ``null`` may stand in the
    array where an element would, as in ``list[int | None]``. The two are
    independent, because a list that may be absent and a list that may hold
    gaps are different declarations, and an array with no declared ``items``
    admits a ``null`` element already.

    ``type`` is a JSON type or ``file``, which an array's ``items`` may name
    too. A file is a Django ``File``, an upload included, and has no
    ``choices``: it is matched by nothing a declaration could list.

    ``type`` may also be ``any``, for a parameter that declares no type, as an
    unannotated argument does: ``3`` and ``"abc"`` are both one. Its value is
    handed on exactly as it arrived, never read as a number or a boolean, so
    a query string's ``"3"`` stays the string ``"3"``; ``null`` is accepted
    only where ``nullable`` says so, as for every other type. Having no type,
    it describes nothing a type would - no ``choices``, ``format``, ``fields``,
    ``items`` or bound - and an array's ``items`` never name it, since an
    array that declares no ``items`` takes any element already.

    ``choice_labels`` names the choices for a reader: a mapping of a choice to
    its label, or Django's ``choices`` spelling, pairs of the two, which keeps
    apart the ``1`` and ``True`` a mapping's keys would merge. A choice may go
    unlabelled. The labels constrain nothing, so the shape check reads only
    ``choices``; the schema carries them as titles. They are stored as a tuple
    of pairs, and a label may be a lazy translation, rendered when the schema
    is built.

    ``default`` is [`UNSET`][django_service_specs.types.unset.UNSET] when none is
    declared, so a default of ``None`` stays a real default. It is reported, not
    applied: whether an omitted argument arrives as the default, as ``None`` or
    not at all is the validating library's behaviour, and each adapter reports
    what its library does. It takes no part in the hash, so a declaration with
    a list or dict default is as hashable as any other, while equality still
    tells two defaults apart.

    ``minimum`` and ``maximum`` bound a number, inclusively: an ``integer``, a
    ``number``, or a ``decimal`` string, which is compared as the decimal it
    spells, so ``"1E+999999999"`` is past a bound of ``1e50`` without ever
    being built as the integer it names. Each is an ``int`` or a finite
    ``float``, a JSON number. The schema states them on an ``integer`` and a
    ``number`` and not on a decimal string, where JSON Schema gives them no
    meaning; the shape check enforces all three. They exist for the bound a
    reader needs before any Validator runs: a filter whose form field has none
    hands the value to the database's integer conversion, which builds every
    digit. Any other bound - a string's length, a Validator's ``max_value`` -
    is still the Validator's alone.

    **On an array,** ``format``, ``minimum`` **and** ``maximum`` **describe
    each element**, as ``choices`` do: an array of ``integer`` or ``number``
    takes a bound, and an array of ``string`` takes ``format="decimal"`` and
    then a bound too, which is what a django-filter CSV number filter
    declares. A decimal is the one format an element takes: a number element
    is read as a float on the way, which rounds a fraction past a float's
    precision, where a decimal string is compared and handed on as it was
    sent. Any other format on an array, and a format or a bound on an
    element that cannot carry it, is refused. The list's own count is
    ``min_length`` and ``max_length``'s, so an array may carry both pairs.

    ``min_length`` and ``max_length`` bound how many elements an ``array``
    takes, inclusively, and are refused on anything else: each a
    non-negative ``int``. They are checked on the list whole, before any
    element is read, so a list past its maximum costs no per-element work.
    **An array that declares no** ``max_length`` **is still bounded**, by the
    ``SERVICE_SPECS_MAX_ARRAY_LENGTH`` setting, 1000 unless the project sets
    another count or ``None``: a list a caller controls the length of is a
    cost the caller controls, and the setting is read at the call, so it
    applies to a declaration built before settings were configured. A
    declared ``max_length`` outranks it either way, wider or narrower.
    ``min_length`` has no default: an empty list is taken unless one says
    otherwise.

    ``json_schema_extra`` carries the JSON Schema keywords no field of a
    Parameter spells - a ``pattern``, a string's ``maxLength``,
    ``uniqueItems`` - as a mapping of keyword to value, held as a deep copy of
    its own. It is how an adapter whose library declares more than a
    Parameter carries keeps it on every route rather than on its own.
    [`parameters_schema`][django_service_specs.schema.parameters_schema.parameters_schema]
    adds its keys to this parameter's node. A keyword a field states there is
    refused here, naming the field, whether or not this parameter sets it:
    ``type``, ``format`` (so a custom format is refused too: ``format`` is a
    field), ``default``, the choices' ``enum``, ``anyOf`` and ``const``, the
    bounds, ``minItems`` and ``maxItems``, ``items``, ``description`` from
    ``help``, and ``properties``, ``required`` and ``additionalProperties``
    from ``fields``. Either side winning would advertise what the declaration
    does not say or drop what was written, and refusing the keyword only when
    one build stated it would make the same declaration valid until the array
    cap came on or a spec moved to ``REJECT``. A value JSON cannot carry - a
    ``Decimal``, a lazy translation, at any depth - is refused too, naming its
    key. It is advertised, not enforced: the shape check never reads it, so
    what it states holds only where the spec's Validator enforces it
    (test_it_is_advertised_and_not_enforced_by_the_shape_check).
    It takes no part in the hash, as ``default`` does not, and still in equality.

    ``reflected`` says the parameter was read off a callable's signature
    rather than written by an author, as djangorestframework-services reads a
    selector's, a target lookup's or a spread service's parameters into
    ``reads``. It counts on a ``reads`` parameter alone - a selector spec's,
    a target selector's or a service spec's - and only at dispatch: a
    reflected read named like a seed the call's ``pool_seeds`` registers
    leaves that call's argument set, and the seed fills it, where an unmarked
    one is refused as a configuration error
    (test_a_reflected_read_a_registered_seed_is_named_like_is_the_seed_s).
    On a Validator field or a shape it changes nothing. No schema carries it,
    since it describes where a declaration came from rather than what a caller
    sends; it takes part in equality and the hash, because two declarations
    that differ in it dispatch differently
    (test_reflected_is_compared_and_hashed_and_never_in_the_schema).
    """

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
    """An ordered set of [`Parameter`][django_service_specs.parameters.parameters.Parameter].

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
