from __future__ import annotations

from django import forms
from django.test import override_settings

from django_service_specs.schema.registered_fragment import registered_fragment
from django_service_specs.types.json_schema_registry import JsonSchemaRegistry
from tests.schema.utils import PROJECT_RULES, LooseIntegerField

PROJECT = "tests.schema.utils.PROJECT_RULES"


def test_no_rule_anywhere_answers_none() -> None:
    assert registered_fragment(LooseIntegerField) is None


def test_the_project_s_rule_answers_a_seat_with_no_registry() -> None:
    with override_settings(SERVICE_SPECS_FIELD_SCHEMA_REGISTRY=PROJECT):
        assert registered_fragment(LooseIntegerField) == {"type": "string"}


def test_an_empty_seat_registry_still_reads_the_project_s() -> None:
    with override_settings(SERVICE_SPECS_FIELD_SCHEMA_REGISTRY=PROJECT):
        assert registered_fragment(LooseIntegerField, JsonSchemaRegistry()) == {"type": "string"}


def test_the_seat_s_rule_wins_over_the_project_s_for_one_class() -> None:
    seat = JsonSchemaRegistry(fields=((LooseIntegerField, {"type": "number"}),))
    with override_settings(SERVICE_SPECS_FIELD_SCHEMA_REGISTRY=PROJECT):
        assert registered_fragment(LooseIntegerField, seat) == {"type": "number"}


def test_the_seat_s_rule_for_a_base_wins_over_the_project_s_for_the_class() -> None:
    # The seat's rules are read through the whole MRO before the project's are read.
    seat = JsonSchemaRegistry(fields=((forms.IntegerField, {"type": "number"}),))
    with override_settings(SERVICE_SPECS_FIELD_SCHEMA_REGISTRY=PROJECT):
        assert registered_fragment(LooseIntegerField, seat) == {"type": "number"}


def test_the_project_answers_a_class_the_seat_names_no_rule_for() -> None:
    seat = JsonSchemaRegistry(fields=((forms.DateField, {"type": "string"}),))
    with override_settings(SERVICE_SPECS_FIELD_SCHEMA_REGISTRY=PROJECT):
        assert registered_fragment(LooseIntegerField, seat) == {"type": "string"}


def test_a_seat_that_opts_out_reads_no_project_rule() -> None:
    with override_settings(SERVICE_SPECS_FIELD_SCHEMA_REGISTRY=PROJECT):
        assert registered_fragment(LooseIntegerField, project_registry=False) is None


def test_a_seat_that_opts_out_does_not_read_the_setting() -> None:
    # A setting that would be refused is never read.
    with override_settings(SERVICE_SPECS_FIELD_SCHEMA_REGISTRY=7):
        assert registered_fragment(LooseIntegerField, project_registry=False) is None


def test_the_fragment_is_a_copy_the_caller_may_change() -> None:
    with override_settings(SERVICE_SPECS_FIELD_SCHEMA_REGISTRY=PROJECT):
        fragment = registered_fragment(LooseIntegerField)
    assert fragment is not None
    fragment["type"] = "boolean"
    assert PROJECT_RULES.fields[0] == (LooseIntegerField, {"type": "string"})
