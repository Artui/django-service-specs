from __future__ import annotations

from typing import Any

import pytest
from django import forms
from django.db import models

from django_service_specs.adapters.forms.form_validator import FormValidator
from django_service_specs.parameters.constraints_not_held import constraints_not_held
from django_service_specs.parameters.parameters import Parameter
from django_service_specs.parameters.string_lengths import string_lengths


def _string(**lengths: int) -> Parameter:
    return Parameter("title", "string", json_schema_extra=string_lengths(**lengths))


def _choice(choices: tuple[Any, ...] | None) -> Parameter:
    return Parameter("kind", "string", choices=choices)


class _Form(forms.Form):
    title = forms.CharField(max_length=100, min_length=2)
    count = forms.IntegerField(min_value=0)
    kind = forms.ChoiceField(choices=[("a", "A"), ("b", "B")])
    # What a ModelForm builds: a column with choices and no default, and a positive integer.
    col = models.CharField(max_length=1, choices=[("r", "Red")]).formfield()
    stock = models.PositiveIntegerField().formfield()


def _form(name: str) -> Parameter:
    found = FormValidator(_Form).parameters().get(name)
    assert found is not None
    return found


class TestLengths:
    def test_a_spec_with_no_maximum_is_refused(self) -> None:
        assert constraints_not_held(_string(), _string(max_length=100)) == (
            "'title': the form states a maximum length of 100, and the spec declares none.",
        )

    def test_a_spec_maximum_above_the_form_s_is_refused(self) -> None:
        assert constraints_not_held(_string(max_length=101), _string(max_length=100)) == (
            "'title': the form states a maximum length of 100, and the spec declares 101.",
        )

    def test_a_spec_with_no_minimum_is_refused(self) -> None:
        assert constraints_not_held(_string(), _string(min_length=2)) == (
            "'title': the form states a minimum length of 2, and the spec declares none.",
        )

    def test_a_spec_minimum_below_the_form_s_is_refused(self) -> None:
        assert constraints_not_held(_string(min_length=1), _string(min_length=2)) == (
            "'title': the form states a minimum length of 2, and the spec declares 1.",
        )

    @pytest.mark.parametrize(
        ("spec", "form"),
        [
            pytest.param({"max_length": 100}, {"max_length": 100}, id="equal-maximum"),
            pytest.param({"max_length": 50}, {"max_length": 100}, id="tighter-maximum"),
            pytest.param({"min_length": 2}, {"min_length": 2}, id="equal-minimum"),
            pytest.param({"min_length": 5}, {"min_length": 2}, id="tighter-minimum"),
            pytest.param({"max_length": 9}, {}, id="form-states-none"),
        ],
    )
    def test_a_spec_as_tight_as_the_form_or_tighter_holds_it(
        self, spec: dict[str, int], form: dict[str, int]
    ) -> None:
        assert constraints_not_held(_string(**spec), _string(**form)) == ()

    def test_each_length_not_held_is_its_own_message(self) -> None:
        found = constraints_not_held(_string(), _string(min_length=2, max_length=100))
        assert [message.split(" of ")[0] for message in found] == [
            "'title': the form states a maximum length",
            "'title': the form states a minimum length",
        ]


class TestChoices:
    def test_a_spec_with_no_choices_is_refused(self) -> None:
        assert constraints_not_held(_choice(None), _choice(("a", "b"))) == (
            "'kind': the form takes the choices ['a', 'b'], and the spec declares none.",
        )

    def test_a_spec_taking_a_choice_the_form_lacks_is_refused(self) -> None:
        assert constraints_not_held(_choice(("a", "c")), _choice(("a", "b"))) == (
            "'kind': the form takes the choices ['a', 'b'], and the spec declares ['a', 'c'].",
        )

    @pytest.mark.parametrize(
        "spec",
        [
            pytest.param(("a", "b"), id="equal"),
            pytest.param(("a",), id="subset"),
        ],
    )
    def test_a_spec_whose_choices_are_among_the_form_s_holds_it(
        self, spec: tuple[Any, ...]
    ) -> None:
        assert constraints_not_held(_choice(spec), _choice(("a", "b"))) == ()

    def test_a_form_with_no_choices_asks_none(self) -> None:
        assert constraints_not_held(_choice(("a",)), _choice(None)) == ()

    def test_an_unhashable_choice_is_compared_by_equality(self) -> None:
        spec = Parameter("tags", "array", choices=(["a"],))
        form = Parameter("tags", "array", choices=(["a"], ["b"]))
        assert constraints_not_held(spec, form) == ()


class TestBounds:
    def test_a_bound_is_never_compared(self) -> None:
        # Stated by hand, since FormValidator declares none: only this test sees a comparison.
        form = Parameter("count", "integer", minimum=0, maximum=10)
        assert constraints_not_held(Parameter("count", "integer"), form) == ()
        looser = Parameter("count", "integer", minimum=-5, maximum=20)
        assert constraints_not_held(looser, form) == ()

    def test_a_min_value_0_form_field_asks_nothing_of_a_bare_integer(self) -> None:
        assert _form("count").minimum is None
        assert constraints_not_held(Parameter("count", "integer"), _form("count")) == ()


class TestAModelFormSFields:
    def test_a_column_s_choices_with_no_default_are_held_against_the_spec(self) -> None:
        assert constraints_not_held(Parameter("col", "string"), _form("col")) == (
            "'col': the form takes the choices ['r'], and the spec declares none.",
        )

    def test_a_positive_integer_column_asks_nothing_of_the_spec(self) -> None:
        assert constraints_not_held(Parameter("stock", "integer"), _form("stock")) == ()


class TestThroughFormValidator:
    def test_a_form_s_lengths_and_choices_are_what_it_compares(self) -> None:
        assert len(constraints_not_held(Parameter("title", "string"), _form("title"))) == 2
        assert len(constraints_not_held(Parameter("kind", "string"), _form("kind"))) == 1

    def test_a_spec_stating_the_form_s_rules_holds_it(self) -> None:
        spec = Parameter("title", "string", json_schema_extra={"minLength": 2, "maxLength": 100})
        assert constraints_not_held(spec, _form("title")) == ()
        assert constraints_not_held(_choice(("a", "b")), _form("kind")) == ()
