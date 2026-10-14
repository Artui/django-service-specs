"""``PydanticValidator`` - a Validator over a pydantic model."""

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
    choices; ``Annotated`` looked through; and ``list[X]`` of any of these,
    where ``list[X | None]`` makes the element nullable and not the array
    and ``list[Decimal]`` declares each element a ``decimal``. On top of
    those:

    - a list's length, however the model states it - ``Field(min_length=,
      max_length=)``, ``conlist``, ``annotated_types``' ``Len``, ``MinLen``
      and ``MaxLen`` - is the parameter's ``min_length`` and ``max_length``,
      so a list the model allows more of than ``SERVICE_SPECS_MAX_ARRAY_LENGTH``
      is not held to it. Where a field states one twice, the last pydantic
      applies is the one declared, as it is the one pydantic enforces. A
      number's bounds are not declared: ``gt`` and ``lt`` are exclusive,
      which a parameter cannot state, and the model keeps every bound in
      its own words rather than some in the kernel's;

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
    wrong JSON type, and a list past its declared length, in the kernel's
    words, under the code pydantic's would carry; pydantic's are what a
    caller reads for the model's other rules: bounds, patterns, validators.

    **Each message carries a code**, the one a DRF field gives the same
    mistake where pydantic's error type has one: ``missing`` is
    ``"required"``, a ``None`` refused by a type is ``"null"``, a string or a
    list too long or too short ``"max_length"`` or ``"min_length"``, a number
    past a bound ``"max_value"`` or ``"min_value"`` (an exclusive bound too,
    which no DRF field has), a ``Literal`` or an ``Enum`` ``"invalid_choice"``,
    a list's type ``"not_a_list"``, a decimal's digits ``"max_digits"``,
    ``"max_decimal_places"`` and ``"max_whole_digits"``, and a forbidden extra
    key the kernel's ``"unknown"``. Any other of pydantic's own types is
    ``"invalid"``, DRF's code for a value it cannot take, and a
    ``ValueError`` or an ``assert`` in a validator is too, as DRF says for a
    message raised with no code. A ``PydanticCustomError``'s type is the
    author's code, and is kept, as a Django ``ValidationError``'s is.

    **Time zones are pydantic's**: an offset-less date-time stays naive, where
    ``DataclassValidator`` makes it aware as Django's forms do. Declare the
    offset, or convert in the service.

    The declaration is read at construction, so an unmappable field fails
    where the spec is written. A model whose annotations named a class not yet
    defined when it was built is completed first, as pydantic completes it on
    first use.
    """

    # A partial spec over it is refused when declared: see ``validate()``.
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
        """Every field's validated value, keyed by field name, or ``InvalidArguments``.

        The context reaches pydantic's validators as ``info.context``, a dict
        with ``"principal"`` and ``"target"``, so a validator can check a
        value against the caller or the row being updated. Nested values stay
        model instances, which is what the mutation helpers read a row from.

        **A partial call is refused** with ``ImproperlyConfigured``. pydantic
        validates a model whole: a required field not sent is missing, and a
        ``model_validator`` is written against every field being there, so
        there is no partial validation to hand the call to. Validating only
        the fields sent, one by one, would skip the model's own rules; a spec
        whose calls are partial uses a Validator that can return only what was
        sent. ``supports_partial`` is ``False``, so a ``ServiceSpec``
        declaring ``partial=True`` over this Validator is refused when it is
        built, and this refusal answers only a caller using it directly.
        ``validated()`` is the default: the values are the call's ``data``.
        """
        if context.partial:
            raise ImproperlyConfigured(
                f"PydanticValidator({self.model.__qualname__}) cannot validate a partial call: "
                "a pydantic model validates every field. Drop partial and give each field an "
                "update may leave out a default, or validate with a FormValidator."
            )
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
            # A node with messages inside it cannot also be a list of its own,
            # so a message about the node itself goes beside them, as it does
            # for a row. Only a validator wrapping another produces both.
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
    """The code of one of pydantic's errors: DRF's for the same mistake, or the author's own.

    A ``None`` a type refuses is ``"null"``, as DRF refuses one, whatever the
    type: pydantic has no error type of its own for it. One branch to
    coverage, so each condition is held by its own test:
    test_each_error_type_carries_its_code[type] (the input: without it, a
    wrong type is ``"null"``) and
    test_each_error_type_carries_its_code[value-error-on-none] (the type:
    without it, a validator refusing a ``None`` its field admits is
    ``"null"`` rather than the validator's ``"invalid"``).
    """
    kind = error["type"]
    if error["input"] is None and kind.endswith("_type"):
        return "null"
    if kind in _CODES:
        return _CODES[kind]
    return "invalid" if kind in _BUILT_IN else kind


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
