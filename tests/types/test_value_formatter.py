from __future__ import annotations

import dataclasses
from datetime import datetime
from datetime import timezone as dt_timezone
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone

from django_service_specs.types.value_formatter import ValueFormatter

MONEY = ValueFormatter(
    lambda amount: f"EUR {amount}", produces="string", schema={"examples": ["EUR 1240.00"]}
)


def refuse(value: Any) -> Any:
    raise AssertionError(f"rendered {value!r}")


class TestDeclaration:
    def test_the_schema_is_the_declared_type_with_the_fragment_merged_over_it(self) -> None:
        assert MONEY.json_schema() == {"examples": ["EUR 1240.00"], "type": "string"}

    def test_no_fragment_is_the_type_alone(self) -> None:
        assert ValueFormatter(str, produces="integer").json_schema() == {"type": "integer"}

    @pytest.mark.parametrize("produces", ["object", "array", "null", "str"])
    def test_a_formatter_produces_a_json_scalar(self, produces: Any) -> None:
        with pytest.raises(ImproperlyConfigured, match=rf"produces={produces!r}\) is not a JSON"):
            ValueFormatter(str, produces=produces)

    def test_the_produced_type_is_checked_first(self) -> None:
        """djangorestframework-services' order: a formatter wrong on both counts
        is told about ``produces``, and never about the fragment."""
        with pytest.raises(ImproperlyConfigured, match="is not a JSON type") as raised:
            ValueFormatter(str, produces="object", schema={"type": "integer"})  # type: ignore[arg-type]
        assert "may not set" not in str(raised.value)

    def test_the_fragment_may_not_name_the_type(self) -> None:
        """``produces`` declares it, so a formatter cannot contradict its own
        advertisement, and the refusal names the spelling that would."""
        with pytest.raises(ImproperlyConfigured, match=r"Set produces='integer' instead\.$"):
            ValueFormatter(str, produces="string", schema={"type": "integer"})

    def test_a_formatter_is_frozen(self) -> None:
        with pytest.raises(dataclasses.FrozenInstanceError):
            MONEY.produces = "number"  # type: ignore[misc]


class TestApply:
    def test_a_value_is_rendered(self) -> None:
        assert MONEY.apply("9.99") == "EUR 9.99"

    def test_a_null_is_never_rendered(self) -> None:
        """A null is the absence of the value formatted, so it passes through
        rather than every transform guarding it."""
        assert ValueFormatter(refuse, produces="string").apply(None) is None


class TestTimestamp:
    def test_an_aware_string_is_rendered_in_the_active_zone(self) -> None:
        with timezone.override("Europe/Paris"):
            assert ValueFormatter.timestamp().apply("2026-01-31T13:05:09Z") == "31 Jan 2026 14:05"

    def test_an_aware_datetime_is_rendered_as_its_string_is(self) -> None:
        moment = datetime(2026, 1, 31, 13, 5, 9, tzinfo=dt_timezone.utc)

        with timezone.override("Asia/Tokyo"):
            assert ValueFormatter.timestamp().apply(moment) == "31 Jan 2026 22:05"

    def test_a_naive_date_time_is_formatted_as_it_is(self) -> None:
        """A project with ``USE_TZ = False`` has naive date-times that are
        already local, and there is no zone to convert one from."""
        with timezone.override("Asia/Tokyo"):
            assert ValueFormatter.timestamp().apply("2026-01-31T14:05:09") == "31 Jan 2026 14:05"

    def test_a_bare_date_is_read_as_midnight(self) -> None:
        assert ValueFormatter.timestamp().apply("2026-01-31") == "31 Jan 2026 00:00"

    def test_a_date_takes_a_format_without_a_time(self) -> None:
        assert ValueFormatter.timestamp("%d %B %Y").apply("2026-01-31") == "31 January 2026"

    @pytest.mark.parametrize("value", ["soon", 3, ["2026-01-31"]], ids=["text", "number", "list"])
    def test_anything_that_is_not_a_date_time_passes_through(self, value: Any) -> None:
        assert ValueFormatter.timestamp().apply(value) == value

    def test_a_date_time_string_naming_no_real_moment_raises(self) -> None:
        """The limit of passing through, kept from djangorestframework-services:
        Django's parser accepts the shape and then refuses the day. The
        message is Python's, and its wording differs between versions."""
        with pytest.raises(ValueError):
            ValueFormatter.timestamp().apply("2026-02-30T10:00:00")

    def test_the_example_is_rendered_from_the_format_in_use(self) -> None:
        """A day past the twelfth and an hour past noon, so the example tells
        day-first from month-first and 24-hour from 12-hour."""
        assert ValueFormatter.timestamp().schema == {"examples": ["31 Jan 2026 14:05"]}
        assert ValueFormatter.timestamp("%m/%d %I%p").schema == {"examples": ["01/31 02PM"]}

    def test_a_timestamp_is_a_string(self) -> None:
        assert ValueFormatter.timestamp().json_schema() == {
            "examples": ["31 Jan 2026 14:05"],
            "type": "string",
        }
