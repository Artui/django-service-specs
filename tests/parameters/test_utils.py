from __future__ import annotations

import pytest

from django_service_specs.parameters.parameter import JSON_TYPES
from django_service_specs.parameters.utils import NON_FIELD_ERRORS, expected_type


def test_non_field_errors_is_django_and_drfs_spelling() -> None:
    assert NON_FIELD_ERRORS == "non_field_errors"


@pytest.mark.parametrize("json_type", sorted(JSON_TYPES))
def test_every_json_type_has_its_own_sentence(json_type: str) -> None:
    # A whole sentence per type, with the type named in it, so a translator
    # sees each one entire rather than a template with a code word dropped in.
    assert json_type in expected_type(json_type)


def test_the_decimal_format_names_both_the_forms_it_accepts() -> None:
    assert expected_type("decimal") == "Expected a decimal string or a number."
