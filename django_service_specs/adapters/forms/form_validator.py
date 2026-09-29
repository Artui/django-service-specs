"""``FormValidator`` - a Validator over a Django form class."""

from __future__ import annotations

import copy
import dataclasses
from collections.abc import Iterator, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from django import forms
from django.core.exceptions import NON_FIELD_ERRORS as FORM_NON_FIELD_ERRORS
from django.core.exceptions import ImproperlyConfigured
from django.db import models

from django_service_specs.adapters.utils import scalar_type
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.parameter import Parameter
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.parameters.utils import NON_FIELD_ERRORS
from django_service_specs.validation.validation_context import ValidationContext
from django_service_specs.validation.validator import Validator

_REFUSED: tuple[tuple[type[forms.Field], str], ...] = (
    (forms.FileField, "takes an uploaded file, which no JSON transport carries"),
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
    "and ModelChoiceField and ModelMultipleChoiceField"
)


class FormValidator(Validator):
    """A Validator whose declaration is a Django form class.

    ``parameters()`` reads the form's class-level fields, ``base_fields``, in
    declaration order; ``validate()`` binds the arguments to a new form and
    returns what it cleaned. Every rule the form states stays the form's to
    enforce - its fields' validators, ``clean_<field>()``, ``clean()`` and, on
    a ``ModelForm``, the model's own validation and uniqueness checks - and the
    shape check in front of it enforces what the declaration can see.

    The fields it reads, and what each declares, the first match winning:

    - ``BooleanField`` and ``NullBooleanField``: a ``boolean``.
    - ``DecimalField``: a ``string`` in the ``decimal`` format, which takes a
      JSON number as well. ``FloatField``: a ``number``. ``IntegerField``: an
      ``integer``.
    - ``DateTimeField`` and ``DateField``: a ``string`` in the ``date-time`` or
      ``date`` format. ``TimeField`` and ``DurationField``: a ``string``.
    - ``ChoiceField``: choices, with the empty choice dropped and option
      groups flattened. A plain one cleans with ``str`` and matches the
      string against each choice's ``str``, so it takes a ``string`` and its
      choices are declared as strings, whatever type they were written in. A
      ``TypedChoiceField`` takes the JSON type all of its values share. A
      choice set given as a callable is computed per form and may query, so
      it is not read: the field is a ``string`` with no choices, which every
      choice field accepts, and the form checks the choice.
    - ``MultipleChoiceField`` and ``TypedMultipleChoiceField``: an array of
      that, whose choices constrain each element.
    - ``ModelChoiceField``: the JSON type of the model field it matches rows
      on - its ``to_field_name``, or the primary key - and no choices, since
      they are rows and reading them would query. ``ModelMultipleChoiceField``:
      an array of that. They validate to the row, and to a queryset of rows.
    - any other ``CharField`` (email, URL, slug, UUID, regex, IP address): a
      ``string``.

    Refused with ``ImproperlyConfigured``, naming the form, the field and its
    class: a ``FileField`` or ``ImageField``, a ``JSONField``, a
    ``MultiValueField`` such as ``SplitDateTimeField``, a ``ComboField``, any
    field the list does not cover, and a ``ModelChoiceField`` with no queryset
    or matching rows on a model field with no JSON type. The declaration is read at
    construction, so a form that cannot be described fails where the spec is
    written; nothing in it queries or needs a translation, so building a spec
    at import time is safe. ``help`` is the exception, and is read from
    ``help_text`` on each ``parameters()`` call, in the language active then.

    What the Parameters say about presence is what the form does:

    - ``required`` is the field's own ``required``. For a ``BooleanField`` that
      is a statement about presence too: an absent checkbox cleans to
      ``False``, which a required one refuses, as it refuses ``false``.
      A ``NullBooleanField`` is never required, whatever it says, because its
      validation is empty and it takes an absent value as ``None``.
    - ``nullable`` is ``not required``, and always true for a
      ``NullBooleanField``. A form reads ``None`` as an empty value for every
      field, so an optional field takes ``null`` and cleans it to its empty
      value, and a required one refuses it.
    - ``default`` is always
      [`UNSET`][django_service_specs.types.unset.UNSET]: a field's ``initial``
      is what an unbound form displays, and a bound form cleans an absent
      optional field to its empty value, never to its initial.

    **The types are JSON's, and do not cross.** A form reads its data as an
    HTML post's strings, so it also takes a value of another type through
    ``str`` - a number for a ``CharField``, ``1`` for the choice ``"1"`` -
    and the shape check refuses one, as it does for every declaration: a
    caller sends the declared type. The empty choice is the other case: an
    optional choice field reads ``""`` as no value, and a caller sends
    ``null`` for that instead.

    **An argument is in its wire form, which no locale touches.** A number
    field reads a string through the active locale when it is localized, and
    under one whose thousands separator is a dot that reads ``"1.500"`` as
    fifteen hundred. So a string argument for an ``IntegerField``,
    ``FloatField`` or ``DecimalField`` is bound as the ``Decimal`` it spells,
    which the field reads as the number it is, localized or not.

    **Declare the fields on the class.** A field a form adds or changes in its
    own ``__init__`` is not in ``base_fields``, so it is not described, and
    under ``UnknownArguments.REJECT`` the closed argument set refuses its key
    before the form is built. A field declared ``disabled`` is not a
    parameter either: the form ignores what a caller sends for it and cleans
    its ``initial``, which ``validate()`` returns with the rest.

    **A ``ModelForm`` is bound to a copy of the target.** When the
    [`ValidationContext`][django_service_specs.validation.validation_context.ValidationContext]
    carries a row of the form's model, the form is built with
    ``instance=`` a shallow copy of it, so its uniqueness checks exclude the
    row being updated. It is a copy because a ``ModelForm`` writes the cleaned
    values onto its instance while it validates: handed the target itself, it
    would change the row the service receives before the service runs, and a
    helper that saves only what changed, such as
    [`update_from_input`][django_service_specs.mutations.update_from_input.update_from_input],
    would find nothing to save. Any other target - the queryset a collection
    selector resolves, or none - binds the form as a create. The form is built
    from ``data=`` and ``instance=`` alone, so one whose ``__init__`` requires
    more, such as the signed-in user, cannot be used as it is.

    A refusal is one
    [`InvalidArguments`][django_service_specs.parameters.invalid_arguments.InvalidArguments]
    carrying the form's own errors and messages, ``{field: [messages]}``, with
    the form-wide ones Django keeps under ``"__all__"`` moved to
    ``non_field_errors``, the key every other refusal uses. An argument no
    field declares is ignored by the form, as Django ignores any key it has
    no field for: the closed argument set in front of it is what refuses one.
    """

    def __init__(self, form_class: type[forms.BaseForm]) -> None:
        # One branch to coverage, so each condition is held by its own case of
        # test_refuses_anything_but_a_form_class: the first by a-form-instance,
        # which ``issubclass`` would raise TypeError on; the second by
        # another-class and a-meta-class.
        if not (isinstance(form_class, type) and issubclass(form_class, forms.BaseForm)):
            raise ImproperlyConfigured(
                f"FormValidator takes a Django form class; got {form_class!r}."
            )
        _check_model(form_class)
        self.form_class = form_class
        # ``base_fields`` is set by the metaclass of Form and ModelForm, or by
        # hand on a form built from BaseForm; the stubs declare it on neither.
        fields: dict[str, forms.Field] = form_class.base_fields  # ty: ignore[unresolved-attribute]
        self._declared: tuple[tuple[Parameter, forms.Field], ...] = tuple(
            (_parameter(form_class, name, field), field)
            for name, field in fields.items()
            # The form cleans a disabled field from its initial and never
            # reads the caller's value, so declaring it would offer an
            # argument that does nothing.
            if not field.disabled
        )

    def parameters(self) -> Parameters:
        """The form's class-level fields, in declaration order, as Parameters. Never queries."""
        return Parameters(
            tuple(
                # ``help_text`` is commonly a lazy translation, so it is made a
                # string here, per call, rather than frozen at import in
                # whichever language was active then.
                dataclasses.replace(parameter, help=str(field.help_text) or None)
                for parameter, field in self._declared
            )
        )

    def validate(self, arguments: Mapping[str, Any], context: ValidationContext) -> dict[str, Any]:
        """The form's ``cleaned_data``, or ``InvalidArguments`` carrying its errors.

        A ``ModelChoiceField`` cleans to the row and a
        ``ModelMultipleChoiceField`` to a queryset, which is what the service
        receives.
        """
        fields = {parameter.name: field for parameter, field in self._declared}
        data = {
            name: _as_bound(fields[name], value) if name in fields else value
            for name, value in arguments.items()
        }
        form = self._bind(data, context.target)
        if not form.is_valid():
            raise InvalidArguments(
                {
                    NON_FIELD_ERRORS if key == FORM_NON_FIELD_ERRORS else key: list(messages)
                    for key, messages in form.errors.items()
                }
            )
        return dict(form.cleaned_data)

    def _bind(self, data: dict[str, Any], target: Any) -> forms.BaseForm:
        form_class = self.form_class
        if not issubclass(form_class, forms.BaseModelForm):
            return form_class(data=data)
        # A copy, because validation writes the cleaned values onto the
        # instance: see the class docstring.
        instance = copy.copy(target) if isinstance(target, form_class._meta.model) else None
        return form_class(data=data, instance=instance)


