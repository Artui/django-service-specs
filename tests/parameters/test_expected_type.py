"""``expected_type``: one whole sentence per type a value is not."""

from __future__ import annotations

import pytest

from django_service_specs.parameters.expected_type import expected_type
from django_service_specs.parameters.parameters import JSON_TYPES


@pytest.mark.parametrize("json_type", sorted(JSON_TYPES))
def test_every_json_type_has_its_own_sentence(json_type: str) -> None:
    # A whole sentence per type, with the type named in it, so a translator
    # sees each one entire rather than a template with a code word dropped in.
    assert json_type in expected_type(json_type)


def test_the_decimal_format_names_both_the_forms_it_accepts() -> None:
    assert expected_type("decimal") == "Expected a decimal string or a number."


def test_a_file_has_its_own_sentence() -> None:
    # Not a JSON type, and refused as one all the same: a string or a mapping
    # sent where a file is declared.
    assert expected_type("file") == "Expected a file."
