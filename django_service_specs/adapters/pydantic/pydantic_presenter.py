"""``PydanticPresenter`` - a Presenter over a pydantic model."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django.db.models import Choices, Manager
from pydantic import BaseModel

from django_service_specs.adapters.pydantic.utils import (
    FieldShape,
    Shape,
    check_model,
    fields_of,
    inputs,
    read_fields,
)
from django_service_specs.output.output import Output
from django_service_specs.output.output_field import OutputField
from django_service_specs.output.presenter import Presenter

_MISSING = object()
"""A field the value does not carry, left for pydantic to default or refuse."""


class PydanticPresenter(Presenter):
    """An operation's output declared as a pydantic model, rendered by that model.

    ``output()`` reads the fields as
    [`PydanticValidator`][django_service_specs.adapters.pydantic.pydantic_validator.PydanticValidator]
    does, so one model declares the same types going in and coming out, and
    adds what only the output side has:

    - each field is named for the key ``model_dump(by_alias=True)`` emits:
      its ``serialization_alias``, else its ``alias``, else its name;
    - fields declared ``exclude=True`` are not output, and each
      ``computed_field`` is, after the fields, typed by its return annotation;
    - every field is ``always_present``, because ``model_dump`` emits every
      key, except one with an ``exclude_if``, which may be dropped;
    - ``label`` is the field's ``title`` when the author set one, and ``None``
      otherwise: pydantic invents no label, and a reader can title-case a
      name as well as an adapter;
    - choices are (value, display) pairs: a Django ``Choices`` enum supplies
      its label, translated when ``output()`` is called, and a plain ``Enum``
      or a ``Literal`` has no display of its own, so the value's ``str``
      stands in;
    - a ``FieldMarking`` is declared in the field's ``Annotated`` metadata:
      ``id: Annotated[int, FieldMarking.handle()]``.

    ``present(value)`` renders with the model itself, so its serializers and
    its JSON encoding are what a caller receives. The value may be an instance
    of the model, a model row, any object carrying the same names, or a
    mapping keyed by field name. Anything but an instance is read one declared
    field at a time, by attribute or by key, and the model validates what was
    read: a related collection may be a manager, read through ``.all()`` so a
    prefetch is used when there is one, where pydantic's own
    ``from_attributes`` would fail on it. A field the value does not carry is
    left to the model's default.

    A value that does not fit the model raises pydantic's ``ValidationError``
    as it is. What is presented is the operation's own value rather than a
    caller's, so a mismatch is a defect in the operation, not a refusal to
    report.

    The declaration is read at construction, as the validator's is.
    """

    def __init__(self, model: type[BaseModel]) -> None:
        check_model(model, label="PydanticPresenter")
        self.model = model
        self._shape = Shape("object", python=model, fields=read_fields(model))

    def output(self) -> Output:
        """The model's output fields, then its computed fields, as an Output. Never queries."""
        return _output(fields_of(self._shape))

    def present(self, value: Any) -> Any:
        """One value, validated by the model and dumped as JSON data by alias.

        ``None`` is presented as ``None``: it is JSON's null, not a row whose
        every attribute is missing.
        """
        if value is None:
            return None
        instance = self.model.model_validate(_gather(self._shape, value))
        return instance.model_dump(mode="json", by_alias=True)


def _gather(shape: Shape, value: Any) -> Any:
    """``value`` as data the model at ``shape`` validates, read along the declaration.

    An instance of exactly the declared model is passed through: pydantic
    takes it as it is, and reading it apart would only rebuild it. Anything
    else at a model is read field by field, keyed by the name pydantic
    validates by, and a list is read row by row, through ``.all()`` when it
    is a related manager. Everything else is pydantic's to validate.
    """
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
        rows = value.all() if isinstance(value, Manager) else value
        return [_gather(shape.items, row) for row in rows]
    return value


def _field_value(value: Any, name: str) -> Any:
    # A mapping is read by key and anything else by attribute, both by the
    # field's own name: the name a model row or a plain object carries.
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
    return OutputField(
        name,
        shape.type,
        format=shape.format,
        nullable=shape.nullable,
        label=fs.label,
        choices=_choice_pairs(shape),
        always_present=fs.always_present,
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
