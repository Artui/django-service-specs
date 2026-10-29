"""The flat-source page's example, run, and each outcome the page states."""

from __future__ import annotations

from django_service_specs import flat_arguments
from docs.examples import flat


def test_the_source_reads_as_strings_with_its_blanks_and_token_dropped() -> None:
    assert flat_arguments(flat.NOTES, flat.QUERY) == flat.READ


def test_the_route_is_merged_and_the_whole_coerced_and_checked() -> None:
    assert flat.arguments(flat.QUERY, flat.ROUTE) == flat.TYPED
