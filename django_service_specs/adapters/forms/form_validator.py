"""``FormValidator`` - a Validator over a Django form class."""

from __future__ import annotations

import copy
import dataclasses
from collections.abc import Callable, Iterator, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from django import forms
from django.core.exceptions import NON_FIELD_ERRORS as FORM_NON_FIELD_ERRORS
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import models
from django.utils.datastructures import MultiValueDict

from django_service_specs.adapters.utils import element_format, shared_scalar_type
from django_service_specs.parameters.clean_held_to_their_columns import (
    clean_held_to_their_columns,
)
from django_service_specs.parameters.coded_message import CodedMessage
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.non_field_errors import NON_FIELD_ERRORS
from django_service_specs.parameters.parameters import Parameter, Parameters
from django_service_specs.parameters.utils import coded_messages
from django_service_specs.pool.null_progress import null_progress
from django_service_specs.pool.resolve_callable_kwargs import resolve_callable_kwargs
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

_BOUND_KEYWORDS = frozenset({"data", "files", "instance"})
"""The constructor keywords the bind sets itself, which ``form_kwargs`` may not
return: ``instance`` too for a plain form, so a callable's keywords mean one
thing whichever kind of form it serves."""

_SUPPORTED = (
    "BooleanField, NullBooleanField, IntegerField, FloatField, DecimalField, "
    "DateTimeField, DateField, TimeField, DurationField, CharField and its "
    "subclasses, ChoiceField and MultipleChoiceField with their typed variants, "
    "ModelChoiceField and ModelMultipleChoiceField, and FileField and ImageField"
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
    reporter. Off dispatch - ``bind_arguments``, or a
    [`ValidationContext`][django_service_specs.validation.validation_context.ValidationContext]
    built by hand - the context holds no seeds, so a callable naming one
    gives it a default or meets Python's own ``TypeError``. It is called on
    every ``validate()``, on the thread the call runs on, which under
    ``adispatch`` is the one its synchronous phases share, so it may query;
    on a ``many`` call that is once per row, so a query belongs in a seed,
    which resolves once per call.
    What it returns is passed beside ``data``, ``files`` and ``instance``,
    and returning one of those three, for a plain form as for a
    ``ModelForm``, is refused with ``ImproperlyConfigured`` naming it, as is
    returning anything but a mapping. ``parameters()`` still reads only the
    class: a field ``__init__`` adds from those keywords is not a parameter.
    The callable is kept as ``form_kwargs``, so a transport building the
    form itself, for a page, builds it the same way.

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
    ) -> None:
        # One branch to coverage, so each condition is held by its own case of
        # test_refuses_anything_but_a_form_class: the first by a-form-instance,
        # which ``issubclass`` would raise TypeError on; the second by
        # another-class and a-meta-class.
        if not (isinstance(form_class, type) and issubclass(form_class, forms.BaseForm)):
            raise ImproperlyConfigured(
                f"FormValidator takes a Django form class; got {form_class!r}."
            )
        # One branch to coverage, so each condition is held by its own test:
        # the first by test_with_none_the_form_is_built_from_the_arguments_alone,
        # where ``None`` is no callable; the second by
        # test_it_is_the_callable_it_was_given, which the guard would refuse.
        if form_kwargs is not None and not callable(form_kwargs):
            raise ImproperlyConfigured(
                f"{form_class.__qualname__}: form_kwargs takes a callable returning the "
                f"form's extra constructor keywords; got {form_kwargs!r}."
            )
        _check_model(form_class)
        self.form_class = form_class
        self.form_kwargs = form_kwargs
        # ``base_fields`` is set by the metaclass of Form and ModelForm, or by
        # hand on a form built from BaseForm; the stubs declare it on neither.
        fields: dict[str, forms.Field] = form_class.base_fields  # ty: ignore[unresolved-attribute]
        # Every field a whole call binds, disabled ones included: on a partial
        # ModelForm call, the model fields outside it are the ones a whole
        # call's uniqueness checks leave out.
        self._names: frozenset[str] = frozenset(fields)
        self._declared: tuple[tuple[Parameter, forms.Field], ...] = tuple(
            (_parameter(form_class, name, field), field)
            for name, field in fields.items()
            # The form cleans a disabled field from its initial and never
            # reads the caller's value, so declaring it would offer an
            # argument that does nothing.
            if not field.disabled
        )
        # Each optional file field's clear checkbox, by the field's name: see
        # ``_clear_checkbox``.
        self._clears: dict[str, str] = {
            parameter.name: clear
            for parameter, field in self._declared
            if (clear := _clear_checkbox(form_class, parameter.name, field)) is not None
        }

    def parameters(self) -> Parameters:
        """The form's class-level fields, in declaration order, as Parameters. Never queries."""
        declared: list[Parameter] = []
        for parameter, field in self._declared:
            # ``help_text`` is commonly a lazy translation, so it is made a
            # string here, per call, rather than frozen at import in whichever
            # language was active then.
            declared.append(dataclasses.replace(parameter, help=str(field.help_text) or None))
            clear = self._clears.get(parameter.name)
            if clear is not None:
                # Right after its file, as the widget renders it. Optional and
                # never null: unchecked and absent are one answer to the form.
                declared.append(Parameter(clear, "boolean"))
        return Parameters(tuple(declared))

    def validate(self, arguments: Mapping[str, Any], context: ValidationContext) -> dict[str, Any]:
        """The form's ``cleaned_data``, or ``InvalidArguments`` carrying its errors.

        A ``ModelChoiceField`` cleans to the row and a
        ``ModelMultipleChoiceField`` to a queryset, which is what the service
        receives. On a partial call, only the fields the caller sent are
        bound, and so only those are returned; a ``ModelForm``'s uniqueness
        checks still read the whole row, as the class docstring says.
        """
        fields = {parameter.name: field for parameter, field in self._declared}
        data: dict[str, Any] = {}
        # The type Django binds a request's uploads as, ``request.FILES``.
        files: MultiValueDict[str, Any] = MultiValueDict()
        for name, value in arguments.items():
            field = fields.get(name)
            if isinstance(field, forms.FileField):
                # A file input's widget reads the form's ``files``, never its
                # ``data``: bound as data, the upload would be no upload.
                files[name] = value
            else:
                data[name] = value if field is None else _as_bound(field, value)
        form, row = self._bind(
            data, files, context.target, _extra_keywords(self.form_class, self.form_kwargs, context)
        )
        if context.partial:
            # Off the form rather than made optional: an optional field still
            # cleans to its empty value, runs its ``clean_<field>()`` on it and,
            # on a ModelForm, is written onto the instance and validated there.
            # A checked clear checkbox sends its file field, which the widget
            # then cleans to ``False``; unchecked, it is what absent is.
            sent = arguments.keys() | {
                name for name, clear in self._clears.items() if _checked(arguments, clear)
            }
            for name in form.fields.keys() - sent:
                del form.fields[name]
        # A number no integer column holds is refused in the words of the
        # check that would have handed it to the driver, beside the rest.
        clean_held_to_their_columns(form)
        if not form.is_valid():
            raise InvalidArguments(_detail(form.errors.as_data()))
        # One branch to coverage, so each condition is held by its own test:
        # test_a_whole_model_form_call_checks_uniqueness_once (the partial
        # call: a whole one has already checked every pair, and would query
        # for each again) and
        # test_a_partial_call_with_no_target_row_checks_nothing_it_was_not_sent
        # (the row: a form bound as a create holds the model's defaults for
        # what was not sent, which nothing writes).
        if context.partial and row is not None:
            _check_unique_as_whole(row, self._names)
        return dict(form.cleaned_data)

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
        # A copy, because validation writes the cleaned values onto the
        # instance: see the class docstring.
        instance = copy.copy(target) if isinstance(target, form_class._meta.model) else None
        return form_class(data=data, files=files, instance=instance, **extra), instance


