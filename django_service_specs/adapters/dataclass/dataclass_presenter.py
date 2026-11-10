from __future__ import annotations

from functools import cached_property
from typing import Any

from django_service_specs.adapters.dataclass.utils import (
    FieldShape,
    Shape,
    check_dataclass,
    encode_fields,
    read_fields,
)
from django_service_specs.adapters.utils import choice_pairs
from django_service_specs.output.output import Output, OutputField
from django_service_specs.output.presenter import Presenter


class DataclassPresenter(Presenter):
    """An operation's output declared as a dataclass, rendered from any object."""

    def __init__(self, cls: type[Any]) -> None:
        check_dataclass(cls, label="DataclassPresenter")
        self.cls = cls

    @cached_property
    def _fields(self) -> tuple[FieldShape, ...]:
        # Read on first use, since specs are built at import time.
        return read_fields(self.cls)

    def output(self) -> Output:
        """The dataclass's fields as an Output, in declaration order. Never queries."""
        return _output(self._fields)

    def present(self, value: Any) -> Any:
        """One value's declared fields, read by attribute and encoded to JSON-like data."""
        return None if value is None else encode_fields(self._fields, value)


def _output(fields: tuple[FieldShape, ...]) -> Output:
    return Output(tuple(_output_field(fs) for fs in fields))


def _output_field(fs: FieldShape) -> OutputField:
    shape = fs.shape
    # A list's choices are its element's, as on the Parameter side.
    element = shape if shape.items is None else shape.items
    return OutputField(
        fs.name,
        shape.type,
        format=shape.format,
        nullable=shape.nullable,
        choices=choice_pairs(element.choices, element.enum),
        always_present=not fs.omittable,
        marking=fs.marking,
        fields=None if shape.fields is None else _output(shape.fields),
        items=_items(shape.items),
        items_nullable=shape.items is not None and shape.items.nullable,
    )


def _items(items: Shape | None) -> str | Output | None:
    if items is None:
        return None
    if items.fields is not None:
        return _output(items.fields)
    return items.type
