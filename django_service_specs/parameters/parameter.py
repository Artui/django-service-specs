"""``Parameter`` - one thing an operation takes, as a declaration."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import KW_ONLY, dataclass, field
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

PARAMETER_TYPES = JSON_TYPES | {"file"}
"""The types a parameter may declare: JSON's, and ``file``.

A file is what a multipart body carries beside its fields, and what a Python
caller hands a command or a task as a Django ``File``. It is no JSON type, so a
JSON caller cannot send one, and it is a parameter's alone: what comes out of an
operation is still one of the JSON types."""

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

    ``nullable`` is the parameter's own: whether the argument may be ``null``.
    ``items_nullable`` is its element's: whether a ``null`` may stand in the
    array where an element would, as in ``list[int | None]``. The two are
    independent, because a list that may be absent and a list that may hold
    gaps are different declarations, and an array with no declared ``items``
    admits a ``null`` element already.

    ``type`` is a JSON type or ``file``, which an array's ``items`` may name
    too. A file is a Django ``File``, an upload included, and has no
    ``choices``: it is matched by nothing a declaration could list.

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
    ``float``, a JSON number the schema can state. They exist for the bound a
    reader needs before any Validator runs: a filter whose form field has none
    hands the value to the database's integer conversion, which builds every
    digit. Any other bound - a length, a Validator's ``max_value`` - is still
    the Validator's alone.
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
    choice_labels: tuple[tuple[Any, str], ...] | None = None
    minimum: int | float | None = None
    maximum: int | float | None = None
    # Out of the hash and still in equality, so a list or dict default - which
    # the pydantic adapter reports as given - leaves the declaration hashable.
    # Equal Parameters still hash equal, which is all a hash promises; two that
    # differ only by default share one and stay unequal. This is the case the
    # ``dataclasses`` documentation names for ``hash=``: a field equality needs
    # while the others carry the hash. Freezing the value instead would change
    # the type the adapter reported and leave a dict default unhashable.
    default: Any = field(default=UNSET, hash=False)
    nullable: bool = False
    help: str | None = None

    def __post_init__(self) -> None:
        # A declaration that no reader can act on is refused where it is written,
        # so the error names the parameter rather than surfacing later as a
        # schema or a shape check that quietly ignores half of it.
        where = f"Parameter {self.name!r}"
        if self.type not in PARAMETER_TYPES:
            raise ImproperlyConfigured(
                f"{where}: type {self.type!r} is not a JSON type or a file; "
                f"use one of {sorted(PARAMETER_TYPES)}."
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
            # Normalized rather than refused, so a list reads as naturally as a
            # tuple and the frozen declaration stays hashable.
            object.__setattr__(self, "choices", tuple(self.choices))
            # The element's type for an array, since its choices constrain each
            # element. One branch to coverage, so each operand is held by its
            # own test: test_a_file_has_no_choices[file] and [array-of-files].
            if "file" in (self.type, self.items):
                raise ImproperlyConfigured(
                    f"{where}: a file is never one of a list of values; declare no choices."
                )
        if self.choice_labels is not None:
            self._normalize_choice_labels(where, self.choice_labels)
        # One branch to coverage, each side held by its own half of
        # test_a_bound_must_be_a_finite_number: [minimum-...] and [maximum-...].
        if self.minimum is not None or self.maximum is not None:
            self._check_bounds(where)

    def _check_bounds(self, where: str) -> None:
        """Refuse a bound no reader can act on: a non-number, or one on a value that is no number."""
        for label, bound in (("minimum", self.minimum), ("maximum", self.maximum)):
            # A JSON number the schema can state: ``bool`` is an ``int`` to Python
            # and no number to JSON, which ``type() is`` keeps out, and NaN and the
            # infinities have no JSON spelling. Read by type rather than through
            # ``math.isfinite`` alone, which overflows on a large ``int`` and takes
            # a ``Decimal``. One branch to coverage, so each condition is held by
            # its own test: test_a_bound_may_stand_alone (``None``),
            # test_a_bound_on_an_integer_is_inclusive (``int``) and
            # test_a_bound_must_be_a_finite_number[decimal] and [infinity].
            if bound is not None and not (
                type(bound) is int or (type(bound) is float and math.isfinite(bound))
            ):
                raise ImproperlyConfigured(
                    f"{where}: {label} {bound!r} is not a finite int or float."
                )
        # One branch to coverage, so each condition is held by its own test:
        # test_a_bound_on_an_integer_is_inclusive (the type: without it, an
        # integer's bound is refused) and test_a_decimal_string_takes_a_bound
        # (the format).
        if self.type not in ("integer", "number") and self.format != "decimal":
            raise ImproperlyConfigured(
                f"{where}: a bound describes a number or a decimal string; "
                f"this parameter is {self.type!r}."
            )
        # One branch to coverage: test_one_bound_may_equal_the_other holds the
        # comparison, and test_a_bound_may_stand_alone each ``is not None``,
        # without which an absent bound is compared and raises.
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ImproperlyConfigured(
                f"{where}: minimum {self.minimum!r} is past maximum {self.maximum!r}."
            )

    def _normalize_choice_labels(
        self, where: str, labels: Mapping[Any, str] | Iterable[tuple[Any, str]]
    ) -> None:
        """Store ``choice_labels`` as pairs, refusing a label for no declared choice."""
        pairs = tuple(
            labels.items() if isinstance(labels, Mapping) else ((v, lb) for v, lb in labels)
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
