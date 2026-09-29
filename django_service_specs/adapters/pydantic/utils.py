"""Reading a pydantic model's fields, shared by the validator and the presenter.

The two read one declaration from two sides - what an argument must be for the
model to validate it, and what a field becomes when the model dumps it - and
reading it once, here, keeps them from disagreeing about a type. The
annotations are read with the same table and the same unwrapping as the
dataclass adapter's (``adapters/utils.py``), so a model and a dataclass
declaring the same field declare the same parameter.

What differs from the dataclass adapter is who builds the values. That adapter
decodes rows itself, so a dataclass containing itself would decode forever,
and it refuses one. Here pydantic builds every instance from its own schema,
which handles recursion; the declaration is only a description, and a
self-referential model is described to a bound (``MAX_APPEARANCES``) instead
of refused.
"""

from __future__ import annotations

import typing
from dataclasses import dataclass
from enum import Enum
from typing import Any

from django.core.exceptions import ImproperlyConfigured
from pydantic import BaseModel, RootModel
from pydantic.errors import PydanticUndefinedAnnotation
from pydantic.fields import ComputedFieldInfo, FieldInfo
from pydantic_core import PydanticUndefined

from django_service_specs.adapters.utils import SCALARS, scalar_type, strip
from django_service_specs.output.field_marking import FieldMarking
from django_service_specs.types.unset import UNSET

MAX_APPEARANCES = 4
"""How many times one model may appear on a path before the next appearance is truncated.

A self-referential model - a category tree, a threaded comment, an org chart -
is an ordinary shape, and described without a bound it is a ``RecursionError``
raised while a spec is being *declared*, before any call exists to fail. So the
bound has no off switch. The root is the first appearance, so a tree is
described four levels deep and the fifth level is an ``object`` with no
``fields``: still true, since it is an object a caller can send, and
constraining nothing a valid call could fail against. A list of them is an
array of ``"object"``.

Appearances are counted per path, not per model: the same address model under
``billing`` and ``shipping`` is on two paths and is described in full on both.
Four is drfs' ``_MAX_SERIALIZER_APPEARANCES``, so a pydantic declaration and a
DRF one are cut at the same depth.

Truncation costs the **shape check** its depth and nothing else. The kernel
checks what the declaration describes; below the cut, the model's own schema
still validates every level, because pydantic builds the instances, not this
adapter.
"""

_SUPPORTED = (
    "str, int, float, bool, Decimal, datetime, date, a Literal, an Enum, a pydantic "
    "model, dict[str, ...], or a list of any of these, each optionally '| None'"
)


@dataclass(frozen=True)
class Shape:
    """What one annotation means, once ``Annotated`` and ``None`` are off it.

    ``python`` is the class a value validates into: the scalar class, the
    ``Enum``, the model, or ``dict``. It is ``None`` for a ``Literal``, whose
    values are already what the field holds, and for a list, which is
    ``items``.

    ``fields`` is a model's own fields. It is ``None`` for a model the
    appearance bound truncated, as it is for a ``dict``: in both the
    declaration says only that the value is an object.
    """

    type: str
    python: Any = None
    format: str | None = None
    nullable: bool = False
    choices: tuple[Any, ...] | None = None
    items: Shape | None = None
    fields: tuple[FieldShape, ...] | None = None

    @property
    def enum(self) -> type[Enum] | None:
        """The ``Enum`` class a choice validates into, or ``None`` for a ``Literal``."""
        python = self.python
        if isinstance(python, type) and issubclass(python, Enum):
            return python
        return None

    @property
    def model(self) -> type[BaseModel] | None:
        """The model an object validates into, truncated or not; ``None`` for anything else."""
        python = self.python
        return python if _is_model(python) else None


@dataclass(frozen=True)
class FieldShape:
    """One model field, or one computed field, with everything the adapters read off it.

    ``name`` is the attribute: what ``validate()`` returns a value under,
    because it is the keyword the service receives, and what ``present()``
    reads off a value. The two wire names are pydantic's own, one per
    direction:

    - ``input_name``: the key pydantic validates by, and so the parameter's
      name. A computed field is never an input (``computed``), and carries
      its own name here.
    - ``output_name``: the key ``model_dump(by_alias=True)`` emits, and so the
      output field's name. ``None`` for a field declared ``exclude=True``,
      which is never output.
    """

    name: str
    shape: Shape
    computed: bool
    input_name: str
    output_name: str | None
    required: bool
    default: Any
    """The declared default when JSON can state it, else ``UNSET``."""
    help: str | None
    label: str | None
    always_present: bool
    marking: FieldMarking | None