def _extra_keywords(
    form_class: type[forms.BaseForm],
    form_kwargs: Callable[..., Mapping[str, Any]] | None,
    context: ValidationContext,
) -> Mapping[str, Any]:
    """What ``form_kwargs`` returns for this call, or nothing when there is none.

    Its pool is the context's ``ambient`` over ``null_progress`` as
    ``progress``, so the name is in every pool, as ``base_pool`` promises,
    and with ``ambient`` empty off dispatch. ``user`` is laid over
    ``ambient``, so the principal is ``user`` on every path, the two being
    one object on dispatch, and the context's ``resolved`` last: its names
    are reserved, so no seed shares one. Each is held by its own test:
    test_off_dispatch_it_meets_the_principal_as_user_and_no_seed
    (``progress``),
    test_a_hand_built_context_s_user_is_still_the_principal (``user``) and
    test_an_update_hands_it_the_row_itself_and_the_form_a_copy
    (``resolved``).
    """
    if form_kwargs is None:
        return {}
    pool = {
        "progress": null_progress,
        **context.ambient,
        "user": context.principal,
        **context.resolved,
    }
    extra = form_kwargs(**resolve_callable_kwargs(form_kwargs, pool))
    if not isinstance(extra, Mapping):
        raise ImproperlyConfigured(
            f"{form_class.__qualname__}: form_kwargs returned {extra!r}; it returns a "
            "mapping of constructor keywords."
        )
    # Every key in the set is held by its own case of
    # test_refuses_a_key_the_bind_sets_itself, on a form and a ModelForm.
    for key in extra:
        if key in _BOUND_KEYWORDS:
            raise ImproperlyConfigured(
                f"{form_class.__qualname__}: form_kwargs returned {key!r}, which the bind "
                "sets itself from the call; return only the form's own keywords."
            )
    return extra


