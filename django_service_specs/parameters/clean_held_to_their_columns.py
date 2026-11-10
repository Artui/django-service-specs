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
    """Validate a bound ``form`` as ``full_clean()`` does, refusing out-of-range integers."""
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
