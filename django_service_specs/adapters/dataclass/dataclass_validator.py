"""``DataclassValidator`` - the reference Validator, over a standard-library dataclass."""

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
    scalar_type,
)
from django_service_specs.adapters.utils import choice_labels, element_format
from django_service_specs.parameters.coded_message import CodedMessage
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.non_field_errors import NON_FIELD_ERRORS
from django_service_specs.parameters.parameters import Parameter, Parameters
from django_service_specs.parameters.utils import coded_messages, expected_type
from django_service_specs.types.unset import UNSET
from django_service_specs.validation.validated import Validated
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
      types, so ``true`` is not an ``int``. An integer past a float's range
      is refused as no number, in the words the shape check refuses a
      non-finite one in, since no finite float stands for it.
    - ``Decimal``, ``datetime``, ``date``: a string, with the format it decodes
      from. A decimal takes a JSON number too, as every decimal validator does,
      and an integer exactly, whatever its digits.
    - ``X | None``: nullable. Inside a list, ``list[X | None]``, it is the
      element that is, declared as ``items_nullable`` and not as the array's
      own nullability.
    - ``Literal[...]`` and an ``Enum`` (Django's ``TextChoices`` and
      ``IntegerChoices`` included): choices, of the JSON type the values
      share. An ``Enum`` decodes to the member.
    - ``list[X]``: an array; ``list[SomeDataclass]`` is an array of rows, each
      declared as nested Parameters. For any other element, ``Parameter.items``
      holds its JSON type, and what else describes the element is declared on
      the array, where it constrains each element: a list of choices declares
      them there, and ``list[Decimal]`` the ``decimal`` format, so each
      element is read as a scalar decimal is, a JSON number included, and a
      query string's ``?prices=1.5,2.25`` is two of them. A list of dates or
      date-times is an array of strings, since an element takes no other
      format, and is decoded here.
    - A list declares no length, since a dataclass has no way to state one,
      so the shape check in front of this Validator holds it to the
      ``SERVICE_SPECS_MAX_ARRAY_LENGTH`` setting, 1000 by default. A list a
      caller may send more of is declared with a Validator that states its
      length, such as a pydantic model's ``Field(max_length=...)``, or under
      a larger setting.
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

    # A partial spec over it is refused when declared: see ``validate()``.
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
        """The built instance's ``__init__`` fields, by name, or ``InvalidArguments``.

        Nested values stay dataclass instances, which is what the mutation
        helpers read a row from. A partial call is refused: see ``validated()``.
        """
        return self._validated(arguments, context).values

    def validated(self, arguments: Mapping[str, Any], context: ValidationContext) -> Validated:
        """The built instance as the call's ``data``, and its ``__init__`` fields as the values.

        A service declaring ``data`` receives the instance, typed as the
        dataclass, where 0.4 handed it the fields as a dict; one declaring the
        fields by name receives them as before. The values are the instance's
        own attributes, so ``data.title`` and ``title`` are one object.

        **A partial call is refused** with ``ImproperlyConfigured``, because a
        dataclass instance holds every field and a partial call may leave any
        out. Building one anyway would mean a value the field's annotation does
        not admit standing in for each field not sent, or no instance and no
        ``__post_init__`` at all. A field an update may leave out is declared
        ``X | UnsetType``, which every call honours; a spec whose calls are
        partial uses a Validator that can return only what was sent.
        ``supports_partial`` is ``False``, so a ``ServiceSpec`` declaring
        ``partial=True`` over this Validator is refused when it is built, and
        this refusal answers only a caller using it directly.
        """
        return self._validated(arguments, context)

    def _validated(self, arguments: Mapping[str, Any], context: ValidationContext) -> Validated:
        # Neither public method calls the other, so a subclass may extend
        # either through the other, as one binding a value in ``pool`` on top
        # of ``validate()`` does, without the two calling each other forever.
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
        # An array's format is its element's, and only a decimal's is one.
        format=shape.format if shape.items is None else element_format(shape.items.format),
        items=_items(shape.items),
        # ``list[X | None]``: the element's own nullability, which the array's
        # is not. Declared, or the shape check refuses the null the library takes.
        items_nullable=shape.items is not None and shape.items.nullable,
        fields=None if shape.fields is None else _parameters(shape.fields),
        # A list's choices are its element's: an array's choices constrain each
        # element, and ``items`` can hold only the element's JSON type.
        choices=shape.choices if shape.items is None else shape.items.choices,
        choice_labels=choice_labels((shape if shape.items is None else shape.items).enum),
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
        key: [CodedMessage(gettext("Unknown argument."), "unknown")]
        for key in arguments
        if key not in declared
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
        # ``__post_init__`` is the only place a dataclass can state a rule
        # across its fields, and raising is how it states one.
        # A ``ValueError`` carries no code, so it says ``"invalid"``, DRF's
        # default for a message raised with none.
        raise InvalidArguments({NON_FIELD_ERRORS: [CodedMessage(str(exc), "invalid")]}) from exc
    except ValidationError as exc:
        raise InvalidArguments({NON_FIELD_ERRORS: coded_messages([exc])}) from exc