def _as_bound(field: forms.Field, value: Any) -> Any:
    """``value`` as the form's data: a number field's string bound as the ``Decimal`` it spells.

    An argument arrives in its wire form, which no locale touches, and a
    decimal's wire form is a string. A localized number field reads a string
    through Django's ``sanitize_separators``, which takes a dot followed by
    exactly three digits for a thousands separator where the active locale's
    is one: bound as ``"1.500"``, one and a half, it cleans to 1500. It passes
    anything but a string through, so a ``Decimal`` is read as the number it
    is, localized or not, and it spells every value the shape check accepts
    exactly.

    One branch to coverage, so each condition is held by its own test:
    test_a_field_that_is_not_a_number_is_bound_as_it_came (the field) and
    test_a_json_number_for_a_decimal_is_bound_as_it_came (the string, since a
    float made a ``Decimal`` carries its binary expansion into the field's
    decimal-places check).
    """
    if not (isinstance(field, forms.IntegerField) and isinstance(value, str)):
        return value
    try:
        return Decimal(value)
    except InvalidOperation:
        # Not a number at all, from a caller the shape check did not front:
        # the field refuses it, in its own words.
        return value


def _check_model(form_class: type[forms.BaseForm]) -> None:
    """Refuse a ``ModelForm`` that names no model, as its declaration.

    Django refuses one only when it is built, which for a Validator is the
    first call rather than the spec's declaration.
    """
    # One branch to coverage, so each condition is held by its own test: the
    # first by every test of a plain form, which has no ``_meta``, such as
    # test_every_mapped_field_declares_its_json_type_in_declaration_order; the
    # second by test_an_update_excludes_the_target_from_the_uniqueness_check.
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
    if isinstance(field, forms.NullBooleanField):
        # Its ``validate()`` is empty, so it cleans an absent value or ``null``
        # to ``None`` whatever ``required`` says; declaring either would make
        # the shape check refuse what the form takes.
        return Parameter(name, "boolean", nullable=True)
    json_type, fmt, choices = _shape(field, where=where)
    if isinstance(field, forms.MultipleChoiceField | forms.ModelMultipleChoiceField):
        # ``items`` holds a JSON type and no format, as for any flat list, and
        # an array's choices constrain each of its elements.
        return Parameter(
            name,
            "array",
            items=json_type,
            choices=choices,
            required=field.required,
            nullable=not field.required,
        )
    return Parameter(
        name,
        json_type,
        format=fmt,
        choices=choices,
        required=field.required,
        nullable=not field.required,
    )


