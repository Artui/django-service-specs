from __future__ import annotations

import copy
import dataclasses
from collections.abc import Callable, Iterator, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from django import forms
from django.core.exceptions import NON_FIELD_ERRORS as FORM_NON_FIELD_ERRORS
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.validators import BaseValidator, MaxLengthValidator, MinLengthValidator
from django.db import models
from django.utils.datastructures import MultiValueDict

from django_service_specs.adapters.forms.utils import extra_keywords
from django_service_specs.adapters.utils import element_format, shared_scalar_type
from django_service_specs.parameters.clean_held_to_their_columns import (
    clean_held_to_their_columns,
)
from django_service_specs.parameters.coded_message import CodedMessage
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.non_field_errors import NON_FIELD_ERRORS
from django_service_specs.parameters.parameters import Parameter, Parameters
from django_service_specs.parameters.utils import coded_messages
from django_service_specs.validation.validation_context import ValidationContext
from django_service_specs.validation.validator import Validator

_REFUSED: tuple[tuple[type[forms.Field], str], ...] = (
    # Ahead of the CharField row below, since JSONField subclasses CharField.
    (forms.JSONField, "takes any JSON value, and a parameter declares one JSON type"),
    (
        forms.MultiValueField,
        "is cleaned from several widget values at once, which only an HTML form "
        "sends; declare a field per value",
    ),
    (
        forms.ComboField,
        "cleans one value through several fields, and has no JSON type of its own",
    ),
)
"""Fields a form can declare and a JSON wire cannot carry, each with the reason
the refusal gives. Read before anything else, so a subclass of a mapped field
is refused rather than mapped."""

_SCALARS: tuple[tuple[type[forms.Field], str, str | None], ...] = (
    # NullBooleanField subclasses BooleanField, and is read before this table.
    (forms.BooleanField, "boolean", None),
    # DecimalField and FloatField both subclass IntegerField, so they come first.
    (forms.DecimalField, "string", "decimal"),
    (forms.FloatField, "number", None),
    (forms.IntegerField, "integer", None),
    (forms.DateTimeField, "string", "date-time"),
    (forms.DateField, "string", "date"),
    # Each parses a string, in a format the kernel has no name for.
    (forms.TimeField, "string", None),
    (forms.DurationField, "string", None),
    # Email, URL, Slug, UUID, Regex, GenericIPAddress: every one a string.
    (forms.CharField, "string", None),
)
"""The fields with one JSON type of their own, most specific first, since the
first ``isinstance`` match wins."""

_KEYS: tuple[tuple[type[models.Field[Any, Any]], str, str | None], ...] = (
    # AutoField, BigAutoField and every integer column subclass IntegerField.
    (models.IntegerField, "integer", None),
    (models.DecimalField, "string", "decimal"),
    # Ahead of DateField, which it subclasses.
    (models.DateTimeField, "string", "date-time"),
    (models.DateField, "string", "date"),
    # SlugField, EmailField and URLField subclass CharField.
    (models.CharField, "string", None),
    (models.TextField, "string", None),
    (models.UUIDField, "string", None),
)
"""The model fields a ``ModelChoiceField`` can match rows on, and the JSON type
a caller sends for one."""

_EMPTY_CHOICES = ("", None)
"""The values Django reads as the blank choice, as a model field's
``get_choices`` does. A form never matches a value against one: it reads an
empty value as no value before it looks at the choices, so neither is a value
a caller can choose."""

_SUPPORTED = (
    "BooleanField, NullBooleanField, IntegerField, FloatField, DecimalField, "
    "DateTimeField, DateField, TimeField, DurationField, CharField and its "
    "subclasses, ChoiceField and MultipleChoiceField with their typed variants, "
    "ModelChoiceField and ModelMultipleChoiceField, and FileField and ImageField"
)


_LENGTH_VALIDATORS: dict[type[BaseValidator], tuple[str, Callable[[int, int], int]]] = {
    MinLengthValidator: ("minLength", max),
    MaxLengthValidator: ("maxLength", min),
}
"""The validators read as a string's length, each with its keyword and how two
of one side combine: the larger minimum and the smaller maximum hold."""


