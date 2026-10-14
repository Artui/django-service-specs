from __future__ import annotations

import pytest

from django_service_specs.parameters.parameter import JSON_TYPES
from django_service_specs.parameters.utils import expected_type, parse_number


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


@pytest.mark.parametrize(
    ("json_type", "text", "number"),
    [
        # Django's ``IntegerField`` strips a trailing ``.0*`` and space before
        # ``int``, so it reads both of these as 5, and pydantic's lax ``int``
        # refuses both: the reading is Django's, which is looser here.
        ("integer", "5.", 5),
        ("integer", "5 .0", 5),
        # ``float`` reads the first, as pydantic's ``float`` does, and refuses
        # the second, as both Django's ``FloatField`` and pydantic do.
        ("number", "5.", 5.0),
        ("number", "5 .0", None),
    ],
)
def test_a_trailing_point_is_read_as_django_reads_it(
    json_type: str, text: str, number: float | None
) -> None:
    assert parse_number(json_type, text) == number


@pytest.mark.parametrize("text", ["\u0665", "\uff15", "\u0665.0", "\u00a05"])
@pytest.mark.parametrize("json_type", ["integer", "number"])
def test_a_number_spelled_outside_ascii_spells_none(json_type: str, text: str) -> None:
    # Python's ``int`` and ``float`` read each of these as 5; no JSON number is
    # spelled so, and pydantic's lax mode refuses every one.
    assert parse_number(json_type, text) is None


@pytest.mark.parametrize(
    ("text", "number"),
    [("7", 7), (" 7 ", 7), ("+7", 7), (str(2**63 + 1), 2**63 + 1), ("7.0", 7.0), ("7e0", 7.0)],
)
def test_a_number_spelling_an_integer_is_that_exact_int(text: str, number: float) -> None:
    # The integer a JSON decoder makes of the same literal, exact past 2**53,
    # and a float only where a point or an exponent is spelled.
    parsed = parse_number("number", text)
    assert parsed == number
    assert type(parsed) is type(number)


@pytest.mark.parametrize(
    ("text", "number"), [("1E5", 100000.0), ("1e5", 100000.0), ("2.5E-1", 0.25)]
)
def test_an_exponent_in_either_case_spells_a_float(text: str, number: float) -> None:
    # JSON spells an exponent ``e`` or ``E``, and so does a decoder's float.
    parsed = parse_number("number", text)
    assert parsed == number
    assert type(parsed) is float


@pytest.mark.parametrize("text", ["1E400", "-1E400"])
def test_an_exponent_past_a_float_s_range_in_either_case_spells_none(text: str) -> None:
    assert parse_number("number", text) is None
