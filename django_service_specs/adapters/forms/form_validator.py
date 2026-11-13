from __future__ import annotations

import copy
import dataclasses
import datetime as dt
import inspect
from collections.abc import Callable, Iterator, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from django import forms
from django.core.exceptions import NON_FIELD_ERRORS as FORM_NON_FIELD_ERRORS
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.validators import BaseValidator, MaxLengthValidator, MinLengthValidator
from django.db import models
from django.forms.formsets import DELETION_FIELD_NAME, INITIAL_FORM_COUNT, TOTAL_FORM_COUNT
from django.http import QueryDict
from django.utils import formats
from django.utils.datastructures import MultiValueDict
from django.utils.duration import duration_string

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
from django_service_specs.validation.validated import Validated
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


_FORMSET_KEYWORDS = ("prefix", "empty_permitted")
"""The form keywords a formset sets for each form, which ``form_kwargs`` may not
return under one: a ``prefix`` would key every row alike, and every row sent is
validated, never skipped as an unchanged extra form."""

_LENGTH_VALIDATORS: dict[type[BaseValidator], tuple[str, Callable[[int, int], int]]] = {
    MinLengthValidator: ("minLength", max),
    MaxLengthValidator: ("maxLength", min),
}
"""The validators read as a string's length, each with its keyword and how two
of one side combine: the larger minimum and the smaller maximum hold."""


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
      JSON number as well, and an integer whatever its digits. ``FloatField``:
      a ``number``, and an integer past a float's range is refused as the
      field refuses an infinity, ``invalid`` in its own words.
      ``IntegerField``: an ``integer``. On a ``ModelForm``, a value the form
      cleans to an integer past the range of the model's integer column is
      refused in the words and with the code of the validator Django's model
      field carries from 5.0, ``max_value`` or ``min_value``, before a
      uniqueness check or a constraint queries with it: Django 4.2 states no
      range for SQLite, whose driver raises ``OverflowError`` for one. It is
      judged where Django 5.0 and later judge it, after the field, its
      ``clean_<field>()`` and the form's ``clean()``, so each of those answers
      first, and a value a ``clean_<field>()`` brings inside the range is
      taken. Only a column Django validates is judged: a value ``clean()``
      sets for a column the form has no field for, and a field declared over
      a column ``Meta.fields`` leaves out or ``Meta.exclude`` names, are the
      form's, as Django never writes them onto the row.
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
      an array of that, so one matching rows on a ``DecimalField`` takes an
      array of ``decimal`` strings, and a query string's
      ``?rows=12.50,9.99`` is two of them. Django matches each against the
      column's own spelling, so ``"12.50"`` names a row a two-place column
      holds and ``12.5`` names none. A date or a
      date-time key is an array of strings, since an element takes no other
      format. They validate to the row, and to a queryset of rows. A key
      past the range of the integer column rows are matched on names no row,
      and is refused as the field refuses a key no row holds,
      ``invalid_choice`` in its own words, before the form queries: Django
      hands a ``ModelMultipleChoiceField``'s keys to the database driver,
      which raises ``OverflowError`` for one, and so does a
      ``ModelChoiceField``'s on Django 4.2.
    - No choice field declares a length, since Django's have none, so the
      shape check in front of this Validator holds a list to the
      ``SERVICE_SPECS_MAX_ARRAY_LENGTH`` setting, 1000 by default.
    - any other ``CharField`` (email, URL, slug, UUID, regex, IP address): a
      ``string``.
    - every ``CharField``, those above included, declares the limit of a
      ``MaxLengthValidator`` on it as ``json_schema_extra``'s ``maxLength``,
      and a required one a ``MinLengthValidator``'s as ``minLength``, so a
      schema advertises them: the validator ``max_length`` and ``min_length``
      append, or one a project appends by hand, the tightest winning; a
      ``ModelForm``'s carries its column's, which Django puts on the field.
      Only those two are read, by exact type, so a ``SimpleArrayField``,
      whose ``max_length`` counts its items with subclasses of them,
      declares no length, and neither does a callable limit. The shape check
      enforces neither, and the form refuses a string past one in its own
      words, beside its other refusals. An optional field's minimum is not
      declared, since the form takes ``""`` whatever it says, and a length
      counts on the value the form cleans: stripped unless ``strip=False``,
      and a ``URLField``'s with the scheme it adds.
    - No ``IntegerField`` or ``FloatField`` declares its ``min_value`` or
      ``max_value``. The shape check enforces a declared ``minimum`` or
      ``maximum`` before the form runs, in its own words, so declaring them
      would replace a field's ``error_messages`` for the bound and keep the
      form's other refusals from coming back beside it.
    - ``FileField`` and ``ImageField``: a ``file``, which no JSON caller can
      send. A multipart request carries one, and a Python caller hands a
      Django ``File``; the form is bound with it as its ``files``, where a
      file field reads, and the form's own checks run on it. A ``ContentFile``
      built with no name is refused by the form, which needs one.
    - an optional file field whose widget is a ``ClearableFileInput``, as a
      ``FileField``'s and an ``ImageField``'s are by default, declares its
      clear checkbox as well: a ``boolean`` named as the widget names it,
      ``<name>-clear``, right after the file. Checked with no upload, the
      form cleans the field to ``False``, its own value for a cleared file,
      which ``validate()`` returns under the field's name and a
      ``ModelForm`` writes as no file through the model field's
      ``save_form_data``; checked beside an upload, the form refuses the
      pair. It is the only way to clear one, since ``null`` keeps the file
      a row holds and ``false`` is not a file. A required file field, or one
      whose widget has no checkbox, declares none, and a field named as a
      checkbox is refused.

    Every choice field's choices carry their labels, as ``choice_labels``,
    for a schema to show beside each value: the label Django displays, keyed
    by the value as the caller sends it, so a plain ``ChoiceField``'s are
    keyed by the string. A lazy label stays lazy until a schema renders it.

    Refused with ``ImproperlyConfigured``, naming the form, the field and its
    class: a ``JSONField``, a
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
      value, and a required one refuses it. A clear checkbox is no field:
      it is optional and never ``null``, since unchecked and absent are
      the one answer the widget reads.
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

    **The form is bound to a post.** Its ``data`` is an immutable
    ``QueryDict`` holding each argument as the strings a browser would post
    for it, so a form or widget written for HTML reads it as it reads
    ``request.POST``: ``getlist`` on a list, ``.isdigit()`` on an id. A list
    is one string per element, a boolean ``"True"`` or ``"False"``, a date,
    time or datetime its ISO spelling, a duration Django's own, and ``null``
    an absent key; any other value is its ``str``. A file stays in ``files``.

    **An argument is in its wire form, which no locale touches.** A
    localized number field reads its post through the active locale, and
    under one whose thousands separator is a dot reads ``"1.500"`` as fifteen
    hundred. So a number, or a string spelling one, for a localized
    ``IntegerField``, ``FloatField`` or ``DecimalField`` is posted as its
    widget renders it in that locale, which the field reads back as the
    number it is.

    **Declare the fields on the class.** A field a form adds or changes in its
    own ``__init__`` is not in ``base_fields``, so it is not described, and
    under ``UnknownArguments.REJECT`` the closed argument set refuses its key
    before the form is built. A field declared ``disabled`` is not a
    parameter either: the form ignores what a caller sends for it and cleans
    its ``initial``, which ``validate()`` returns with the rest on a whole
    call.

    **A partial call binds only the fields the caller sent.** When the
    [`ValidationContext`][django_service_specs.validation.validation_context.ValidationContext]
    says ``partial``, every field the arguments do not name is taken off the
    bound form before it validates, so it is neither required nor cleaned,
    and ``validate()`` returns no key for it: an absent ``BooleanField`` does
    not come back ``False``, nor an absent ``CharField`` ``''``, which an
    update would write over the row. A value that is sent is checked exactly
    as on a whole call, so a required field may be left out but not sent
    empty. A checked clear checkbox sends its file field, and an unchecked
    one is what an absent one is. On a ``ModelForm`` the fields left out keep the target's values,
    and each one's own model check skips them, as Django skips any model
    field a form does not have. **Its uniqueness checks and constraints do
    not**: they run over the row as it would be saved, what was sent on top
    of the target's values, leaving out only the model fields the form never
    declares, as a whole call does. So an update that sends one field of a
    ``unique_together`` pair or a ``UniqueConstraint`` and collides is refused
    as the whole call would be, under ``non_field_errors``, rather than
    failing with an ``IntegrityError`` when the row is saved. That needs a
    target row: a partial call bound as a create checks only what was sent,
    since the rest would be the model's defaults, which nothing writes.
    ``clean()``
    sees only what was sent, so it
    reads ``cleaned_data`` with ``get``, as Django advises for a field that
    failed. ``parameters()`` is the same for both calls: ``required`` says
    what a whole call needs.

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
    selector resolves, or none - binds the form as a create.

    **A plain form that declares ``instance`` is handed the target.** When a
    plain form's ``__init__`` names a parameter ``instance`` (a bare
    ``**kwargs`` does not count), the form is built with ``instance=`` the
    context's target itself, whatever it is and never a copy (a collection
    selector's queryset too), ``None`` when there is none; a plain
    form that declares none is built from ``data`` and ``files`` alone.

    **A form whose ``__init__`` takes more is handed it by ``form_kwargs``.**
    It is a callable returning a mapping of extra constructor keywords, such
    as a queryset scoped by the caller's tenant, and it binds through the
    pool as a selector or a service does, naming what it wants: ``user``,
    ``progress``, every registered seed, and the target under the name the
    service receives it by, from the context's ``resolved``: ``instance``
    for a spec with an instance selector, ``None`` when one that allows none
    finds no row, ``collection`` for one with a collection selector, and
    neither for a create. It is the target itself, never the copy the form
    edits. ``user`` is the context's principal on every path, and
    ``progress`` is ``null_progress`` wherever the context carries no
    reporter. In ``bind_arguments`` handed ``pool_seeds``, it is handed
    every seed of the registry, as on dispatch. In ``bind_arguments`` handed
    none, or with a
    [`ValidationContext`][django_service_specs.validation.validation_context.ValidationContext]
    built by hand, the context holds no seeds, so a callable naming one
    gives it a default or meets Python's own ``TypeError``;
    [`form_keywords`][django_service_specs.adapters.forms.form_keywords.form_keywords]
    is the path off dispatch for building the form itself, and resolves the
    seeds it names. It is called on
    every ``validate()``, on the thread the call runs on, which under
    ``adispatch`` is the one its synchronous phases share, so it may query;
    on a ``many`` call that is once per row, or once for the call under a
    ``formset_class``, so a query belongs in a seed, which resolves once per
    call.
    What it returns is passed beside ``data``, ``files`` and ``instance``,
    and returning one of those three, for a plain form as for a
    ``ModelForm``, is refused with ``ImproperlyConfigured`` naming it, as is
    returning anything but a mapping. ``parameters()`` still reads only the
    class: a field ``__init__`` adds from those keywords is not a parameter.
    The callable is kept as ``form_kwargs``. A transport building the form
    itself, for a page, builds it the same way with
    [`form_keywords`][django_service_specs.adapters.forms.form_keywords.form_keywords],
    which calls it from the pool dispatch would, the seeds it names included.

    **A ``many`` call is one formset under ``formset_class``.** Without one,
    ``validated_many()`` binds each row to a form of its own. Given a
    ``BaseFormSet`` subclass whose ``form`` is ``form_class`` (anything else
    is refused, as are an inline formset, which needs a parent row, and
    ``can_order``, whose field is no parameter), it binds every row into one
    formset, spelled ``<prefix>-<i>-<field>`` as a post spells it, runs each
    form and the formset's ``clean()``, and refuses with each form's errors
    under the caller's index for its row and ``non_form_errors()`` under
    ``non_field_errors``. Every row sent is validated: none is skipped as an
    unchanged extra form, so a row equal to the fields' initials is still
    checked. ``form_kwargs`` is called once and handed to every form, and may
    not return ``prefix`` or ``empty_permitted``, which the formset sets per
    form. The bound formset is in the call's ``pool`` as ``formset``. A
    formset validates whole rows, so the validator's ``supports_partial`` is
    ``False``. Under ``can_delete``, ``parameters()`` declares ``DELETE``, a
    ``boolean``: a row sent with it ``true`` skips its form's errors, as
    Django's formset skips them, and reaches the service with ``DELETE``
    true. A row left out is left alone.

    A ``BaseModelFormSet`` edits the call's collection target, a queryset of
    its model, which a collection selector resolves; a call with none is
    refused with ``ImproperlyConfigured``. ``parameters()`` declares the
    model's key before ``DELETE``: optional, of the JSON type its column
    takes, as a ``ModelChoiceField``'s. A row sending a key is an existing
    row, bound first among the formset's initial forms, its errors still
    answered under its own index, and its form is bound to its row from a
    fresh copy of the collection, so its uniqueness checks exclude it and
    the rows the service receives are not changed. A row with no key is a
    new one. A key outside the collection is refused under the row's key
    field as ``invalid_choice``, deleted or not: Django's own key field takes
    any row of the model, and is held to the collection here. Two rows
    naming one key are refused under ``non_field_errors``, where Django's
    formset would let the last one win. Each row comes back as its form's
    ``cleaned_data``, the key cleaned to its row, or ``None`` for a new one.
    A form field named as one of these additions is refused.

    A refusal is one
    [`InvalidArguments`][django_service_specs.parameters.invalid_arguments.InvalidArguments]
    carrying the form's own errors and messages, ``{field: [messages]}``, with
    the form-wide ones Django keeps under ``"__all__"`` moved to
    ``non_field_errors``, the key every other refusal uses. An argument no
    field declares is ignored by the form, as Django ignores any key it has
    no field for: the closed argument set in front of it is what refuses one.
    """

    def __init__(
        self,
        form_class: type[forms.BaseForm],
        form_kwargs: Callable[..., Mapping[str, Any]] | None = None,
        *,
        formset_class: type[forms.BaseFormSet] | None = None,
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
        self._takes_instance = _declares_instance(form_class)
        self._clears: dict[str, str] = {
            parameter.name: clear
            for parameter, field in self._declared
            if (clear := _clear_checkbox(form_class, parameter.name, field)) is not None
        }
        self.formset_class = formset_class
        self._added = _formset_parameters(form_class, formset_class)
        if formset_class is not None:
            self.supports_partial = False

    def parameters(self) -> Parameters:
        """The form's class-level fields, in declaration order, as Parameters."""
        declared: list[Parameter] = []
        for parameter, field in self._declared:
            declared.append(dataclasses.replace(parameter, help=str(field.help_text) or None))
            clear = self._clears.get(parameter.name)
            if clear is not None:
                declared.append(Parameter(clear, "boolean"))
        return Parameters((*declared, *self._added))

    def validate(self, arguments: Mapping[str, Any], context: ValidationContext) -> dict[str, Any]:
        """The form's ``cleaned_data``, or ``InvalidArguments`` carrying its errors.

        A ``ModelChoiceField`` cleans to the row and a
        ``ModelMultipleChoiceField`` to a queryset, which is what the service
        receives. On a partial call, only the fields the caller sent are
        bound, and so only those are returned; a ``ModelForm``'s uniqueness
        checks still read the whole row, as the class docstring says.
        """
        extra = extra_keywords(self.form_class, self.form_kwargs, context)
        prefix = extra.get("prefix")
        if prefix is None:
            prefix = self.form_class.prefix
        data, files = self._prefixed(*self._row(arguments), prefix)
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

    def validated_many(
        self,
        rows: Mapping[int, Mapping[str, Any]],
        context: ValidationContext,
        *,
        many_argument: str,
    ) -> Validated:
        """The rows bound into one ``formset_class`` formset, or each its own form without one."""
        formset_class = self.formset_class
        if formset_class is None:
            return super().validated_many(rows, context, many_argument=many_argument)
        if context.partial:
            raise ImproperlyConfigured(
                f"{formset_class.__qualname__}: a formset validates whole rows, and this call "
                "is partial; drop partial from the spec, or drop the formset_class."
            )
        extra = extra_keywords(self.form_class, self.form_kwargs, context)
        for keyword in _FORMSET_KEYWORDS:
            if keyword in extra:
                raise ImproperlyConfigured(
                    f"{self.form_class.__qualname__}: form_kwargs returned {keyword!r}, which "
                    f"{formset_class.__qualname__} sets for each form; drop it."
                )
        order = list(rows)
        bound: dict[str, Any] = {}
        key = None
        if issubclass(formset_class, forms.BaseModelFormSet):
            bound["queryset"] = _collection(formset_class, context.target)
            key = _model(formset_class)._meta.pk.name
            order.sort(key=lambda index: rows[index].get(key) is None)
        prefix = formset_class.get_default_prefix()
        initial = sum(key is not None and rows[index].get(key) is not None for index in order)
        data = {
            f"{prefix}-{TOTAL_FORM_COUNT}": [str(len(order))],
            f"{prefix}-{INITIAL_FORM_COUNT}": [str(initial)],
        }
        files: MultiValueDict[str, Any] = MultiValueDict()
        for position, index in enumerate(order):
            posted, uploads = self._prefixed(*self._row(rows[index]), f"{prefix}-{position}")
            data.update(posted)
            for name in uploads:
                files.setlist(name, uploads.getlist(name))
        formset = formset_class(
            data=_query_dict(data),
            files=files,
            form_kwargs={**extra, "empty_permitted": False},
            **bound,
        )
        for form in formset.forms:
            if key is not None:
                _narrow(cast(forms.BaseModelFormSet, formset), form.fields[key])
            clean_held_to_their_columns(form)
        formset.is_valid()
        errors: dict[Any, Any] = {}
        for position, form in enumerate(formset.forms):
            found = form.errors.as_data()
            if formset.can_delete and _deleted(formset, form):
                found = {name: refused for name, refused in found.items() if name == key}
            if found:
                errors[order[position]] = _detail(found)
        refused = [*formset.non_form_errors().as_data(), *_repeated_keys(formset, key)]
        if refused:
            errors[NON_FIELD_ERRORS] = coded_messages(refused)
        if errors:
            raise InvalidArguments(errors)
        cleaned = {order[p]: dict(form.cleaned_data) for p, form in enumerate(formset.forms)}
        values = [cleaned[index] for index in rows]
        return Validated(values={many_argument: values}, data=values, pool={"formset": formset})

    def _row(
        self, arguments: Mapping[str, Any]
    ) -> tuple[dict[str, list[str]], MultiValueDict[str, Any]]:
        """One row's arguments as a post's strings and its files, keyed by field name."""
        fields = {parameter.name: field for parameter, field in self._declared}
        data: dict[str, list[str]] = {}
        files: MultiValueDict[str, Any] = MultiValueDict()
        for name, value in arguments.items():
            field = fields.get(name)
            if isinstance(field, forms.FileField):
                files[name] = value
            elif value is not None:
                data[name] = _posted(field, value)
        return data, files

    def _prefixed(
        self,
        data: dict[str, list[str]],
        files: MultiValueDict[str, Any],
        prefix: str | None,
    ) -> tuple[dict[str, list[str]], MultiValueDict[str, Any]]:
        """``data`` and ``files`` keyed as the bound form reads them."""
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
        posted: dict[str, list[str]],
        files: MultiValueDict[str, Any],
        target: Any,
        extra: Mapping[str, Any],
    ) -> tuple[forms.BaseForm, models.Model | None]:
        """The bound form, and the copy of the target it edits, or ``None`` for no row."""
        data = _query_dict(posted)
        form_class = self.form_class
        if not issubclass(form_class, forms.BaseModelForm):
            edits = {"instance": target} if self._takes_instance else {}
            return form_class(data=data, files=files, **edits, **extra), None
        instance = copy.copy(target) if isinstance(target, form_class._meta.model) else None
        return form_class(data=data, files=files, instance=instance, **extra), instance