class FormValidator(Validator):
    """A Validator whose declaration is a Django form class."""

    def __init__(
        self,
        form_class: type[forms.BaseForm],
        form_kwargs: Callable[..., Mapping[str, Any]] | None = None,
    ) -> None:
        # Refuses anything but a form class at construction.
        if not (isinstance(form_class, type) and issubclass(form_class, forms.BaseForm)):
            raise ImproperlyConfigured(
                f"FormValidator takes a Django form class; got {form_class!r}."
            )
        if form_kwargs is not None and not callable(form_kwargs):
            raise ImproperlyConfigured(
                f"{form_class.__qualname__}: form_kwargs takes a callable returning the "
                f"form's extra constructor keywords; got {form_kwargs!r}."
            )
        _check_model(form_class)
        self.form_class = form_class
        self.form_kwargs = form_kwargs
        fields: dict[str, forms.Field] = form_class.base_fields  # ty: ignore[unresolved-attribute]
        self._names: frozenset[str] = frozenset(fields)
        self._declared: tuple[tuple[Parameter, forms.Field], ...] = tuple(
            (_parameter(form_class, name, field), field)
            for name, field in fields.items()
            if not field.disabled
        )
        self._clears: dict[str, str] = {
            parameter.name: clear
            for parameter, field in self._declared
            if (clear := _clear_checkbox(form_class, parameter.name, field)) is not None
        }

    def parameters(self) -> Parameters:
        """The form's class-level fields, in declaration order, as Parameters."""
        declared: list[Parameter] = []
        for parameter, field in self._declared:
            declared.append(dataclasses.replace(parameter, help=str(field.help_text) or None))
            clear = self._clears.get(parameter.name)
            if clear is not None:
                declared.append(Parameter(clear, "boolean"))
        return Parameters(tuple(declared))

    def validate(self, arguments: Mapping[str, Any], context: ValidationContext) -> dict[str, Any]:
        """The form's ``cleaned_data``, or ``InvalidArguments`` carrying its errors."""
        fields = {parameter.name: field for parameter, field in self._declared}
        data: dict[str, Any] = {}
        files: MultiValueDict[str, Any] = MultiValueDict()
        for name, value in arguments.items():
            field = fields.get(name)
            if isinstance(field, forms.FileField):
                files[name] = value
            else:
                data[name] = value if field is None else _as_bound(field, value)
        extra = extra_keywords(self.form_class, self.form_kwargs, context)
        data, files = self._prefixed(data, files, extra)
        form, row = self._bind(data, files, context.target, extra)
        if context.partial:
            sent = arguments.keys() | {
                name for name, clear in self._clears.items() if _checked(arguments, clear)
            }
            for name in form.fields.keys() - sent:
                del form.fields[name]
        clean_held_to_their_columns(form)
        if not form.is_valid():
            raise InvalidArguments(_detail(form.errors.as_data()))
        if context.partial and row is not None:
            _check_unique_as_whole(row, self._names)
        return dict(form.cleaned_data)

    def _prefixed(
        self,
        data: dict[str, Any],
        files: MultiValueDict[str, Any],
        extra: Mapping[str, Any],
    ) -> tuple[dict[str, Any], MultiValueDict[str, Any]]:
        """``data`` and ``files`` keyed as the bound form reads them."""
        prefix = extra.get("prefix")
        if prefix is None:
            prefix = self.form_class.prefix
        if not prefix:
            return data, files
        keys = self.form_class.__new__(self.form_class)
        keys.prefix = prefix
        clears = {clear: name for name, clear in self._clears.items()}
        widgets = {parameter.name: field.widget for parameter, field in self._declared}

        def key(name: str) -> str:
            field_name = clears.get(name)
            if field_name is None:
                return keys.add_prefix(name)
            widget = widgets[field_name]
            # Only a ``ClearableFileInput`` is ever recorded in ``_clears``.
            assert isinstance(widget, forms.ClearableFileInput)
            return widget.clear_checkbox_name(keys.add_prefix(field_name))

        return (
            {key(name): value for name, value in data.items()},
            MultiValueDict({key(name): files.getlist(name) for name in files}),
        )

    def _bind(
        self,
        data: dict[str, Any],
        files: MultiValueDict[str, Any],
        target: Any,
        extra: Mapping[str, Any],
    ) -> tuple[forms.BaseForm, models.Model | None]:
        """The bound form, and the copy of the target it edits, or ``None`` for no row."""
        form_class = self.form_class
        if not issubclass(form_class, forms.BaseModelForm):
            return form_class(data=data, files=files, **extra), None
        instance = copy.copy(target) if isinstance(target, form_class._meta.model) else None
        return form_class(data=data, files=files, instance=instance, **extra), instance


