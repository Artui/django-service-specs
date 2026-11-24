from __future__ import annotations

from django_service_specs.parameters.string_lengths import string_lengths


def test_each_length_given_is_its_json_schema_keyword() -> None:
    assert string_lengths(min_length=2, max_length=100) == {"minLength": 2, "maxLength": 100}
    assert string_lengths(max_length=100) == {"maxLength": 100}
    assert string_lengths(min_length=0) == {"minLength": 0}


def test_no_length_is_no_extra() -> None:
    assert string_lengths() is None
