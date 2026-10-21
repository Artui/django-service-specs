"""``clean_held_to_their_columns`` leaves the form as it found it, whether validation returned or raised.

What it refuses is held where its readers are tested: here in
``tests/adapters/forms/test_form_validator.py``, and in django-spec-html's
tests of ``add_argument_errors``. These hold what it puts back.
"""

from __future__ import annotations

from typing import Any

import pytest
from django import forms

from django_service_specs.parameters.clean_held_to_their_columns import (
    clean_held_to_their_columns,
)
from tests.adapter_app.models import Book

# Past every integer column: a key no row can hold, so the guard takes the
# field off the form while it validates.
_BEYOND_THE_COLUMN = 2**63


class _Picked(forms.ModelForm):
    row = forms.ModelChoiceField(queryset=Book.objects.all())

    class Meta:
        model = Book
        fields = ("title",)


class _Breaks(_Picked):
    def clean(self) -> dict[str, Any]:
        raise RuntimeError("a project's clean() failing for its own reasons")


def _bound(form_class: type[_Picked]) -> _Picked:
    return form_class(data={"title": "Lathe", "row": _BEYOND_THE_COLUMN})


@pytest.mark.django_db
def test_a_clean_that_raises_leaves_the_form_every_field_it_had() -> None:
    form = _bound(_Breaks)
    fields = form.fields
    with pytest.raises(RuntimeError, match="its own reasons"):
        clean_held_to_their_columns(form)
    assert form.fields is fields
    assert set(form.fields) == {"title", "row"}


@pytest.mark.django_db
def test_a_clean_that_raises_leaves_the_form_its_own_post_clean() -> None:
    form = _bound(_Breaks)
    with pytest.raises(RuntimeError, match="its own reasons"):
        clean_held_to_their_columns(form)
    assert "_post_clean" not in vars(form)


@pytest.mark.django_db
def test_a_validated_form_keeps_the_class_s_own_post_clean() -> None:
    form = _bound(_Picked)
    clean_held_to_their_columns(form)
    # The guard did run while the form validated: the key is refused.
    assert form.errors["row"][0].startswith("Select a valid choice.")
    assert "_post_clean" not in vars(form)
    assert type(form)._post_clean is forms.BaseModelForm._post_clean


@pytest.mark.django_db
def test_a_post_clean_the_form_carried_itself_is_run_and_put_back() -> None:
    form = _bound(_Picked)
    calls: list[str] = []
    own = form._post_clean

    def recorded() -> None:
        calls.append("own")
        own()

    vars(form)["_post_clean"] = recorded
    clean_held_to_their_columns(form)
    assert calls == ["own"]
    assert vars(form)["_post_clean"] is recorded
