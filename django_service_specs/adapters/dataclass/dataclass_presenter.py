"""``DataclassPresenter`` - the reference Presenter, over a standard-library dataclass."""

from __future__ import annotations

from functools import cached_property
from typing import Any

from django.db.models import Choices

from django_service_specs.adapters.dataclass.utils import (
    FieldShape,
    Shape,
    check_dataclass,
    encode_fields,
    read_fields,
)
from django_service_specs.output.output import Output
from django_service_specs.output.output_field import OutputField
from django_service_specs.output.presenter import Presenter


class DataclassPresenter(Presenter):
    """An operation's output declared as a dataclass, rendered from any object.

    ``output()`` reads the fields and annotations the way
    [`DataclassValidator`][django_service_specs.adapters.dataclass.dataclass_validator.DataclassValidator]
    does, so one dataclass declares the same types going in and coming out.

    ``present(value)`` reads each declared field **by attribute**, so the value
    may be an instance of the dataclass or anything carrying the same names: a
    model row is the case this is for, and it is never converted into the
    dataclass first. A nested dataclass field is read the same way off the
    attribute's value, and a list field may be a related manager, read
    through ``.all()`` so a prefetch is used when there is one. Encoding is
    JSON's: a ``Decimal`` as its string, a ``datetime`` or ``date`` in ISO
    8601, an ``Enum`` as its value.

    A field whose value is ``UNSET`` is left out of the rendered object, and
    only a field whose annotation admits ``UnsetType`` is declared as possibly
    absent (``always_present=False``). Labels are ``None``: a dataclass has no
    label of its own, and a reader can title-case a name as well as an adapter.

    Choices are (value, display) pairs. A Django ``Choices`` enum supplies its
    label, translated when ``output()`` is called; a plain ``Enum`` or a
    ``Literal`` has no display of its own, so the value's ``str`` stands in.

    A ``FieldMarking`` is declared on the field it marks, in its annotation:
    ``id: Annotated[int, FieldMarking.handle()]``.
    """

    def __init__(self, cls: type[Any]) -> None:
        check_dataclass(cls, label="DataclassPresenter")
        self.cls = cls

    @cached_property
    def _fields(self) -> tuple[FieldShape, ...]:
        # Read on first use, not at construction: specs are built at import
        # time, and an annotation may name a class its module cannot resolve yet.
        return read_fields(self.cls)

    def output(self) -> Output:
        """The dataclass's fields as an Output, in declaration order. Never queries."""
        return _output(self._fields)

    def present(self, value: Any) -> Any:
        """One value's declared fields, read by attribute and encoded to JSON-like data.

        ``None`` is presented as ``None``: it is JSON's null, not a row whose
        every attribute is missing.
        """
        return None if value is None else encode_fields(self._fields, value)


def _output(fields: tuple[FieldShape, ...]) -> Output:
    return Output(tuple(_output_field(fs) for fs in fields))


def _output_field(fs: FieldShape) -> OutputField:
    shape = fs.shape
    return OutputField(
        fs.name,
        shape.type,
        format=shape.format,
        nullable=shape.nullable,
        # A list's choices are its element's, as on the Parameter side.
        choices=_choice_pairs(shape if shape.items is None else shape.items),
        always_present=not fs.omittable,
        marking=fs.marking,
        fields=None if shape.fields is None else _output(shape.fields),
        items=_items(shape.items),
    )


def _items(items: Shape | None) -> str | Output | None:
    if items is None:
        return None
    if items.fields is not None:
        return _output(items.fields)
    return items.type


def _choice_pairs(shape: Shape) -> tuple[tuple[Any, str], ...] | None:
    if shape.choices is None:
        return None
    enum_cls = shape.enum
    if enum_cls is not None and issubclass(enum_cls, Choices):
        # Read per call rather than once, so the display is in the language
        # active for the reader, as Django's own choices are.
        return tuple((member.value, str(member.label)) for member in enum_cls)
    return tuple((value, str(value)) for value in shape.choices)