def _query_dict(posted: Mapping[str, list[str]]) -> QueryDict:
    """``posted`` as an immutable ``QueryDict``, each key holding its list of strings."""
    data = QueryDict(mutable=True)
    for key, spellings in posted.items():
        data.setlist(key, spellings)
    data._mutable = False
    return data


def _formset_parameters(
    form_class: type[forms.BaseForm], formset_class: type[forms.BaseFormSet] | None
) -> tuple[Parameter, ...]:
    """The fields ``formset_class`` adds to each form, refusing a formset it cannot bind."""
    if formset_class is None:
        return ()
    if not (isinstance(formset_class, type) and issubclass(formset_class, forms.BaseFormSet)):
        raise ImproperlyConfigured(
            f"FormValidator takes a Django formset class as formset_class; got {formset_class!r}."
        )
    name = formset_class.__qualname__
    if formset_class.form is not form_class:
        raise ImproperlyConfigured(
            f"{name}.form is {formset_class.form.__qualname__}, not "
            f"{form_class.__qualname__}: the formset builds its own form, so build the "
            f"validator over it, FormValidator({name}.form, formset_class={name})."
        )
    if issubclass(formset_class, forms.BaseInlineFormSet):
        raise ImproperlyConfigured(
            f"{name} is an inline formset, which edits one parent row's children and needs "
            "that row; declare a model formset over the collection instead."
        )
    if formset_class.can_order:
        raise ImproperlyConfigured(
            f"{name} declares can_order, whose ORDER field is no parameter; drop it."
        )
    added: list[Parameter] = []
    if issubclass(formset_class, forms.BaseModelFormSet):
        model = _model(formset_class)
        key = forms.ModelChoiceField(model._default_manager.get_queryset())
        json_type, fmt = _key_type(key, where=f"{name}.{model._meta.pk.name}")
        added.append(
            Parameter(model._meta.pk.name, json_type, format=fmt, required=False, nullable=True)
        )
    if formset_class.can_delete:
        added.append(Parameter(DELETION_FIELD_NAME, "boolean"))
    for parameter in added:
        if parameter.name in form_class.base_fields:
            raise ImproperlyConfigured(
                f"{form_class.__qualname__}.{parameter.name}: {name} adds a field named "
                f"{parameter.name!r} to every form; rename the form's field."
            )
    return tuple(added)


