"""``DataclassValidator`` - the reference Validator, over a standard-library dataclass."""

from __future__ import annotations

import dataclasses
import datetime as dt
from collections.abc import Callable, Mapping
from decimal import Decimal, InvalidOperation
from functools import cached_property
from typing import Any, TypeVar

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.utils.translation import gettext

from django_service_specs.adapters.dataclass.utils import (
    FieldShape,
    Shape,
    check_dataclass,
    encode,
    read_fields,
    scalar_type,
)
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.parameter import Parameter
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.parameters.utils import NON_FIELD_ERRORS, expected_type
from django_service_specs.types.unset import UNSET
from django_service_specs.validation.validation_context import ValidationContext
from django_service_specs.validation.validator import Validator

_T = TypeVar("_T")


class DataclassValidator(Validator):
    """A Validator whose declaration is a standard-library dataclass.

    The reference adapter: what any adapter owes the kernel, done with nothing
    but the standard library and Django. ``parameters()`` reads the fields and
    their annotations; ``validate()`` decodes JSON-like arguments into those
    types and builds the instance, nested dataclasses included.

    The annotations it reads, and what each declares:

    - ``str``, ``int``, ``float``, ``bool``: their JSON types. ``float`` takes an
      integer as well, since JSON writes ``2.0`` as ``2``; nothing else crosses
      types, so ``true`` is not an ``int``.
    - ``Decimal``, ``datetime``, ``date``: a string, with the format it decodes
      from. A decimal takes a JSON number too, as every decimal validator does.
    - ``X | None``: nullable.
    - ``Literal[...]`` and an ``Enum`` (Django's ``TextChoices`` and
      ``IntegerChoices`` included): choices, of the JSON type the values
      share. An ``Enum`` decodes to the member.
    - ``list[X]``: an array; ``list[SomeDataclass]`` is an array of rows, each
      declared as nested Parameters. For any other element, ``Parameter.items``
      can hold only its JSON type, so a list of decimals or of choices is
      declared as an array of strings, and the rest is decoded here.
    - a dataclass: an object, with its own fields as nested Parameters.
    - ``X | UnsetType``: the argument may be left out, with or without a
      default, and the field then holds ``UNSET`` rather than a value a
      service would act on. It adds no JSON type, since no wire can send it.

    A field with a default, or a ``default_factory``, is optional, and one with
    neither is required. Only a plain default is reported as the Parameter's
    ``default``: a factory's value is computed per instance, so it is not a
    declaration a transport could print. A field declared ``init=False`` is
    the dataclass's to compute, so it is neither taken nor returned.
    ``Annotated`` is looked through, and an annotation outside this list is
    refused with ``ImproperlyConfigured`` naming the field, never read as a
    string.

    **A row that updates must declare its key.** A relation write matches an
    incoming row to an existing one by its primary key, so a row dataclass used
    for an update needs ``pk: int | None = None``: present for a row that
    exists, absent for a new one. Without it no incoming row matches an
    existing one, and every update replaces every row. Nothing fails when that
    happens, which is why it is written down here.

    **Time zones follow Django's forms**, not pydantic: an offset-less
    date-time is made aware in the current time zone when ``USE_TZ`` is on,
    so a date-time means the same thing whichever library validated it.

    **Every failure is reported, not the first**, as one ``InvalidArguments``
    whose detail is addressed by path: ``{"books": {1: {"title": [...]}}}``
    for a field inside the second row, only the rows that failed, and a message
    about a row itself under ``non_field_errors`` inside it. A ``ValueError``
    or Django ``ValidationError`` raised by the dataclass's own
    ``__post_init__`` is a message about that object, and lands there too.

    It is correct without the shape check in front of it, for a caller that
    uses it directly: a wrong JSON type is a refusal, not a crash, and an
    argument no field declares is refused as the dataclass's own constructor
    would refuse it.

    The annotations are read on first use rather than at construction, for
    the reason a spec's parameters are: specs are built at import time, and an
    annotation may name a class its module cannot resolve yet.
    """

    def __init__(self, cls: type[Any]) -> None:
        check_dataclass(cls, label="DataclassValidator")
        self.cls = cls

    @cached_property
    def _fields(self) -> tuple[FieldShape, ...]:
        return read_fields(self.cls)

    def parameters(self) -> Parameters:
        """The dataclass's ``__init__`` fields, as Parameters. Never queries."""
        return _parameters(self._fields)

    def validate(self, arguments: Mapping[str, Any], context: ValidationContext) -> dict[str, Any]:
        """The built instance's ``__init__`` fields, by name, or ``InvalidArguments``.

        Nested values stay dataclass instances, which is what the mutation
        helpers read a row from.
        """
        instance = _build(self.cls, self._fields, arguments)
        return {fs.name: getattr(instance, fs.name) for fs in _inputs(self._fields)}


