from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final, get_args

from django.core.exceptions import ImproperlyConfigured
from pydantic import BaseModel, ValidationError
from pydantic_core import ErrorDetails
from pydantic_core.core_schema import ErrorType

from django_service_specs.adapters.pydantic.utils import (
    FieldShape,
    Shape,
    check_model,
    fields_of,
    inputs,
    read_fields,
)
from django_service_specs.adapters.utils import choice_labels, element_format
from django_service_specs.parameters.coded_message import CodedMessage
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.non_field_errors import NON_FIELD_ERRORS
from django_service_specs.parameters.parameters import Parameter, Parameters
from django_service_specs.validation.validated import Validated
from django_service_specs.validation.validation_context import ValidationContext
from django_service_specs.validation.validator import Validator


class PydanticValidator(Validator):
    """A Validator whose declaration is a pydantic model."""

    supports_partial = False

    def __init__(self, model: type[BaseModel]) -> None:
        check_model(model, label="PydanticValidator")
        self.model = model
        self._fields = read_fields(model)
        self._parameters = _parameters(self._fields)

    def parameters(self) -> Parameters:
        """The model's fields as Parameters, named as pydantic validates them. Never queries."""
        return self._parameters

    def validate(self, arguments: Mapping[str, Any], context: ValidationContext) -> dict[str, Any]:
        """Every field's validated value, keyed by field name, or ``InvalidArguments``."""
        return self._validated(arguments, context).values

    def validated(self, arguments: Mapping[str, Any], context: ValidationContext) -> Validated:
        """The validated instance as the call's ``data``, and its fields as the values."""
        return self._validated(arguments, context)

    def _validated(self, arguments: Mapping[str, Any], context: ValidationContext) -> Validated:
        # Neither public method calls the other, so a subclass may extend either.
        if context.partial:
            raise ImproperlyConfigured(
                f"PydanticValidator({self.model.__qualname__}) cannot validate a partial call: "
                "a pydantic model validates every field. Drop partial and give each field an "
                "update may leave out a default, or validate with a FormValidator."
            )
        try:
            instance = self.model.model_validate(
                dict(arguments),
                context={
                    "principal": context.principal,
                    "target": context.target,
                    "call_context": context.call_context,
                },
            )
        except ValidationError as exc:
            raise InvalidArguments(_detail(self.model, self._fields, exc)) from exc
        values = {fs.name: getattr(instance, fs.name) for fs in inputs(self._fields)}
        return Validated(values=values, data=instance)


def _parameters(fields: tuple[FieldShape, ...]) -> Parameters:
    return Parameters(tuple(_parameter(fs) for fs in inputs(fields)))


def _parameter(fs: FieldShape) -> Parameter:
    shape = fs.shape
    return Parameter(
        fs.input_name,
        shape.type,
        required=fs.required,
        # An array's format is its element's, and only a decimal's is one.
        format=shape.format if shape.items is None else element_format(shape.items.format),
        items=_items(shape.items),
        items_nullable=shape.items is not None and shape.items.nullable,
        fields=None if shape.fields is None else _parameters(shape.fields),
        choices=shape.choices if shape.items is None else shape.items.choices,
        choice_labels=choice_labels((shape if shape.items is None else shape.items).enum),
        min_length=fs.min_length,
        max_length=fs.max_length,
        default=fs.default,
        nullable=shape.nullable,
        help=fs.help,
    )


def _items(items: Shape | None) -> str | Parameters | None:
    if items is None:
        return None
    if items.fields is not None:
        return _parameters(items.fields)
    # A scalar's type, or "object" for a dict or a row the bound truncated.
    return items.type


def _detail(
    model: type[BaseModel], fields: tuple[FieldShape, ...], exc: ValidationError
) -> dict[Any, Any]:
    """pydantic's errors as the kernel's tree, each message at the node it is about."""
    top = Shape("object", python=model, fields=fields)
    found: dict[tuple[Any, ...], list[CodedMessage]] = {}
    for error in exc.errors():
        address, about_a_model = _address(top, tuple(error["loc"]))
        if about_a_model:
            address = (*address, NON_FIELD_ERRORS)
        found.setdefault(address, []).append(CodedMessage(error["msg"], _code(error)))
    tree: dict[Any, Any] = {}
    for address, messages in found.items():
        if any(len(other) > len(address) and other[: len(address)] == address for other in found):
            address = (*address, NON_FIELD_ERRORS)
        node = tree
        for key in address[:-1]:
            node = node.setdefault(key, {})
        node.setdefault(address[-1], []).extend(messages)
    return tree


_CODES: Final[dict[str, str]] = {
    "missing": "required",
    "extra_forbidden": "unknown",
    "string_too_short": "min_length",
    "string_too_long": "max_length",
    "too_short": "min_length",
    "too_long": "max_length",
    "greater_than": "min_value",
    "greater_than_equal": "min_value",
    "less_than": "max_value",
    "less_than_equal": "max_value",
    "literal_error": "invalid_choice",
    "enum": "invalid_choice",
    "list_type": "not_a_list",
    "decimal_max_digits": "max_digits",
    "decimal_max_places": "max_decimal_places",
    "decimal_whole_digits": "max_whole_digits",
}
"""pydantic's error types with a DRF code for the same mistake, and that code.

Data, so coverage cannot see a misspelled key, which would fall through to
``"invalid"``: test_each_error_type_carries_its_code has a case for every
entry, and fails with any one key renamed."""

_BUILT_IN: Final[frozenset[str]] = frozenset(get_args(ErrorType))
"""Every error type pydantic itself raises; any other is a ``PydanticCustomError``'s."""


def _code(error: ErrorDetails) -> str:
    """The code of one of pydantic's errors: DRF's for the same mistake, or the author's own."""
    kind = error["type"]
    if error["input"] is None and kind.endswith("_type"):
        return "null"
    if kind in _CODES:
        return _CODES[kind]
    return "invalid" if kind in _BUILT_IN else kind


def _address(top: Shape, loc: tuple[Any, ...]) -> tuple[tuple[Any, ...], bool]:
    """(the tree address of an error's ``loc``, whether it names a model rather than a field)."""
    address: list[Any] = []
    node: Shape | None = top
    for key in loc:
        name, node = (key, None) if node is None else _child(node, key)
        address.append(name)
    return tuple(address), node is not None and node.model is not None


def _child(node: Shape, key: Any) -> tuple[Any, Shape | None]:
    """(the tree key for ``key`` below ``node``, the shape it leads to, if declared)."""
    model = node.model
    if model is not None:
        by_alias = model.model_config.get("loc_by_alias", True)
        for fs in inputs(fields_of(node)):
            if key == (fs.input_name if by_alias else fs.name):
                return fs.input_name, fs.shape
        return key, None
    if node.items is not None and isinstance(key, int):
        return key, node.items
    return key, None