def _model(formset_class: type[forms.BaseModelFormSet]) -> type[models.Model]:
    """The model a model formset edits, which ``modelformset_factory`` always sets."""
    return cast(type[models.Model], formset_class.model)


def _narrow(formset: forms.BaseModelFormSet, field: forms.Field) -> None:
    """Hold the key field Django adds, which takes any row of the model, to the formset's set."""
    key = cast(forms.ModelChoiceField, field)
    rows = cast(models.QuerySet[Any], key.queryset)
    key.queryset = rows.filter(pk__in=formset.get_queryset().values("pk"))


def _deleted(formset: forms.BaseFormSet, form: forms.BaseForm) -> bool:
    """Whether the formset reads ``form`` as marked for deletion, through its own hook."""
    return bool(formset._should_delete_form(form))  # ty: ignore[unresolved-attribute]


def _repeated_keys(formset: forms.BaseFormSet, key: str | None) -> list[ValidationError]:
    """A refusal of two rows naming one row, which Django's formset lets the last one win."""
    if key is None:
        return []
    named = [form.cleaned_data.get(key) for form in formset.forms]
    rows = [row.pk for row in named if row is not None]
    if len(set(rows)) == len(rows):
        return []
    message = cast(forms.BaseModelFormSet, formset).get_unique_error_message((key,))
    return [ValidationError(message, code="unique")]