def _decode(shape: Shape, value: Any) -> Any:
    """``value`` decoded into what ``shape`` declares.

    Raises ``_Refused`` for a leaf, and ``InvalidArguments`` carrying the
    subtree for an object or a list, which the caller places under its own key.
    """
    if value is None:
        if shape.nullable:
            return None
        raise _Refused(CodedMessage(gettext("This field cannot be null."), "null"))
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
            CodedMessage(
                gettext("Select a valid choice. %(value)s is not one of the available choices.")
                % {"value": value},
                "invalid_choice",
            )
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
    if python is not float:
        return value
    try:
        return float(value)
    except OverflowError:
        # An integer past a float's range: JSON's number has none, so the
        # shape check hands it on, and ``float`` raises rather than refusing.
        # No finite float stands for it, which is the shape check's own
        # refusal of a non-finite number, in the same words
        # (test_an_integer_past_a_float_s_range_is_no_number).
        raise _Refused(CodedMessage(gettext("Enter a number."), "invalid")) from None


def _decode_decimal(value: Any) -> Decimal:
    if scalar_type(value) not in ("string", "integer", "number"):
        raise _Refused(expected_type("decimal"))
    try:
        # A float through ``str`` so it gives the digits JSON carried, not its
        # binary expansion: ``Decimal(0.1)`` is not ``Decimal("0.1")``. Anything
        # else as it is, since an int is a Decimal exactly, and ``str`` refuses
        # one past 4300 digits from Python 3.10.7 on
        # (test_a_decimal_sent_as_an_integer_is_read_whatever_its_digits).
        decoded = Decimal(str(value) if isinstance(value, float) else value)
    except InvalidOperation:
        raise _Refused(CodedMessage(gettext("Enter a number."), "invalid")) from None
    if not decoded.is_finite():
        # Django's DecimalField refuses NaN and infinity too; neither is an
        # amount, and neither can be stored.
        raise _Refused(CodedMessage(gettext("Enter a number."), "invalid"))
    return decoded


def _decode_datetime(value: Any) -> dt.datetime:
    parsed = _parse(parse_datetime, value)
    if parsed is None:
        raise _Refused(CodedMessage(gettext("Enter a valid date/time."), "invalid"))
    if settings.USE_TZ and timezone.is_naive(parsed):
        # What forms.DateTimeField does, and what pydantic does not: the
        # kernel sides with forms, so an offset-less value means the same
        # instant whichever library validated it.
        parsed = timezone.make_aware(parsed)
    return parsed


def _decode_date(value: Any) -> dt.date:
    parsed = _parse(parse_date, value)
    if parsed is None:
        raise _Refused(CodedMessage(gettext("Enter a valid date."), "invalid"))
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