def check_model(model: Any, *, label: str) -> None:
    """Refuse anything that is not a pydantic model class, naming what was passed.

    An instance is refused as well as an unrelated class: it would fail later
    and further away. So is a ``RootModel``, which validates one value rather
    than named arguments, so it has no fields to be parameters.
    """
    if not _is_model(model):
        raise ImproperlyConfigured(
            f"{label} takes a pydantic model class (not a RootModel, which validates one "
            f"value rather than named arguments); got {model!r}."
        )


def read_fields(
    model: type[BaseModel], stack: tuple[type[BaseModel], ...] = ()
) -> tuple[FieldShape, ...]:
    """Every field of ``model`` in declaration order, then every computed field.

    ``stack`` holds the models being read above this one, which is what the
    appearance bound counts. A caller leaves it empty.
    """
    _complete(model)
    below = (*stack, model)
    # Only pydantic's own config can say a model validates by field name
    # rather than by alias; unset, it validates by alias.
    by_alias = model.model_config.get("validate_by_alias", True)
    out: list[FieldShape] = []
    for name, info in model.model_fields.items():
        where = f"{model.__qualname__}.{name}"
        shape, extras = _read(info.annotation, where=where, stack=below)
        out.append(
            FieldShape(
                name=name,
                shape=shape,
                computed=False,
                input_name=_input_name(name, info, by_alias=by_alias, where=where),
                output_name=None if info.exclude else _output_name(name, info),
                required=info.is_required(),
                default=_default(info),
                help=info.description,
                label=info.title,
                always_present=_always_present(info),
                # pydantic lifts the metadata of an outer ``Annotated`` onto the
                # FieldInfo and leaves an inner one in the annotation, so a
                # marking is looked for in both.
                marking=_marking((*info.metadata, *extras), where=where),
            )
        )
    for name, computed in model.model_computed_fields.items():
        where = f"{model.__qualname__}.{name}"
        shape, extras = _read(computed.return_type, where=where, stack=below)
        out.append(
            FieldShape(
                name=name,
                shape=shape,
                computed=True,
                input_name=name,
                output_name=computed.alias or name,
                required=False,
                default=UNSET,
                help=computed.description,
                label=computed.title,
                always_present=_always_present(computed),
                marking=_marking(extras, where=where),
            )
        )
    return tuple(out)


def fields_of(shape: Shape) -> tuple[FieldShape, ...]:
    """A model node's fields: as read, or read afresh where the appearance bound cut them.

    Describing stops at the bound; walking a value or an error's location does
    not, because a value can be deeper than its description. Reading afresh
    starts a new count, so each re-read goes as deep again.
    """
    return shape.fields if shape.fields is not None else read_fields(shape.python)


def inputs(fields: tuple[FieldShape, ...]) -> tuple[FieldShape, ...]:
    """The fields a caller supplies: every model field, and no computed one."""
    return tuple(fs for fs in fields if not fs.computed)


