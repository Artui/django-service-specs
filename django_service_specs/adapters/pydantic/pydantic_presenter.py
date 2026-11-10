from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from django_service_specs.adapters.pydantic.utils import (
    FieldShape,
    Shape,
    check_model,
    fields_of,
    inputs,
    read_fields,
)
from django_service_specs.adapters.utils import choice_pairs, rows_of
from django_service_specs.output.output import Output, OutputField
from django_service_specs.output.presenter import Presenter

_MISSING = object()
"""A field the value does not carry, left for pydantic to default or refuse."""


class PydanticPresenter(Presenter):
    """An operation's output declared as a pydantic model, rendered by that model."""

    def __init__(self, model: type[BaseModel]) -> None:
        check_model(model, label="PydanticPresenter")
        self.model = model
        self._shape = Shape("object", python=model, fields=read_fields(model))

    def output(self) -> Output:
        """The model's output fields, then its computed fields, as an Output. Never queries."""
        return _output(fields_of(self._shape))

    def present(self, value: Any) -> Any:
        """One value, validated by the model and dumped as JSON data by alias."""
        if value is None:
            return None
        instance = self.model.model_validate(_gather(self._shape, value))
        return instance.model_dump(mode="json", by_alias=True)


def _gather(shape: Shape, value: Any) -> Any:
    """``value`` as data the model at ``shape`` validates, read along the declaration."""
    if value is None:
        return None
    model = shape.model
    if model is not None:
        if type(value) is model:
            return value
        data: dict[str, Any] = {}
        for fs in inputs(fields_of(shape)):
            found = _field_value(value, fs.name)
            if found is not _MISSING:
                data[fs.input_name] = _gather(fs.shape, found)
        return data
    if shape.items is not None:
        return [_gather(shape.items, row) for row in rows_of(value)]
    return value


def _field_value(value: Any, name: str) -> Any:
    # A mapping is read by key, anything else by attribute, under the field's name.
    if isinstance(value, Mapping):
        return value.get(name, _MISSING)
    return getattr(value, name, _MISSING)


def _output(fields: tuple[FieldShape, ...]) -> Output:
    # A field declared ``exclude=True`` has no output name: model_dump never emits it.
    return Output(
        tuple(_output_field(name, fs) for fs in fields if (name := fs.output_name) is not None)
    )


def _output_field(name: str, fs: FieldShape) -> OutputField:
    shape = fs.shape
    # A list's choices are its element's, as on the Parameter side.
    element = shape if shape.items is None else shape.items
    return OutputField(
        name,
        shape.type,
        format=shape.format,
        nullable=shape.nullable,
        label=fs.label,
        choices=choice_pairs(element.choices, element.enum),
        always_present=fs.always_present,
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
