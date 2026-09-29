"""``PydanticValidator`` - a Validator over a pydantic model."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ValidationError

from django_service_specs.adapters.pydantic.utils import (
    FieldShape,
    Shape,
    check_model,
    fields_of,
    inputs,
    read_fields,
)
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.parameter import Parameter
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.parameters.utils import NON_FIELD_ERRORS
from django_service_specs.validation.validation_context import ValidationContext
from django_service_specs.validation.validator import Validator


class PydanticValidator(Validator):
    """A Validator whose declaration is a pydantic model.

    ``parameters()`` reads the model's fields into Parameters, and
    ``validate()`` hands the arguments to the model: pydantic builds the
    instance, nested models included, and its own validators run as they would
    for any other caller.

    The annotations are read as
    [`DataclassValidator`][django_service_specs.adapters.dataclass.dataclass_validator.DataclassValidator]
    reads them, from one shared table, so a model and a dataclass declaring
    the same field declare the same parameter: ``str``, ``int``, ``float``,
    ``bool``; ``Decimal``, ``datetime`` and ``date`` as strings with their
    format; ``X | None`` as nullable; ``Literal[...]`` and an ``Enum`` as
    choices; ``Annotated`` looked through; and ``list[X]`` of any of these.
    On top of those:

    - a nested model is an object with its own fields as nested Parameters,
      and ``list[SomeModel]`` an array of rows;
    - ``dict[str, X]`` is an object with no declared fields, whose values are
      pydantic's to validate;
    - a model that contains itself is described four times on one path
      (``MAX_APPEARANCES`` in the adapter's ``utils``), and deeper levels as
      an object with no fields. pydantic still validates every level.

    ``Any``, a union of two types, ``UnsetType``, a ``RootModel`` and anything
    else without one JSON type is refused with ``ImproperlyConfigured`` naming
    the model and the field, never read as a string.

    **Names.** A parameter is named for the key pydantic validates by: the
    field's ``validation_alias`` when it is a string, else its ``alias``, else
    its name (the name alone when the model sets ``validate_by_alias=False``).
    An ``AliasPath`` or ``AliasChoices`` is not one name, and is refused.
    ``validate()`` returns the values keyed by the **field name** whatever the
    wire called them, because that is the keyword the service is called with.

    ``required`` is pydantic's own ``is_required()``. The default is reported
    when JSON carries it as itself; a ``default_factory``, or a default such
    as a ``Decimal`` or a date, is not reported, and the field is optional
    all the same. ``help`` is the field's ``description``.

    **A row that updates must declare its key**, as with the dataclass
    adapter: ``pk: int | None = None`` on the row's model, or no incoming row
    matches an existing one and every update replaces every row.

    **Refusals keep pydantic's words**, addressed by path into the kernel's
    tree: ``{"books": {1: {"title": ["..."]}}}``, with a row's index as an
    ``int``. A message about a model itself - its ``model_validator`` refusing
    - sits under ``non_field_errors`` inside that model, or at the top for the
    model being validated. The kernel's shape check runs first and refuses a
    wrong JSON type in the kernel's words, so pydantic's are what a caller
    reads for its own rules: bounds, patterns, validators.

    **Time zones are pydantic's**: an offset-less date-time stays naive, where
    ``DataclassValidator`` makes it aware as Django's forms do. Declare the
    offset, or convert in the service.

    The declaration is read at construction, so an unmappable field fails
    where the spec is written. A model whose annotations named a class not yet
    defined when it was built is completed first, as pydantic completes it on
    first use.
    """

    def __init__(self, model: type[BaseModel]) -> None:
        check_model(model, label="PydanticValidator")
        self.model = model
        self._fields = read_fields(model)
        self._parameters = _parameters(self._fields)

    def parameters(self) -> Parameters:
        """The model's fields as Parameters, named as pydantic validates them. Never queries."""
        return self._parameters

    def validate(self, arguments: Mapping[str, Any], context: ValidationContext) -> dict[str, Any]:
        """Every field's validated value, keyed by field name, or ``InvalidArguments``.

        The context reaches pydantic's validators as ``info.context``, a dict
        with ``"principal"`` and ``"target"``, so a validator can check a
        value against the caller or the row being updated. Nested values stay
        model instances, which is what the mutation helpers read a row from.
        """
        try:
            instance = self.model.model_validate(
                dict(arguments),
                context={"principal": context.principal, "target": context.target},
            )
        except ValidationError as exc:
            raise InvalidArguments(_detail(self.model, self._fields, exc)) from exc
        return {fs.name: getattr(instance, fs.name) for fs in inputs(self._fields)}


def _parameters(fields: tuple[FieldShape, ...]) -> Parameters:
    return Parameters(tuple(_parameter(fs) for fs in inputs(fields)))


def _parameter(fs: FieldShape) -> Parameter:
    shape = fs.shape
    return Parameter(
        fs.input_name,
        shape.type,
        required=fs.required,
        format=shape.format,
        items=_items(shape.items),
        fields=None if shape.fields is None else _parameters(shape.fields),
        choices=shape.choices,
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
    found: dict[tuple[Any, ...], list[str]] = {}
    for error in exc.errors():
        address, about_a_model = _address(top, tuple(error["loc"]))
        if about_a_model:
            address = (*address, NON_FIELD_ERRORS)
        found.setdefault(address, []).append(error["msg"])
    tree: dict[Any, Any] = {}
    for address, messages in found.items():
        if any(len(other) > len(address) and other[: len(address)] == address for other in found):
            # A node with messages inside it cannot also be a list of its own,
            # so a message about the node itself goes beside them, as it does
            # for a row. Only a validator wrapping another produces both.
            address = (*address, NON_FIELD_ERRORS)
        node = tree
        for key in address[:-1]:
            node = node.setdefault(key, {})
        node.setdefault(address[-1], []).extend(messages)
    return tree


def _address(top: Shape, loc: tuple[Any, ...]) -> tuple[tuple[Any, ...], bool]:
    """(the tree address of an error's ``loc``, whether it names a model rather than a field).

    Walks the declaration alongside the location, so a field's key becomes its
    parameter name and a row's index stays an ``int``. ``()`` is the model
    being validated, which is always a model. Below anything the declaration
    does not describe - a dict's values - the location is kept as pydantic
    gave it, and names a field.
    """
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
            # pydantic locates a field by the key it validated, unless the
            # model asks for field names instead; the tree always says the
            # parameter's name, which is the key the caller sent.
            if key == (fs.input_name if by_alias else fs.name):
                return fs.input_name, fs.shape
        return key, None
    if node.items is not None and isinstance(key, int):
        return key, node.items
    return key, None
