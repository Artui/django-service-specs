"""Tests for ``filter_set_parameters``: a FilterSet's filters, read as Parameters."""

from __future__ import annotations

import json
import sys
from typing import Any

import django_filters
import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest
from django.test import RequestFactory

from django_service_specs.filters.filter_set_parameters import filter_set_parameters
from django_service_specs.http.request_arguments import request_arguments
from django_service_specs.parameters.check_arguments import check_arguments
from django_service_specs.parameters.parameter import Parameter
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.selectors.shape_queryset import shape_queryset
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from tests.dispatch.utils import make_user
from tests.dispatch_app.models import Note
from tests.filters.utils import NoteFilters, UserFilters

CSV_HELP = "Multiple values may be separated by commas."
FACTORY = RequestFactory()


def _json(payload: Any) -> HttpRequest:
    return FACTORY.post("/", data=json.dumps(payload), content_type="application/json")


def _spec(filter_set: Any) -> SelectorSpec:
    return SelectorSpec(kind=SelectorKind.LIST, selector=list, filter_set=filter_set)


def test_each_note_filter_reads_as_the_argument_django_filter_reads() -> None:
    assert filter_set_parameters(NoteFilters) == Parameters.of(
        Parameter("title", "string"),
        Parameter("title_contains", "string", help="Matches `title` with the `icontains` lookup."),
        Parameter("archived", "boolean"),
        Parameter("min_pk", "string", format="decimal", help="Matches `pk` with the `gte` lookup."),
        # django-filter gives every CSV filter this ``help_text`` of its own, and
        # it holds for the query string, where ``?pks=1,2`` is the spelling.
        Parameter("pks", "array", items="number", help=CSV_HELP),
        Parameter("pk_between", "array", items="number", help=CSV_HELP),
        # Two arguments, because django-filter reads ``pk_range_min`` and
        # ``pk_range_max`` off the data and never a ``pk_range`` of its own.
        Parameter("pk_range_min", "string", format="decimal", help="The `min` bound of `pk`."),
        Parameter("pk_range_max", "string", format="decimal", help="The `max` bound of `pk`."),
        Parameter(
            "kind",
            "string",
            choices=("draft", "final"),
            help="Matches `title` with the `exact` lookup.",
        ),
        Parameter(
            "kinds",
            "array",
            items="string",
            choices=("draft", "final"),
            help="Matches `title` with the `exact` lookup.",
        ),
        Parameter("owner", "string"),
        Parameter(
            "owners", "array", items="string", help="Matches `owner` with the `exact` lookup."
        ),
        Parameter("explained", "string", help="Titles starting with this."),
    )


def test_the_date_time_and_choice_shapes() -> None:
    assert filter_set_parameters(UserFilters) == Parameters.of(
        Parameter(
            "joined_on",
            "string",
            format="date",
            help="Matches `date_joined` with the `date` lookup.",
        ),
        Parameter(
            "joined_since",
            "string",
            format="date-time",
            help="Matches `date_joined` with the `gt` lookup.",
        ),
        Parameter(
            "joined_after", "string", format="date", help="The `after` bound of `date_joined`."
        ),
        Parameter(
            "joined_before", "string", format="date", help="The `before` bound of `date_joined`."
        ),
        Parameter(
            "joined_at_after",
            "string",
            format="date-time",
            help="The `after` bound of `date_joined`.",
        ),
        Parameter(
            "joined_at_before",
            "string",
            format="date-time",
            help="The `before` bound of `date_joined`.",
        ),
        Parameter("joined_time", "string", help="Matches `date_joined` with the `time` lookup."),
        Parameter(
            "joined_between_after", "string", help="The `after` bound of `date_joined__time`."
        ),
        Parameter(
            "joined_between_before", "string", help="The `before` bound of `date_joined__time`."
        ),
        Parameter("token", "string", help="Matches `username` with the `exact` lookup."),
        Parameter(
            "level",
            "integer",
            choices=(1, 2),
            help="Matches `pk` with the `exact` lookup.",
        ),
        # A ChoiceField compares the string of each choice, so a mixed set is
        # offered as the strings it will match.
        Parameter(
            "mixed",
            "string",
            choices=("1", "b"),
            help="Matches `username` with the `exact` lookup.",
        ),
        Parameter(
            "grouped",
            "string",
            choices=("ada", "bob", "eve"),
            help="Matches `username` with the `exact` lookup.",
        ),
        Parameter("deferred", "string", help="Matches `username` with the `exact` lookup."),
        Parameter("group", "string", help="Matches `groups` with the `exact` lookup."),
        Parameter("ordering", "array", items="string", choices=("username", "-username")),
        Parameter("spent", "string", help="Matches `pk` with the `exact` lookup."),
    )


