from __future__ import annotations

import re
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from django_service_specs.settings import field_schema_registry, max_array_length
from tests.schema.utils import PROJECT_RULES


def test_the_default_maximum_is_a_thousand_elements() -> None:
    # Django's own DATA_UPLOAD_MAX_NUMBER_FIELDS, the line a form body stops at.
    assert max_array_length() == 1000


@pytest.mark.parametrize("value", [0, 1, 50_000, None])
def test_the_setting_is_read_as_given(value: int | None) -> None:
    with override_settings(SERVICE_SPECS_MAX_ARRAY_LENGTH=value):
        assert max_array_length() == value


@pytest.mark.parametrize(
    "value", [True, -1, 1.5, "1000"], ids=["bool", "negative", "float", "string"]
)
def test_a_setting_that_is_no_count_is_refused_by_name(value: Any) -> None:
    # Refused where it is read rather than compared.
    with (
        override_settings(SERVICE_SPECS_MAX_ARRAY_LENGTH=value),
        pytest.raises(
            ImproperlyConfigured,
            match=f"SERVICE_SPECS_MAX_ARRAY_LENGTH must be a non-negative int or None; "
            f"got {value!r}",
        ),
    ):
        max_array_length()


def test_no_field_schema_registry_is_named_by_default() -> None:
    assert field_schema_registry() is None


def test_the_field_schema_registry_is_the_object_the_path_names() -> None:
    with override_settings(SERVICE_SPECS_FIELD_SCHEMA_REGISTRY="tests.schema.utils.PROJECT_RULES"):
        assert field_schema_registry() is PROJECT_RULES


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (PROJECT_RULES, "must be the dotted path to a JsonSchemaRegistry; got JsonSchemaRegistry"),
        ("tests.schema.utils.MISSING", "names 'tests.schema.utils.MISSING', which cannot be"),
        ("tests.schema.utils.NOT_A_REGISTRY", "names 'tests.schema.utils.NOT_A_REGISTRY', a dict"),
    ],
    ids=["object", "unimportable", "not-a-registry"],
)
def test_a_field_schema_registry_setting_that_names_none_is_refused(
    value: Any, message: str
) -> None:
    with (
        override_settings(SERVICE_SPECS_FIELD_SCHEMA_REGISTRY=value),
        pytest.raises(ImproperlyConfigured, match=re.escape(message)),
    ):
        field_schema_registry()
