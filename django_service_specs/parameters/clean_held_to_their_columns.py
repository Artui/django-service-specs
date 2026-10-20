"""``clean_held_to_their_columns`` - a form validated with no number past its column reaching the driver."""

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
    """Validate a bound ``form`` as its ``full_clean()`` does, refusing a number no integer column holds.

    Django's own validation hands such a number to the database driver in two
    places, and SQLite's raises ``OverflowError`` for one past 64 bits: a
    model choice field matching its key, and a ``ModelForm``'s uniqueness
    checks and constraints querying with a value. Each is answered first, in
    the words of the check Django would have made:

    - a model choice field sent a key its column cannot hold, which
      ``choices_past_their_columns`` reads, is taken off the form while it
      validates and given that refusal after, so the form's ``clean()`` and
      its other errors are found as Django finds them with the field refused;
    - a ``ModelForm``'s value its integer column cannot hold is judged by
      ``_hold_to_the_columns`` as the model's step starts.

    Shared by ``FormValidator``, which validates its form so, and by
    ``add_argument_errors``, which finds a form's own errors so before it
    places a refusal beside them. The form keeps every field, in its order.

    Public so that a transport in a distribution of its own, validating a
    project's form, holds it to the same columns with the same words.
    """
    beyond = choices_past_their_columns(form)
    fields = form.fields
    form.fields = {name: field for name, field in fields.items() if name not in beyond}
    _hold_to_the_columns(form)
    form.full_clean()
    form.fields = fields
    for name, refusals in beyond.items():
        form.add_error(name, refusals)


def _hold_to_the_columns(form: forms.BaseForm) -> None:
    """Have a bound ``ModelForm`` refuse a value its integer column cannot hold, before the model sees it.

    A ``ModelForm`` writes what it cleaned onto its instance and validates the
    instance in its ``_post_clean``, the step after the form's own ``clean()``
    that every validation runs. Its uniqueness checks and constraints query
    with each value, and Django 4.2 states no range for SQLite, whose driver
    raised ``OverflowError`` for a value past the column's. So the values are
    judged as that step starts, by ``_values_beyond_the_column``, and each
    refusal is added to the form as a field's own error, which takes the value
    out of ``cleaned_data``: the instance keeps what it held, and Django leaves
    a field with an error out of every check on the instance. Wrapped on the
    bound form. A plain form has no model to read a column from
    (test_an_integer_past_a_float_s_range_is_the_field_s_invalid_number).
    """
    if not isinstance(form, forms.BaseModelForm):
        return
    # ``Any``, as Django's own step is to the stubs, which declare it on
    # neither form class.
    bound: Any = form
    post_clean = bound._post_clean

    def checked() -> None:
        for name, refusal in _values_beyond_the_column(form).items():
            form.add_error(name, refusal)
        post_clean()

    bound._post_clean = checked


def _values_beyond_the_column(form: forms.BaseModelForm) -> dict[str, ValidationError]:
    """Each value ``form`` cleaned for a column it validates that the column cannot hold, and its refusal.

    In the words, and with the code, of the validator Django's model integer
    field carries from 5.0, where the backend states the column's range:
    ``max_value`` past its top, ``min_value`` past its bottom. The range is
    the one ``integer_column_range`` reads, from the database the row is
    written to. The value is the one the form cleaned, after the field, its
    ``clean_<field>()`` and the form's ``clean()``, read as the model reads
    it, so digits a text field cleans to are the integer they spell
    (test_digits_a_text_field_cleans_to_are_held_to_the_column).

    Only a column Django validates is judged: one it would leave out of the
    model's checks, by ``_get_validation_exclusions``, is never written onto
    the instance by the form or never compared, and is the form's. That is a
    column the form has no field for, whatever its ``clean()`` sets in
    ``cleaned_data`` under that name
    (test_a_value_clean_sets_for_a_column_the_form_does_not_edit_is_never_judged),
    one ``Meta.fields`` leaves out or ``Meta.exclude`` names, though the form
    declares a field for it
    (test_a_field_declared_over_a_column_meta_leaves_out_is_never_judged), a
    field already refused, and an optional field left empty over a column
    that takes no blank. So every name judged is one of the form's fields,
    which is what a refusal is added to. A model choice field is
    ``choices_past_their_columns``'s, since its column is a foreign key, which
    holds the key of another row.
    """
    beyond: dict[str, ValidationError] = {}
    model = form._meta.model
    columns: dict[str, Any] = {column.name: column for column in model._meta.concrete_fields}
    using = router.db_for_write(model, instance=form.instance)
    # Django's own reading, private on every supported version, of which of
    # the model's columns it validates; ``Any`` as the stubs declare none.
    bound: Any = form
    excluded = bound._get_validation_exclusions()
    for name, cleaned in form.cleaned_data.items():
        if name in excluded:
            continue
        column: Any = columns.get(name)
        bounds = integer_column_range(column, using)
        # test_an_integer_field_no_column_holds_is_the_field_s fails without
        # this: a field that is no model column has no range to unpack.
        if bounds is None:
            continue
        try:
            value = column.to_python(cleaned)
        except ValidationError:
            # Text the column reads as no number: the model refuses it, in its
            # words (test_text_the_column_reads_as_no_number_is_the_model_s).
            continue
        # test_a_clean_method_handing_back_nothing_is_the_model_s fails
        # without this: ``None`` is no number to range, and the model refuses
        # it. An optional field left empty is excluded above where the column
        # takes no blank.
        if value is None:
            continue
        refusal = integer_range_refusal(value, bounds)
        if refusal is not None:
            beyond[name] = refusal
    return beyond