def test_a_choice_set_of_booleans_is_offered_as_strings() -> None:
    class Flags(django_filters.FilterSet):
        flag = django_filters.ChoiceFilter(field_name="is_staff", choices=[(True, "Yes")])

    assert filter_set_parameters(Flags).get("flag") == Parameter(
        "flag", "string", choices=("True",), help="Matches `is_staff` with the `exact` lookup."
    )


def test_choices_given_as_a_mapping_offer_its_keys() -> None:
    # Django 5 takes ``{value: label}`` for choices; iterating it yields the values.
    class Kinds(django_filters.FilterSet):
        kind = django_filters.ChoiceFilter(
            field_name="title", choices={"draft": "Draft", "final": "Final"}
        )

    assert filter_set_parameters(Kinds).get("kind") == Parameter(
        "kind",
        "string",
        choices=("draft", "final"),
        help="Matches `title` with the `exact` lookup.",
    )


def test_a_numeric_multiple_choice_is_an_array_of_integers() -> None:
    class Levels(django_filters.FilterSet):
        levels = django_filters.MultipleChoiceFilter(field_name="pk", choices=[(1, "a"), (2, "b")])

    assert filter_set_parameters(Levels).get("levels") == Parameter(
        "levels",
        "array",
        items="integer",
        choices=(1, 2),
        help="Matches `pk` with the `exact` lookup.",
    )


def test_a_suffixed_filter_of_an_unknown_kind_reads_as_strings() -> None:
    class Lookup(django_filters.Filter):
        field_class = django_filters.fields.RangeField

    class Custom(django_filters.FilterSet):
        span = Lookup(field_name="pk")

    assert filter_set_parameters(Custom) == Parameters.of(
        Parameter("span_min", "string", help="The `min` bound of `pk`."),
        Parameter("span_max", "string", help="The `max` bound of `pk`."),
    )


def test_a_csv_filter_of_text_reads_strings() -> None:
    class CharInFilter(django_filters.BaseInFilter, django_filters.CharFilter): ...

    class Titled(django_filters.FilterSet):
        titles = CharInFilter(field_name="title", lookup_expr="in")

    assert filter_set_parameters(Titled) == Parameters.of(
        Parameter(
            "titles",
            "array",
            items="string",
            help=CSV_HELP,
        ),
    )


def test_an_author_s_help_text_names_both_bounds_of_a_range() -> None:
    class Priced(django_filters.FilterSet):
        pk_range = django_filters.RangeFilter(field_name="pk", help_text="Rows in this pk window.")

    assert filter_set_parameters(Priced) == Parameters.of(
        Parameter("pk_range_min", "string", format="decimal", help="Rows in this pk window."),
        Parameter("pk_range_max", "string", format="decimal", help="Rows in this pk window."),
    )


def test_two_filters_reading_one_argument_are_refused() -> None:
    # ``joined`` reads ``joined_after``, so a filter called that would answer
    # the same key: django-filter would hand one value to both.
    class Clash(django_filters.FilterSet):
        joined = django_filters.DateFromToRangeFilter(field_name="date_joined")
        joined_after = django_filters.DateTimeFilter(field_name="date_joined")

    with pytest.raises(ImproperlyConfigured, match=r"\['joined_after'\] more than once"):
        filter_set_parameters(Clash)


def test_an_object_with_no_filters_reads_as_nothing_and_needs_no_django_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A duck-typed stand-in declares no filters, so it is read without the extra.
    monkeypatch.setitem(sys.modules, "django_filters", None)
    assert filter_set_parameters(lambda data, queryset: queryset) == Parameters()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("arguments", "titles"),
    [
        ({"title": "draft"}, ["draft"]),
        ({"title_contains": "RAF"}, ["draft"]),
        ({"archived": True}, ["final"]),
        ({"kind": "final"}, ["final"]),
        ({"kinds": ["draft", "final"]}, ["draft", "final"]),
        ({"explained": "oth"}, ["other"]),
    ],
)
def test_an_argument_shaped_by_its_parameter_narrows_the_rows(
    arguments: dict[str, Any], titles: list[str]
) -> None:
    # The reading is right only if the argument it describes is the one the
    # FilterSet reads: shaped by the Parameter, passed by the shape check,
    # accepted by the FilterSet as ``shape_queryset`` binds it, and narrowing
    # the rows.
    ada = make_user("ada")
    for title, archived in (("draft", False), ("final", True), ("other", False)):
        Note.objects.create(owner=ada, title=title, archived=archived)
    checked = check_arguments(filter_set_parameters(NoteFilters), arguments)
    rows = shape_queryset(Note.objects.all(), _spec(NoteFilters), checked, source_label="x")
    assert sorted(rows.values_list("title", flat=True)) == titles