def _clear_checkbox(form_class: type[forms.BaseForm], name: str, field: forms.Field) -> str | None:
    """The clear checkbox an optional file field's widget offers, or ``None`` for none.

    Django clears an optional file through a ``ClearableFileInput``'s
    checkbox, posted beside the file under the name the widget gives it,
    ``<name>-clear``: checked with no upload, the widget reads the field as
    ``False``, which the field cleans to ``False`` and a ``ModelForm``
    writes as no file. Without the checkbox a JSON caller could never clear
    one, since ``null`` keeps the file a row holds and ``false`` is not a
    file. So it is declared as a parameter of its own, which the closed
    argument set, the shape check and the schema all read.

    Only where the widget would read it: a required field's never does, and
    a widget that is not a ``ClearableFileInput`` has no checkbox. Each
    condition is held by its own test:
    test_a_model_form_s_optional_file_offers_one_and_its_required_one_none
    (the required ``scan``) and
    test_a_custom_widget_with_no_clear_checkbox_offers_none (the widget).
    A form field already named as the checkbox would read the same key, so
    it is refused, disabled or not, since a disabled field is no parameter
    and still shares the data.
    """
    if field.required or not isinstance(field.widget, forms.ClearableFileInput):
        return None
    clear = field.widget.clear_checkbox_name(name)
    # ``base_fields``, as ``__init__`` reads it: the stubs declare it on
    # neither Form nor ModelForm.
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
    """Django's errors as a refusal's detail, the form-wide ones under ``non_field_errors``.

    Each message keeps Django's own code (see ``coded_messages``), which the
    strings ``form.errors`` reads them as would drop.
    """
    return {
        NON_FIELD_ERRORS if key == FORM_NON_FIELD_ERRORS else key: coded_messages(found)
        for key, found in errors.items()
    }