def _clear_checkbox(form_class: type[forms.BaseForm], name: str, field: forms.Field) -> str | None:
    """The clear checkbox an optional file field's widget offers, or ``None`` for none."""
    if field.required or not isinstance(field.widget, forms.ClearableFileInput):
        return None
    clear = field.widget.clear_checkbox_name(name)
    if clear in form_class.base_fields:  # ty: ignore[unresolved-attribute]
        raise ImproperlyConfigured(
            f"{form_class.__qualname__}.{name}: its clear checkbox, {clear!r}, is also the "
            "name of a field, and the two would read one argument; rename the field."
        )
    return clear


def _checked(arguments: Mapping[str, Any], clear: str) -> bool:
    """Whether ``arguments`` check the clear checkbox, read as the widget reads it."""
    return bool(forms.CheckboxInput().value_from_datadict(arguments, MultiValueDict(), clear))


def _detail(errors: Mapping[str, list[ValidationError]]) -> dict[str, list[CodedMessage]]:
    """Django's errors as a refusal's detail, the form-wide ones under ``non_field_errors``."""
    return {
        NON_FIELD_ERRORS if key == FORM_NON_FIELD_ERRORS else key: coded_messages(found)
        for key, found in errors.items()
    }


def _check_unique_as_whole(instance: models.Model, names: frozenset[str]) -> None:
    """Refuse a partial update whose row, as it would be saved, breaks a uniqueness rule."""
    exclude = {field.name for field in instance._meta.fields if field.name not in names}
    errors: dict[str, list[ValidationError]] = {}
    for check in (instance.validate_unique, instance.validate_constraints):
        try:
            check(exclude=exclude)
        except ValidationError as error:
            for key, found in error.error_dict.items():
                errors.setdefault(key, []).extend(found)
    if errors:
        raise InvalidArguments(_detail(errors))


def _as_bound(field: forms.Field, value: Any) -> Any:
    """``value`` as the form's data: a number field's string bound as the ``Decimal`` it spells."""
    if isinstance(field, forms.FloatField | forms.DecimalField) and type(value) is int:
        return Decimal(value)
    if not (isinstance(field, forms.IntegerField) and isinstance(value, str)):
        return value
    try:
        return Decimal(value)
    except InvalidOperation:
        return value


def _check_model(form_class: type[forms.BaseForm]) -> None:
    """Refuse a ``ModelForm`` that names no model, as its declaration."""
    if issubclass(form_class, forms.BaseModelForm) and form_class._meta.model is None:
        raise ImproperlyConfigured(
            f"{form_class.__qualname__}: a ModelForm with no Meta.model cannot be "
            "bound; declare the model it edits."
        )


def _parameter(form_class: type[forms.BaseForm], name: str, field: forms.Field) -> Parameter:
    """One field as a Parameter, ``help`` aside, or ``ImproperlyConfigured`` naming it."""
    where = f"{form_class.__qualname__}.{name}"
    for refused, reason in _REFUSED:
        if isinstance(field, refused):
            raise ImproperlyConfigured(f"{where}: a {type(field).__name__} {reason}.")
    if isinstance(field, forms.FileField):
        return Parameter(name, "file", required=field.required, nullable=not field.required)
    if isinstance(field, forms.NullBooleanField):
        return Parameter(name, "boolean", nullable=True)
    json_type, fmt, choices, labels = _shape(field, where=where)
    if isinstance(field, forms.MultipleChoiceField | forms.ModelMultipleChoiceField):
        return Parameter(
            name,
            "array",
            items=json_type,
            format=element_format(fmt),
            choices=choices,
            choice_labels=labels,
            required=field.required,
            nullable=not field.required,
        )
    return Parameter(
        name,
        json_type,
        format=fmt,
        choices=choices,
        choice_labels=labels,
        required=field.required,
        nullable=not field.required,
        json_schema_extra=_lengths(field),
    )