class _Refused(Exception):
    """One value refused: a leaf of the detail tree, carried to the key it belongs under."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _inputs(fields: tuple[FieldShape, ...]) -> tuple[FieldShape, ...]:
    # A field declared ``init=False`` is computed by the dataclass, not taken
    # from a caller, so it is neither a parameter nor an argument.
    return tuple(fs for fs in fields if fs.field.init)


def _parameters(fields: tuple[FieldShape, ...]) -> Parameters:
    return Parameters(tuple(_parameter(fs) for fs in _inputs(fields)))


def _parameter(fs: FieldShape) -> Parameter:
    shape = fs.shape
    default = fs.field.default
    return Parameter(
        fs.name,
        shape.type,
        required=fs.required,
        format=shape.format,
        items=_items(shape.items),
        fields=None if shape.fields is None else _parameters(shape.fields),
        choices=shape.choices,
        # Encoded, so a Decimal or an Enum default is reported as the argument
        # that would be sent for it. ``UNSET`` stays ``UNSET``: no default.
        default=UNSET if default is dataclasses.MISSING else encode(shape, default),
        nullable=shape.nullable,
    )


def _items(items: Shape | None) -> str | Parameters | None:
    if items is None:
        return None
    if items.fields is not None:
        return _parameters(items.fields)
    return items.type


def _build(cls: type[Any], fields: tuple[FieldShape, ...], arguments: Mapping[str, Any]) -> Any:
    """An instance of ``cls`` from JSON-like arguments, or every reason it cannot be one."""
    inputs = _inputs(fields)
    declared = {fs.name for fs in inputs}
    errors: dict[Any, Any] = {
        key: [gettext("Unknown argument.")] for key in arguments if key not in declared
    }
    values: dict[str, Any] = {}
    for fs in inputs:
        if fs.name not in arguments:
            if fs.has_default:
                # Left to the dataclass, which fills a default or runs a
                # factory exactly as it does for any other caller.
                continue
            if fs.omittable:
                values[fs.name] = UNSET
            else:
                errors[fs.name] = [gettext("This field is required.")]
            continue
        try:
            values[fs.name] = _decode(fs.shape, arguments[fs.name])
        except InvalidArguments as exc:
            errors[fs.name] = exc.detail
        except _Refused as exc:
            errors[fs.name] = [exc.message]
    if errors:
        raise InvalidArguments(errors)
    try:
        return cls(**values)
    except ValueError as exc:
        # ``__post_init__`` is the only place a dataclass can state a rule
        # across its fields, and raising is how it states one.
        raise InvalidArguments({NON_FIELD_ERRORS: [str(exc)]}) from exc
    except ValidationError as exc:
        raise InvalidArguments({NON_FIELD_ERRORS: exc.messages}) from exc


def _decode(shape: Shape, value: Any) -> Any:
    """``value`` decoded into what ``shape`` declares.

    Raises ``_Refused`` for a leaf, and ``InvalidArguments`` carrying the
    subtree for an object or a list, which the caller places under its own key.
    """
    if value is None:
        if shape.nullable:
            return None
        raise _Refused(gettext("This field cannot be null."))
    if shape.fields is not None:
        if not isinstance(value, Mapping):
            raise _Refused(expected_type("object"))
        return _build(shape.python, shape.fields, value)
    if shape.items is not None:
        if not isinstance(value, list):
            raise _Refused(expected_type("array"))
        return _decode_rows(shape.items, value)
    if shape.choices is not None:
        return _decode_choice(shape, shape.choices, value)
    return _decode_scalar(shape, value)


def _decode_rows(items: Shape, rows: list[Any]) -> list[Any]:
    decoded: list[Any] = []
    found: dict[int, Any] = {}
    for index, row in enumerate(rows):
        try:
            decoded.append(_decode(items, row))
        except InvalidArguments as exc:
            found[index] = exc.detail
        except _Refused as exc:
            # A message about a row of objects is about the row itself, so it
            # sits inside the row; a scalar element has no inside.
            found[index] = (
                {NON_FIELD_ERRORS: [exc.message]} if items.fields is not None else [exc.message]
            )
    if found:
        # Keyed by index, and only the rows that failed, so a transport can
        # point at row 1 without the caller counting empty entries.
        raise InvalidArguments(found)
    return decoded


def _decode_choice(shape: Shape, choices: tuple[Any, ...], value: Any) -> Any:
    # The JSON type first: ``True == 1`` in Python, so without it ``true``
    # would be accepted as the integer choice ``1``.
    if not _fits(shape.type, value):
        raise _Refused(expected_type(shape.type))
    if value not in choices:
        raise _Refused(
            gettext("Select a valid choice. %(value)s is not one of the available choices.")
            % {"value": value}
        )
    enum_cls = shape.enum
    return value if enum_cls is None else enum_cls(value)


def _decode_scalar(shape: Shape, value: Any) -> Any:
    python = shape.python
    if python is Decimal:
        return _decode_decimal(value)
    if python is dt.datetime:
        return _decode_datetime(value)
    if python is dt.date:
        return _decode_date(value)
    if not _fits(shape.type, value):
        raise _Refused(expected_type(shape.type))
    return float(value) if python is float else value


def _decode_decimal(value: Any) -> Decimal:
    if scalar_type(value) not in ("string", "integer", "number"):
        raise _Refused(expected_type("decimal"))
    try:
        # Through ``str`` so a float gives the digits JSON carried, not its
        # binary expansion: ``Decimal(0.1)`` is not ``Decimal("0.1")``.
        decoded = Decimal(str(value))
    except InvalidOperation:
        raise _Refused(gettext("Enter a number.")) from None
    if not decoded.is_finite():
        # Django's DecimalField refuses NaN and infinity too; neither is an
        # amount, and neither can be stored.
        raise _Refused(gettext("Enter a number."))
    return decoded


def _decode_datetime(value: Any) -> dt.datetime:
    parsed = _parse(parse_datetime, value)
    if parsed is None:
        raise _Refused(gettext("Enter a valid date/time."))
    if settings.USE_TZ and timezone.is_naive(parsed):
        # What forms.DateTimeField does, and what pydantic does not: the
        # kernel sides with forms, so an offset-less value means the same
        # instant whichever library validated it.
        parsed = timezone.make_aware(parsed)
    return parsed


def _decode_date(value: Any) -> dt.date:
    parsed = _parse(parse_date, value)
    if parsed is None:
        raise _Refused(gettext("Enter a valid date."))
    return parsed


def _parse(parse: Callable[[str], _T | None], value: Any) -> _T | None:
    """Django's parser over a string, ``None`` for anything it cannot read.

    The parser returns ``None`` for a malformed string and raises
    ``ValueError`` for a well-formed one that names no real day, such as
    ``2024-02-30``; to a caller both are the same mistake.
    """
    if not isinstance(value, str):
        return None
    try:
        return parse(value)
    except ValueError:
        return None


def _fits(json_type: str, value: Any) -> bool:
    found = scalar_type(value)
    # An integer is a number in JSON, so a number field takes one.
    return found == json_type or (json_type == "number" and found == "integer")