def is_json_native(value: Any) -> bool:
    """Whether ``value`` survives a JSON round trip as itself, containers included.

    drfs' test for a publishable default, so both describe the same defaults.
    """
    if isinstance(value, (str, int, float, bool)) or value is None:
        return True
    if isinstance(value, (list, tuple)):
        return all(is_json_native(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and is_json_native(item) for key, item in value.items())
    return False


def _is_model(value: Any) -> bool:
    # One branch to coverage, so each condition is held by its own test:
    # test_refuses_anything_but_a_model_class holds the first two, and
    # test_a_root_model_is_refused the third. On Python 3.10 ``list[int]``
    # passes as a type; pydantic's metaclass answers ``issubclass`` for it
    # with False rather than raising, so no guard is needed before it.
    return (
        isinstance(value, type)
        and issubclass(value, BaseModel)
        and not issubclass(value, RootModel)
    )


def _complete(model: type[BaseModel]) -> None:
    """Resolve a model whose annotations named a class not defined when it was.

    pydantic defers such a model rather than failing, and completes it on first
    use; reading its fields is a first use, so it is completed here, against
    the model's own module, or refused naming the model.
    """
    if model.__pydantic_complete__:
        return
    try:
        model.model_rebuild()
    except PydanticUndefinedAnnotation as exc:
        raise ImproperlyConfigured(
            f"{model.__qualname__}: an annotation names something not importable from its "
            f"module ({exc})."
        ) from exc


def _input_name(name: str, info: FieldInfo, *, by_alias: bool, where: str) -> str:
    """The one key pydantic validates this field by: the parameter's name."""
    if not by_alias:
        return name
    alias = info.validation_alias
    if alias is None:
        return info.alias or name
    if isinstance(alias, str):
        return alias
    # AliasPath reads a key inside another, and AliasChoices several keys;
    # neither is one name a transport can declare, a caller send, or the
    # closed argument set admit.
    raise ImproperlyConfigured(
        f"{where}: validation_alias {alias!r} is not one name, and a parameter has one. "
        "Use a string alias."
    )


def _output_name(name: str, info: FieldInfo) -> str:
    """The key ``model_dump(by_alias=True)`` emits for this field."""
    return info.serialization_alias or info.alias or name


def _default(info: FieldInfo) -> Any:
    # A default_factory's value is computed per instance, so it is not a
    # declaration a transport could print; and a default JSON cannot carry
    # as itself (a Decimal, a date, a model) is left out rather than
    # misstated. Either way the field stays optional: ``required`` is read
    # separately, from pydantic.
    default = info.default
    if default is PydanticUndefined or not is_json_native(default):
        return UNSET
    return default


def _always_present(info: FieldInfo | ComputedFieldInfo) -> bool:
    # ``model_dump`` emits every key, except one whose ``exclude_if`` holds
    # for the value at hand. Read with getattr because the option is newer
    # than the floor: a field has it from pydantic 2.12 and a computed field
    # from 2.13, and a model on an older release has no such key to drop.
    return getattr(info, "exclude_if", None) is None


def _marking(extras: tuple[Any, ...], *, where: str) -> FieldMarking | None:
    markings = [extra for extra in extras if isinstance(extra, FieldMarking)]
    if len(markings) > 1:
        raise ImproperlyConfigured(
            f"{where}: declares {len(markings)} FieldMarkings; a field has one audience."
        )
    return markings[0] if markings else None


def _read(
    annotation: Any, *, where: str, stack: tuple[type[BaseModel], ...]
) -> tuple[Shape, tuple[Any, ...]]:
    """(shape, ``Annotated`` extras) for one annotation, or ``ImproperlyConfigured``.

    Never a silent ``string``: an annotation this cannot map is refused where
    it is declared, naming the field, because a wrong type in a declaration is
    a schema that lies to every transport reading it.
    """
    base, nullable, omittable, extras = strip(annotation)
    if omittable:
        # ``UnsetType`` is the dataclass adapter's way to leave an argument
        # out. pydantic has its own (a default) and cannot dump the marker, so
        # here it is one more type with no JSON type.
        raise _unmappable(annotation, where=where)
    origin = typing.get_origin(base)
    args = typing.get_args(base)
    if origin is typing.Literal:
        # ``Literal["a", None]`` is Python's own spelling of a nullable choice.
        values = tuple(v for v in args if v is not None)
        shape = Shape(
            _choice_type(values, base, where=where),
            nullable=nullable or len(values) != len(args),
            choices=values,
        )
    elif origin is list and len(args) == 1:
        # The element keeps its own nullability; a marking belongs to a field,
        # not to one element of a list, so the element's extras are dropped.
        items, _ = _read(args[0], where=where, stack=stack)
        shape = Shape("array", nullable=nullable, items=items)
    elif origin is dict and args[:1] == (str,):
        # JSON object keys are strings, so only a str-keyed dict crosses a
        # wire as one. Its values are pydantic's to validate; Parameters has
        # no way to declare "every value is an X", so the declaration is an
        # object and says nothing false about what is inside it.
        shape = Shape("object", python=dict, nullable=nullable)
    elif isinstance(base, type) and issubclass(base, Enum):
        values = tuple(member.value for member in base)
        shape = Shape(
            _choice_type(values, base, where=where),
            python=base,
            nullable=nullable,
            choices=values,
        )
    elif _is_model(base):
        fields = None if stack.count(base) >= MAX_APPEARANCES else read_fields(base, stack)
        shape = Shape("object", python=base, nullable=nullable, fields=fields)
    elif isinstance(base, type) and base in SCALARS:
        json_type, fmt = SCALARS[base]
        shape = Shape(json_type, python=base, format=fmt, nullable=nullable)
    else:
        raise _unmappable(base, where=where)
    return shape, extras


def _choice_type(values: tuple[Any, ...], annotation: Any, *, where: str) -> str:
    """The one JSON type every choice has, or ``ImproperlyConfigured``.

    A choice set of mixed types has no single JSON type to declare, and a
    member whose value is not a JSON scalar cannot be sent at all.
    """
    found = {scalar_type(v) for v in values}
    json_type = found.pop() if len(found) == 1 else None
    if json_type is None:
        raise _unmappable(annotation, where=where)
    return json_type


def _unmappable(annotation: Any, *, where: str) -> ImproperlyConfigured:
    # A class by its name, and anything else - a parametrized generic included,
    # which Python 3.10 also counts as a ``type`` - as it was written.
    plain = isinstance(annotation, type) and typing.get_origin(annotation) is None
    name = annotation.__qualname__ if plain else repr(annotation)
    return ImproperlyConfigured(
        f"{where}: {name} has no JSON type this adapter can declare. Use {_SUPPORTED}."
    )