@pytest.mark.django_db
@pytest.mark.parametrize(
    "arguments",
    [
        lambda pks: {"min_pk": pks[1]},
        lambda pks: {"pks": [pks[1], pks[2]]},
        lambda pks: {"pk_between": [pks[1], pks[2]]},
        lambda pks: {"pk_range_min": pks[1], "pk_range_max": pks[2]},
    ],
)
def test_the_number_shapes_narrow_the_rows(arguments: Any) -> None:
    ada = make_user("ada")
    pks = [Note.objects.create(owner=ada, title=str(n)).pk for n in range(3)]
    checked = check_arguments(filter_set_parameters(NoteFilters), arguments(pks))
    rows = shape_queryset(Note.objects.all(), _spec(NoteFilters), checked, source_label="x")
    assert sorted(rows.values_list("pk", flat=True)) == pks[1:]


class _ById(django_filters.FilterSet):
    pk = django_filters.NumberFilter()
    pk_range = django_filters.RangeFilter(field_name="pk")


_BIG = 2**53
"""The first integer past which a binary float cannot tell neighbours apart."""


@pytest.fixture
def big_ids() -> list[int]:
    ada = make_user("ada")
    return [Note.objects.create(pk=pk, owner=ada, title=str(pk)).pk for pk in (_BIG, _BIG + 1)]


def _matched(request: Any) -> list[int]:
    params = filter_set_parameters(_ById)
    checked = check_arguments(params, request_arguments(request, params))
    rows = shape_queryset(Note.objects.all(), _spec(_ById), checked, source_label="x")
    return list(rows.values_list("pk", flat=True))


@pytest.mark.django_db
@pytest.mark.parametrize(
    "request_for",
    [
        pytest.param(lambda pk: FACTORY.get(f"/?pk={pk}"), id="query-string"),
        pytest.param(lambda pk: _json({"pk": str(pk)}), id="json-string"),
        # A JSON number was already exact: the decoder makes it an int.
        pytest.param(lambda pk: _json({"pk": pk}), id="json-number"),
        pytest.param(
            lambda pk: FACTORY.get(f"/?pk_range_min={pk}&pk_range_max={pk}"), id="range-bounds"
        ),
    ],
)
@pytest.mark.parametrize("index", [0, 1])
def test_a_number_filter_matches_a_key_past_a_float_s_precision_exactly(
    big_ids: list[int], request_for: Any, index: int
) -> None:
    # A number filter's form field is a ``DecimalField``, which reads a string
    # exactly. Declared a JSON number, its string was read as a float on the
    # way, and 2**53 + 1 came back as 2**53: the filter answered with the
    # neighbouring row.
    assert _matched(request_for(big_ids[index])) == [big_ids[index]]


@pytest.mark.django_db
def test_a_related_row_is_named_by_its_key_as_a_string() -> None:
    ada, bob = make_user("ada"), make_user("bob")
    Note.objects.create(owner=ada, title="a")
    Note.objects.create(owner=bob, title="b")
    arguments = {"owner": str(bob.pk), "owners": [str(bob.pk)]}
    checked = check_arguments(filter_set_parameters(NoteFilters), arguments)
    rows = shape_queryset(Note.objects.all(), _spec(NoteFilters), checked, source_label="x")
    assert list(rows.values_list("title", flat=True)) == ["b"]


@pytest.mark.django_db
def test_the_date_shapes_narrow_the_rows() -> None:
    ada = make_user("ada")
    User.objects.filter(pk=ada.pk).update(date_joined="2026-01-02T10:00:00Z")
    make_user("bob")
    User.objects.filter(username="bob").update(date_joined="2026-03-04T10:00:00Z")
    arguments = {
        "joined_on": "2026-01-02",
        "joined_since": "2026-01-01T00:00:00Z",
        "joined_after": "2026-01-01",
        "joined_before": "2026-01-03",
        "joined_at_after": "2026-01-02T09:00:00Z",
        "joined_at_before": "2026-01-02T11:00:00Z",
    }
    checked = check_arguments(filter_set_parameters(UserFilters), arguments)
    rows = shape_queryset(User.objects.all(), _spec(UserFilters), checked, source_label="x")
    assert list(rows.values_list("username", flat=True)) == ["ada"]