def _collection(formset_class: type[forms.BaseModelFormSet], target: Any) -> models.QuerySet[Any]:
    """A fresh copy of the collection target, or ``ImproperlyConfigured`` for no fitting one."""
    model = _model(formset_class)
    if not (isinstance(target, models.QuerySet) and target.model is model):
        raise ImproperlyConfigured(
            f"{formset_class.__qualname__}: a model formset edits a collection of "
            f"{model.__name__} rows, the call's target, which a collection selector on the "
            "spec resolves; this call has none."
        )
    return target.all()


def _declares_instance(form_class: type[forms.BaseForm]) -> bool:
    """Whether the form's ``__init__`` names an ``instance`` parameter, a catch-all aside."""
    parameter = inspect.signature(form_class.__init__).parameters.get("instance")
    return parameter is not None and parameter.kind in _NAMED


_NAMED = (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)


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


def _posted(field: forms.Field | None, value: Any) -> list[str]:
    """``value`` as the strings a browser posts for it, one per element of a list."""
    if isinstance(value, list | tuple):
        return [_spelled(field, element) for element in value]
    return [_spelled(field, value)]


def _spelled(field: forms.Field | None, value: Any) -> str:
    """One value as a browser spells it, a localized number field's in the active locale."""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(Decimal(value))
    if isinstance(field, forms.IntegerField) and field.localize:
        return _localized(value)
    if isinstance(value, dt.date | dt.time):
        return value.isoformat()
    if isinstance(value, dt.timedelta):
        return duration_string(value)
    return str(value)


def _localized(value: Any) -> str:
    """A number as a localized field's widget renders it, which its field reads back."""
    if isinstance(value, float):
        return formats.localize_input(value)
    try:
        number = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return str(value)
    return formats.localize_input(number) if number.is_finite() else str(value)


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