def _shape(field: forms.Field, *, where: str) -> tuple[str, str | None, tuple[Any, ...] | None]:
    """The JSON type, format and choices of one value the field takes."""
    if isinstance(field, forms.ModelChoiceField):
        # No choices: they are rows, and reading them would query.
        json_type, fmt = _key_type(field, where=where)
        return json_type, fmt, None
    if isinstance(field, forms.ChoiceField):
        json_type, choices = _choices(field, where=where)
        return json_type, None, choices
    for cls, json_type, fmt in _SCALARS:
        if isinstance(field, cls):
            return json_type, fmt, None
    raise ImproperlyConfigured(
        f"{where}: a {type(field).__name__} is not a field this adapter can declare. "
        f"It declares {_SUPPORTED}."
    )


def _choices(field: forms.ChoiceField, *, where: str) -> tuple[str, tuple[Any, ...] | None]:
    """The JSON type a choice field's value is sent as, and the values it may be."""
    choices = field.choices
    if not isinstance(choices, list):
        # Django keeps a choice set given as a callable as a lazy iterator, and
        # evaluates it per form: it may query, and reading it here would
        # freeze a set its author made dynamic.
        return "string", None
    values = tuple(value for value in _flatten(choices) if value not in _EMPTY_CHOICES)
    if not isinstance(field, forms.TypedChoiceField | forms.TypedMultipleChoiceField):
        # A plain choice field cleans with ``str`` and compares against each
        # choice's ``str``, so a caller sends the string whatever the choice was
        # written as.
        return "string", tuple(str(value) for value in values)
    # With no values left the form refuses every non-empty value, and a string
    # is what every choice field takes.
    found = {scalar_type(value) for value in values} or {"string"}
    json_type = found.pop() if len(found) == 1 else None
    if json_type is None:
        raise ImproperlyConfigured(
            f"{where}: a {type(field).__name__} whose values {list(values)!r} share no "
            "JSON type cannot be declared; give every choice a value of one JSON type."
        )
    return json_type, values


def _flatten(choices: list[Any]) -> Iterator[Any]:
    """Every choice's value, with each option group's values in its place."""
    for value, label in choices:
        if isinstance(label, list | tuple):
            yield from (inner for inner, _ in label)
        else:
            yield value


def _key_type(field: forms.ModelChoiceField, *, where: str) -> tuple[str, str | None]:
    """The JSON type and format of what a caller sends to name one row."""
    queryset = field.queryset
    if queryset is None:
        raise ImproperlyConfigured(
            f"{where}: a {type(field).__name__} with no queryset has no model to read "
            "its key from; declare the queryset on the field."
        )
    opts = queryset.model._meta
    key: Any = opts.get_field(field.to_field_name) if field.to_field_name else opts.pk
    while isinstance(key, models.ForeignKey):
        # A multi-table child's primary key is the link to its parent, and a
        # caller sends what that link holds.
        key = key.target_field
    for cls, json_type, fmt in _KEYS:
        if isinstance(key, cls):
            return json_type, fmt
    raise ImproperlyConfigured(
        f"{where}: matches rows on {opts.label}.{key.name}, a {type(key).__name__}, "
        "which has no JSON type this adapter can declare."
    )
