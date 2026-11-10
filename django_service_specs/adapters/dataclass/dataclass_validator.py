from __future__ import annotations

import dataclasses
import datetime as dt
from collections.abc import Callable, Mapping
from decimal import Decimal, InvalidOperation
from functools import cached_property
from typing import Any, TypeVar

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.utils.translation import gettext

from django_service_specs.adapters.dataclass.utils import (
    FieldShape,
    Shape,
    check_dataclass,
    encode,
    read_fields,
)
from django_service_specs.adapters.utils import choice_labels, element_format, scalar_type
from django_service_specs.parameters.coded_message import CodedMessage
from django_service_specs.parameters.expected_type_refusal import expected_type_refusal
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.non_field_errors import NON_FIELD_ERRORS
from django_service_specs.parameters.parameters import Parameter, Parameters
from django_service_specs.parameters.utils import coded_messages
from django_service_specs.types.unset import UNSET
from django_service_specs.validation.validated import Validated
from django_service_specs.validation.validation_context import ValidationContext
from django_service_specs.validation.validator import Validator

_T = TypeVar("_T")


class DataclassValidator(Validator):
    """A Validator whose declaration is a standard-library dataclass."""

    supports_partial = False

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
        """The built instance's ``__init__`` fields, by name, or ``InvalidArguments``."""
        return self._validated(arguments, context).values

    def validated(self, arguments: Mapping[str, Any], context: ValidationContext) -> Validated:
        """The built instance as the call's ``data``, and its ``__init__`` fields as the values."""
        return self._validated(arguments, context)

    def _validated(self, arguments: Mapping[str, Any], context: ValidationContext) -> Validated:
        # Neither public method calls the other, so a subclass may extend either.
        if context.partial:
            raise ImproperlyConfigured(
                f"DataclassValidator({self.cls.__qualname__}) cannot validate a partial call: "
                "a dataclass instance holds every field. Drop partial and declare the fields "
                "an update may leave out as X | UnsetType, or validate with a FormValidator."
            )
        instance = _build(self.cls, self._fields, arguments)
        values = {fs.name: getattr(instance, fs.name) for fs in _inputs(self._fields)}
        return Validated(values=values, data=instance)


class _Refused(Exception):
    """One value refused: a leaf of the detail tree, carried to the key it belongs under."""

    def __init__(self, message: CodedMessage) -> None:
        super().__init__(message)
        self.message = message


def _inputs(fields: tuple[FieldShape, ...]) -> tuple[FieldShape, ...]:
    # A field declared ``init=False`` is computed, so no caller supplies it.
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
        # An array's format is its element's, and only a decimal's is one.
        format=shape.format if shape.items is None else element_format(shape.items.format),
        items=_items(shape.items),
        items_nullable=shape.items is not None and shape.items.nullable,
        fields=None if shape.fields is None else _parameters(shape.fields),
        choices=shape.choices if shape.items is None else shape.items.choices,
        choice_labels=choice_labels((shape if shape.items is None else shape.items).enum),
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
        key: [CodedMessage(gettext("Unknown argument."), "unknown")]
        for key in arguments
        if key not in declared
    }
    values: dict[str, Any] = {}
    for fs in inputs:
        if fs.name not in arguments:
            if fs.has_default:
                continue
            if fs.omittable:
                values[fs.name] = UNSET
            else:
                errors[fs.name] = [CodedMessage(gettext("This field is required."), "required")]
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
        raise InvalidArguments({NON_FIELD_ERRORS: [CodedMessage(str(exc), "invalid")]}) from exc
    except ValidationError as exc:
        raise InvalidArguments({NON_FIELD_ERRORS: coded_messages([exc])}) from exc


def _decode(shape: Shape, value: Any) -> Any:
    """``value`` decoded into what ``shape`` declares."""
    if value is None:
        if shape.nullable:
            return None
        raise _Refused(CodedMessage(gettext("This field cannot be null."), "null"))
    if shape.fields is not None:
        if not isinstance(value, Mapping):
            raise _Refused(expected_type_refusal("object"))
        return _build(shape.python, shape.fields, value)
    if shape.items is not None:
        if not isinstance(value, list):
            raise _Refused(expected_type_refusal("array"))
        return list(_decode_members(shape.items, dict(enumerate(value))).values())
    if shape.values is not None:
        if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
            raise _Refused(expected_type_refusal("object"))
        return _decode_members(shape.values, value)
    if shape.choices is not None:
        return _decode_choice(shape, shape.choices, value)
    return _decode_scalar(shape, value)


def _decode_members(shape: Shape, members: Mapping[Any, Any]) -> dict[Any, Any]:
    """Each member of a list, by index, or of a dict, by key, decoded as ``shape``."""
    decoded: dict[Any, Any] = {}
    found: dict[Any, Any] = {}
    for key, member in members.items():
        try:
            decoded[key] = _decode(shape, member)
        except InvalidArguments as exc:
            found[key] = exc.detail
        except _Refused as exc:
            found[key] = (
                {NON_FIELD_ERRORS: [exc.message]} if shape.fields is not None else [exc.message]
            )
    if found:
        raise InvalidArguments(found)
    return decoded


def _decode_choice(shape: Shape, choices: tuple[Any, ...], value: Any) -> Any:
    # The JSON type first: ``True == 1`` in Python, so ``true`` would pass as ``1``.
    if not _fits(shape.type, value):
        raise _Refused(expected_type_refusal(shape.type))
    if value not in choices:
        raise _Refused(
            CodedMessage(
                gettext("Select a valid choice. %(value)s is not one of the available choices.")
                % {"value": value},
                "invalid_choice",
            )
        )
    enum_cls = shape.enum
    return value if enum_cls is None else enum_cls(value)


def _decode_scalar(shape: Shape, value: Any) -> Any:
    # An integer past a float's range: JSON numbers have none, so it is handed on.
    python = shape.python
    if python is Decimal:
        return _decode_decimal(value)
    if python is dt.datetime:
        return _decode_datetime(value)
    if python is dt.date:
        return _decode_date(value)
    if not _fits(shape.type, value):
        raise _Refused(expected_type_refusal(shape.type))
    if python is not float:
        return value
    try:
        return float(value)
    except OverflowError:
        raise _Refused(CodedMessage(gettext("Enter a number."), "invalid")) from None


def _decode_decimal(value: Any) -> Decimal:
    # A float through ``str``, keeping the digits JSON carried, not binary expansion.
    if scalar_type(value) not in ("string", "integer", "number"):
        raise _Refused(expected_type_refusal("decimal"))
    try:
        decoded = Decimal(str(value) if isinstance(value, float) else value)
    except InvalidOperation:
        raise _Refused(CodedMessage(gettext("Enter a number."), "invalid")) from None
    if not decoded.is_finite():
        raise _Refused(CodedMessage(gettext("Enter a number."), "invalid"))
    return decoded


def _decode_datetime(value: Any) -> dt.datetime:
    # Parses as ``forms.DateTimeField`` does, not as pydantic does.
    parsed = _parse(parse_datetime, value)
    if parsed is None:
        raise _Refused(CodedMessage(gettext("Enter a valid date/time."), "invalid"))
    if settings.USE_TZ and timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    return parsed


def _decode_date(value: Any) -> dt.date:
    parsed = _parse(parse_date, value)
    if parsed is None:
        raise _Refused(CodedMessage(gettext("Enter a valid date."), "invalid"))
    return parsed


def _parse(parse: Callable[[str], _T | None], value: Any) -> _T | None:
    """Django's parser over a string, ``None`` for anything it cannot read."""
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