def _check_unique_as_whole(instance: models.Model, names: frozenset[str]) -> None:
    """Refuse a partial update whose row, as it would be saved, breaks a uniqueness rule.

    A partial call takes the fields it was not sent off the form, and Django
    leaves a model field the form does not have out of every uniqueness
    check, so a pair - ``unique_together`` or a ``UniqueConstraint`` - of
    which one field was sent was not checked at all, and the collision
    surfaced as an ``IntegrityError`` when the row was saved. The form has
    already written what was sent onto ``instance``, a copy of the target
    holding its values for the rest, so the checks run here as a whole call
    runs them: leaving out only the model fields the form never declares, and
    refused in the words a whole call would use. A rule on fields that were
    all sent is checked again, and passes again.
    """
    exclude = {field.name for field in instance._meta.fields if field.name not in names}
    errors: dict[str, list[ValidationError]] = {}
    for check in (instance.validate_unique, instance.validate_constraints):
        try:
            check(exclude=exclude)
        except ValidationError as error:
            # Both raise a dict-built error, read by field so each message
            # keeps its code, as ``message_dict`` would not.
            for key, found in error.error_dict.items():
                errors.setdefault(key, []).extend(found)
    if errors:
        raise InvalidArguments(_detail(errors))


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

    An ``int`` for a ``FloatField`` or a ``DecimalField`` is bound as the
    ``Decimal`` it is, too. Each reads a value through a conversion an int
    can break that a ``Decimal`` cannot: ``float`` raises ``OverflowError`` for
    an int past a float's range, where a ``Decimal`` past it reads as an
    infinity, which the field refuses as no number; and ``str`` refuses an
    int past 4300 digits from Python 3.10.7 on, where a ``Decimal``'s has no
    limit. One branch to coverage, so each field is held by its own test:
    test_an_integer_past_a_float_s_range_is_the_field_s_invalid_number (the
    ``FloatField``) and
    test_a_decimal_sent_as_an_integer_is_read_whatever_its_digits (the
    ``DecimalField``); ``type`` rather than ``isinstance`` is held by
    test_true_is_still_no_decimal_to_the_field, since a ``bool`` is an int
    and ``Decimal(True)`` a number.

    One branch to coverage, so each condition is held by its own test:
    test_a_field_that_is_not_a_number_is_bound_as_it_came (the field) and
    test_a_json_number_for_a_decimal_is_bound_as_it_came (the string, since a
    float made a ``Decimal`` carries its binary expansion into the field's
    decimal-places check).
    """
    if isinstance(field, forms.FloatField | forms.DecimalField) and type(value) is int:
        return Decimal(value)
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
    if isinstance(field, forms.FileField):
        # ImageField included. Never choices: a file is matched by nothing a
        # declaration could list.
        return Parameter(name, "file", required=field.required, nullable=not field.required)
    if isinstance(field, forms.NullBooleanField):
        # Its ``validate()`` is empty, so it cleans an absent value or ``null``
        # to ``None`` whatever ``required`` says; declaring either would make
        # the shape check refuse what the form takes.
        return Parameter(name, "boolean", nullable=True)
    json_type, fmt, choices, labels = _shape(field, where=where)
    if isinstance(field, forms.MultipleChoiceField | forms.ModelMultipleChoiceField):
        # ``items`` holds the element's JSON type, and an array's format and
        # choices describe each of its elements: a list of rows keyed on a
        # decimal column is a list of decimals, as one such key is a decimal.
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
    )


_Labels = tuple[tuple[Any, Any], ...] | None


def _shape(
    field: forms.Field, *, where: str
) -> tuple[str, str | None, tuple[Any, ...] | None, _Labels]:
    """The JSON type, format, choices and their labels of one value the field takes."""
    if isinstance(field, forms.ModelChoiceField):
        # No choices: they are rows, and reading them would query.
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
        # Django keeps a choice set given as a callable as a lazy iterator, and
        # evaluates it per form: it may query, and reading it here would
        # freeze a set its author made dynamic.
        return "string", None, None
    # The labels as Django gives them, a lazy translation left lazy: the schema
    # renders each in the language active when it is built.
    pairs = tuple(
        (value, label) for value, label in _flatten(choices) if value not in _EMPTY_CHOICES
    )
    values = tuple(value for value, _ in pairs)
    if not isinstance(field, forms.TypedChoiceField | forms.TypedMultipleChoiceField):
        # A plain choice field cleans with ``str`` and compares against each
        # choice's ``str``, so a caller sends the string whatever the choice was
        # written as, and a label names the string.
        return (
            "string",
            tuple(str(value) for value in values),
            tuple((str(value), label) for value, label in pairs),
        )
    # With no values left the form refuses every non-empty value, and a string
    # is what every choice field takes.
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
        # A multi-table child's primary key is the link to its parent, and a
        # caller sends what that link holds.
        key = key.target_field
    return key
