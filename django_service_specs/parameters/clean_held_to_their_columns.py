from __future__ import annotations

from typing import Any

from django import forms
from django.core.exceptions import ValidationError
from django.db import router

from django_service_specs.parameters.utils import (
    choices_past_their_columns,
    integer_column_range,
    integer_range_refusal,
)


def clean_held_to_their_columns(form: forms.BaseForm) -> None:
    """Validate a bound ``form`` as its ``full_clean()`` does, refusing a number no integer column
    holds.

    Django's own validation hands such a number to the database driver in two
    places, and SQLite's raises ``OverflowError`` for one past 64 bits: a
    model choice field matching its key, and a ``ModelForm``'s uniqueness
    checks and constraints querying with a value. Each is answered first, in
    the words of the check Django would have made:

    - a model choice field sent a key its column cannot hold is taken off the
      form while it validates and given the field's own ``invalid_choice``
      refusal after, so the form's ``clean()`` and its other errors are found
      as Django finds them with the field refused;
    - a ``ModelForm``'s value its integer column cannot hold is refused as the
      model's validation step starts, before its uniqueness checks and
      constraints query with it, with the ``min_value`` or ``max_value``
      refusal of Django's model integer field.

    Shared by ``FormValidator``, which validates its form so, and by
    django-spec-html's ``add_argument_errors``, which finds a form's own
    errors so before it places a refusal beside them.

    The form is left as it was found, whether its validation returned or
    raised: every field it had, in its order, and its own ``_post_clean``,
    the class's or one the form carried itself. Only its errors and what it
    cleaned are new.

    Public so that a transport in a distribution of its own, validating a
    project's form, holds it to the same columns with the same words.
    """
    beyond = choices_past_their_columns(form)
    fields = form.fields
    own = {name: value for name, value in vars(form).items() if name == "_post_clean"}
    form.fields = {name: field for name, field in fields.items() if name not in beyond}
    _hold_to_the_columns(form)
    try:
        form.full_clean()
    finally:
        form.fields = fields
        vars(form).pop("_post_clean", None)
        vars(form).update(own)
    for name, refusals in beyond.items():
        form.add_error(name, refusals)


def _hold_to_the_columns(form: forms.BaseForm) -> None:
    """Have a bound ``ModelForm`` refuse a value its integer column cannot hold."""
    if not isinstance(form, forms.BaseModelForm):
        return
    bound: Any = form
    post_clean = bound._post_clean

    def checked() -> None:
        for name, refusal in _values_beyond_the_column(form).items():
            form.add_error(name, refusal)
        post_clean()

    bound._post_clean = checked


def _values_beyond_the_column(form: forms.BaseModelForm) -> dict[str, ValidationError]:
    """Each value ``form`` cleaned for a column that cannot hold it, and its refusal."""
    beyond: dict[str, ValidationError] = {}
    model = form._meta.model
    columns: dict[str, Any] = {column.name: column for column in model._meta.concrete_fields}
    using = router.db_for_write(model, instance=form.instance)
    bound: Any = form
    excluded = bound._get_validation_exclusions()
    for name, cleaned in form.cleaned_data.items():
        if name in excluded:
            continue
        column: Any = columns.get(name)
        bounds = integer_column_range(column, using)
        if bounds is None:
            continue
        try:
            value = column.to_python(cleaned)
        except ValidationError:
            continue
        if value is None:
            continue
        refusal = integer_range_refusal(value, bounds)
        if refusal is not None:
            beyond[name] = refusal
    return beyond
