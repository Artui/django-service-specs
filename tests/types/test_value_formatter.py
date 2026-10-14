from __future__ import annotations

import dataclasses
from datetime import datetime
from datetime import timezone as dt_timezone
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone

from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.dispatch.paginate_output import paginate_output
from django_service_specs.dispatch.present_for_audience import present_for_audience
from django_service_specs.output.field_marking import FieldMarking
from django_service_specs.output.output import Output
from django_service_specs.output.output_field import OutputField
from django_service_specs.output.presenter import Presenter
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.types.value_formatter import ValueFormatter
from tests.dispatch.utils import OPEN, make_user, notes_of
from tests.dispatch_app.models import Note

MONEY = ValueFormatter(
    lambda amount: f"EUR {amount}", produces="string", schema={"examples": ["EUR 1240.00"]}
)


class StampedNotes(Presenter):
    """A note's title served as a timestamp, which is where a row's stored text
    meets the formatter."""

    def output(self) -> Output:
        return Output(
            (
                OutputField(
                    "stamp",
                    "string",
                    format="date-time",
                    marking=FieldMarking.formatted(ValueFormatter.timestamp()),
                ),
            )
        )

    def present(self, value: Any) -> Any:
        return {"stamp": value.title}


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

    @pytest.mark.parametrize(
        "value",
        ["2026-02-30T10:00:00", "2026-13-01T10:00:00", "2026-01-31T25:00:00", "2026-02-30T10:00Z"],
        ids=["february-30th", "month-13", "hour-25", "february-30th-zoned"],
    )
    def test_a_date_time_string_naming_no_real_moment_is_reported_as_stored(
        self, value: str
    ) -> None:
        """Django's parser accepts the shape and then refuses the day with a
        ``ValueError``; one row's bad data must not fail the call, so the row
        is reported as it is stored, as any other string that is not a
        date-time is."""
        assert ValueFormatter.timestamp().apply(value) == value

    @pytest.mark.django_db
    def test_one_bad_row_does_not_fail_its_page(self) -> None:
        """Paging is what turned one row's bad data into a failed page: the
        row is served as stored and its neighbours are formatted."""
        ada = make_user("ada")
        stored = ["2026-01-31T14:05:09", "2026-02-30T10:00:00", "2026-03-01T08:00:00"]
        Note.objects.bulk_create([Note(owner=ada, title=title) for title in stored])
        spec = SelectorSpec(
            kind=SelectorKind.LIST, selector=notes_of, permissions=OPEN, presenter=StampedNotes()
        )

        result = dispatch(spec, principal=ada, arguments={})
        page = paginate_output(result.value, page=1, limit=3)
        rendered = present_for_audience(spec, dataclasses.replace(result, value=page.items))

        assert [row["stamp"] for row in page.envelope(rendered)["items"]] == [
            "31 Jan 2026 14:05",
            "2026-02-30T10:00:00",
            "01 Mar 2026 08:00",
        ]

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