def _lengths(field: forms.Field) -> dict[str, int] | None:
    """A ``CharField``'s lengths as ``minLength`` and ``maxLength``, or ``None``."""
    if not isinstance(field, forms.CharField):
        return None
    lengths: dict[str, int] = {}
    for validator in field.validators:
        side = _LENGTH_VALIDATORS.get(type(validator))
        if side is None:
            continue
        keyword, tightest = side
        if keyword == "minLength" and not field.required:
            continue
        if keyword == "minLength" and isinstance(field, forms.URLField):
            continue
        limit = cast(BaseValidator, validator).limit_value
        if type(limit) is not int or limit < 0:
            continue
        lengths[keyword] = tightest(lengths.get(keyword, limit), limit)
    return lengths or None


_Labels = tuple[tuple[Any, Any], ...] | None


def _shape(
    field: forms.Field, *, where: str
) -> tuple[str, str | None, tuple[Any, ...] | None, _Labels]:
    """The JSON type, format, choices and their labels of one value the field takes."""
    if isinstance(field, forms.ModelChoiceField):
        json_type, fmt = _key_type(field, where=where)
        return json_type, fmt, None, None
    if isinstance(field, forms.ChoiceField):
        json_type, choices, labels = _choices(field, where=where)
        return json_type, None, choices, labels
    for cls, json_type, fmt in _SCALARS:
        if isinstance(field, cls):
            return json_type, fmt, None, None
    raise ImproperlyConfigured(
        f"{where}: a {type(field).__name__} is not a field this adapter can declare. "
        f"It declares {_SUPPORTED}."
    )


def _choices(
    field: forms.ChoiceField, *, where: str
) -> tuple[str, tuple[Any, ...] | None, _Labels]:
    """The JSON type a choice field's value is sent as, the values it may be, and their labels."""
    choices = field.choices
    if not isinstance(choices, list):
        return "string", None, None
    pairs = tuple(
        (value, label) for value, label in _flatten(choices) if value not in _EMPTY_CHOICES
    )
    values = tuple(value for value, _ in pairs)
    if not isinstance(field, forms.TypedChoiceField | forms.TypedMultipleChoiceField):
        return (
            "string",
            tuple(str(value) for value in values),
            tuple((str(value), label) for value, label in pairs),
        )
    json_type = shared_scalar_type(values) if values else "string"
    if json_type is None:
        raise ImproperlyConfigured(
            f"{where}: a {type(field).__name__} whose values {list(values)!r} share no "
            "JSON type cannot be declared; give every choice a value of one JSON type."
        )
    return json_type, values, pairs


def _flatten(choices: list[Any]) -> Iterator[tuple[Any, Any]]:
    """Every choice as its value and label, with each option group's choices in its place."""
    for value, label in choices:
        if isinstance(label, list | tuple):
            yield from label
        else:
            yield value, label


def _key_type(field: forms.ModelChoiceField, *, where: str) -> tuple[str, str | None]:
    """The JSON type and format of what a caller sends to name one row."""
    queryset = field.queryset
    if queryset is None:
        raise ImproperlyConfigured(
            f"{where}: a {type(field).__name__} with no queryset has no model to read "
            "its key from; declare the queryset on the field."
        )
    key = _key_field(queryset, field.to_field_name)
    opts = queryset.model._meta
    for cls, json_type, fmt in _KEYS:
        if isinstance(key, cls):
            return json_type, fmt
    raise ImproperlyConfigured(
        f"{where}: matches rows on {opts.label}.{key.name}, a {type(key).__name__}, "
        "which has no JSON type this adapter can declare."
    )


def _key_field(queryset: models.QuerySet[Any], to_field_name: str | None) -> Any:
    """The model field a choice field matches rows on: its ``to_field_name``, or the key."""
    opts = queryset.model._meta
    key: Any = opts.get_field(to_field_name) if to_field_name else opts.pk
    while isinstance(key, models.ForeignKey):
        key = key.target_field
    return key
