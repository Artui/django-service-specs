"""Tests for ``filter_set_parameters``: a FilterSet's filters, read as Parameters."""

from __future__ import annotations

import dataclasses
import sys
from decimal import Decimal
from typing import Any, ClassVar

import django_filters
import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ImproperlyConfigured
from django.utils.functional import lazy

from django_service_specs.adapters.filters.filter_set_parameters import filter_set_parameters
from django_service_specs.authorization.not_permitted import NotPermitted
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.parameters.check_arguments import check_arguments
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.parameters import Parameter, Parameters
from django_service_specs.schema.parameters_schema import parameters_schema
from django_service_specs.selectors.shape_queryset import shape_queryset
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.types.selector_kind import SelectorKind
from tests.adapters.filters.utils import NoteFilters, NumberInFilter, UserFilters, notes
from tests.dispatch.utils import Refuse, make_user
from tests.dispatch_app.models import Note
from tests.parameters.utils import coded

CSV_HELP = "Multiple values may be separated by commas."
# django-filter's ``MaxValueValidator(1e50)`` on a number filter, mirrored below.
BOUNDED: dict[str, Any] = {"minimum": -1e50, "maximum": 1e50}


def _spec(filter_set: Any) -> SelectorSpec:
    return SelectorSpec(kind=SelectorKind.LIST, selector=list, filter_set=filter_set)


def test_each_note_filter_reads_as_the_argument_django_filter_reads() -> None:
    assert filter_set_parameters(NoteFilters) == Parameters.of(
        Parameter("title", "string"),
        Parameter("title_contains", "string", help="Matches `title` with the `icontains` lookup."),
        Parameter("archived", "boolean"),
        Parameter(
            "min_pk",
            "string",
            format="decimal",
            help="Matches `pk` with the `gte` lookup.",
            **BOUNDED,
        ),
        # django-filter gives every CSV filter this ``help_text`` of its own, and
        # it holds for the query string, where ``?pks=1,2`` is the spelling.
        # Each element is a number filter's decimal, bounded as one is.
        Parameter("pks", "array", items="string", format="decimal", help=CSV_HELP, **BOUNDED),
        Parameter(
            "pk_between", "array", items="string", format="decimal", help=CSV_HELP, **BOUNDED
        ),
        # Two arguments, because django-filter reads ``pk_range_min`` and
        # ``pk_range_max`` off the data and never a ``pk_range`` of its own.
        Parameter(
            "pk_range_min", "string", format="decimal", help="The `min` bound of `pk`.", **BOUNDED
        ),
        Parameter(
            "pk_range_max", "string", format="decimal", help="The `max` bound of `pk`.", **BOUNDED
        ),
        Parameter(
            "kind",
            "string",
            choices=("draft", "final"),
            choice_labels=(("draft", "Draft"), ("final", "Final")),
            help="Matches `title` with the `exact` lookup.",
        ),
        Parameter(
            "kinds",
            "array",
            items="string",
            choices=("draft", "final"),
            choice_labels=(("draft", "Draft"), ("final", "Final")),
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
            choice_labels=((1, "One"), (2, "Two")),
            help="Matches `pk` with the `exact` lookup.",
        ),
        # A ChoiceField compares the string of each choice, so a mixed set is
        # offered as the strings it will match.
        Parameter(
            "mixed",
            "string",
            choices=("1", "b"),
            choice_labels=(("1", "One"), ("b", "B")),
            help="Matches `username` with the `exact` lookup.",
        ),
        Parameter(
            "grouped",
            "string",
            choices=("ada", "bob", "eve"),
            choice_labels=(("ada", "Ada"), ("bob", "Bob"), ("eve", "Eve")),
            help="Matches `username` with the `exact` lookup.",
        ),
        Parameter("deferred", "string", help="Matches `username` with the `exact` lookup."),
        Parameter("group", "string", help="Matches `groups` with the `exact` lookup."),
        # The labels an ordering filter builds for itself.
        Parameter(
            "ordering",
            "array",
            items="string",
            choices=("username", "-username"),
            choice_labels=(("username", "Username"), ("-username", "Username (descending)")),
        ),
        Parameter("spent", "string", help="Matches `pk` with the `exact` lookup."),
    )


def test_a_choice_set_of_booleans_is_offered_as_strings() -> None:
    class Flags(django_filters.FilterSet):
        flag = django_filters.ChoiceFilter(field_name="is_staff", choices=[(True, "Yes")])

    assert filter_set_parameters(Flags).get("flag") == Parameter(
        "flag",
        "string",
        choices=("True",),
        choice_labels=(("True", "Yes"),),
        help="Matches `is_staff` with the `exact` lookup.",
    )


def test_choices_given_as_a_mapping_offer_its_keys() -> None:
    # Django 5 takes ``{value: label}`` for choices.
    class Kinds(django_filters.FilterSet):
        kind = django_filters.ChoiceFilter(
            field_name="title", choices={"draft": "Draft", "final": "Final"}
        )

    assert filter_set_parameters(Kinds).get("kind") == Parameter(
        "kind",
        "string",
        choices=("draft", "final"),
        choice_labels=(("draft", "Draft"), ("final", "Final")),
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
        choice_labels=((1, "a"), (2, "b")),
        help="Matches `pk` with the `exact` lookup.",
    )


def _offered(filter_obj: Any) -> Parameter:
    """The one Parameter a FilterSet holding only ``filter_obj`` reads, under the name ``read``."""
    filter_set = type("Offered", (django_filters.FilterSet,), {"read": filter_obj})
    parameter = filter_set_parameters(filter_set).get("read")
    assert parameter is not None
    return parameter


def test_a_choice_filter_s_values_carry_their_labels() -> None:
    read = _offered(
        django_filters.ChoiceFilter(
            field_name="title", choices=[("draft", "Draft"), ("final", "Final")]
        )
    )
    assert read.choices == ("draft", "final")
    assert read.choice_labels == (("draft", "Draft"), ("final", "Final"))


def test_an_integer_choice_set_keeps_its_labels_on_the_integers() -> None:
    read = _offered(django_filters.ChoiceFilter(field_name="pk", choices=[(1, "One"), (2, "Two")]))
    assert read.type == "integer"
    assert read.choices == (1, 2)
    assert read.choice_labels == ((1, "One"), (2, "Two"))
    assert all(type(value) is int for value, _label in read.choice_labels)


def test_a_mixed_choice_set_keys_its_labels_on_the_strings_it_offers() -> None:
    # Not every value an ``int``, so each is the string ``ChoiceField`` compares;
    # a label keyed on the ``1`` would name no choice, and ``Parameter`` would
    # refuse it.
    read = _offered(
        django_filters.ChoiceFilter(field_name="title", choices=[(1, "One"), ("b", "Bee")])
    )
    assert read.choices == ("1", "b")
    assert read.choice_labels == (("1", "One"), ("b", "Bee"))


def test_a_multiple_choice_filter_s_labels_describe_each_element() -> None:
    read = _offered(
        django_filters.MultipleChoiceFilter(field_name="pk", choices=[(1, "One"), (2, "Two")])
    )
    assert (read.type, read.items, read.choices) == ("array", "integer", (1, 2))
    assert read.choice_labels == ((1, "One"), (2, "Two"))


def test_a_named_group_flattens_with_its_labels() -> None:
    read = _offered(
        django_filters.ChoiceFilter(
            field_name="title",
            choices=[
                ("Open", [("draft", "Draft"), ("review", "In review")]),
                ("Closed", (("final", "Final"),)),
            ],
        )
    )
    assert read.choices == ("draft", "review", "final")
    assert read.choice_labels == (("draft", "Draft"), ("review", "In review"), ("final", "Final"))


def test_a_mapping_s_labels_are_read_through_its_items() -> None:
    read = _offered(
        django_filters.ChoiceFilter(
            field_name="title", choices={"draft": "Draft", "final": "Final"}
        )
    )
    assert read.choices == ("draft", "final")
    assert read.choice_labels == (("draft", "Draft"), ("final", "Final"))


@pytest.mark.parametrize(
    "choices",
    [
        pytest.param({"Open": {"draft": "Draft"}, "final": "Final"}, id="a mapping in a mapping"),
        pytest.param({"Open": [("draft", "Draft")], "final": "Final"}, id="pairs in a mapping"),
        pytest.param({"Open": (("draft", "Draft"),), "final": "Final"}, id="a tuple in a mapping"),
        pytest.param([("Open", {"draft": "Draft"}), ("final", "Final")], id="a mapping in pairs"),
    ],
)
def test_a_named_group_flattens_whichever_of_django_s_spellings_holds_it(choices: Any) -> None:
    # Each spelling Django 5's ``normalize_choices`` reads as a group: read as a
    # label, the group's name would be offered as a value no form field accepts.
    read = _offered(django_filters.ChoiceFilter(field_name="title", choices=choices))
    assert read.choices == ("draft", "final")
    assert read.choice_labels == (("draft", "Draft"), ("final", "Final"))


def test_bare_values_are_unlabelled() -> None:
    read = _offered(django_filters.ChoiceFilter(field_name="title", choices=["draft", "final"]))
    assert read.choices == ("draft", "final")
    assert read.choice_labels is None


def test_a_bare_value_beside_a_labelled_one_stays_unlabelled() -> None:
    # ``Parameter`` lets a choice go unlabelled, so nothing is dropped or invented.
    read = _offered(
        django_filters.ChoiceFilter(field_name="title", choices=[("draft", "Draft"), "final"])
    )
    assert read.choices == ("draft", "final")
    assert read.choice_labels == (("draft", "Draft"),)
    assert parameters_schema(Parameters.of(read))["properties"]["read"]["anyOf"] == [
        {"const": "draft", "title": "Draft"},
        {"const": "final"},
    ]


def test_a_lazy_label_stays_lazy_until_the_schema_renders_it() -> None:
    renders: list[str] = []

    def rendered(text: str) -> str:
        renders.append(text)
        return text.upper()

    label = lazy(rendered, str)("draft label")
    read = _offered(django_filters.ChoiceFilter(field_name="title", choices=[("draft", label)]))
    assert read.choice_labels is not None
    assert read.choice_labels[0][1] is label
    # Read off the declaration and joined to a spec's reads, a copy's too, at
    # import where the translation machinery may not be ready: nothing renders it.
    fresh = django_filters.ChoiceFilter(field_name="title", choices=[("draft", label)])
    filter_set = type("Lazy", (django_filters.FilterSet,), {"read": fresh})
    dataclasses.replace(_spec(filter_set), selector=dict)
    assert renders == []
    schema = parameters_schema(Parameters.of(read))["properties"]["read"]
    assert schema["anyOf"] == [{"const": "draft", "title": "DRAFT LABEL"}]


def test_a_labelled_filter_s_schema_states_its_labels() -> None:
    read = _offered(
        django_filters.ChoiceFilter(
            field_name="title", choices=[("draft", "Draft"), ("final", "Final")]
        )
    )
    assert parameters_schema(Parameters.of(read))["properties"]["read"]["anyOf"] == [
        {"const": "draft", "title": "Draft"},
        {"const": "final", "title": "Final"},
    ]


def test_an_ordering_filter_s_own_labels_reach_the_schema() -> None:
    # django-filter labels these itself, so its schema moves with no author's label.
    read = _offered(django_filters.OrderingFilter(fields=["username"]))
    assert parameters_schema(Parameters.of(read))["properties"]["read"]["items"]["anyOf"] == [
        {"const": "username", "title": "Username"},
        {"const": "-username", "title": "Username (descending)"},
    ]


def test_labels_that_only_repeat_the_values_keep_the_enum() -> None:
    read = _offered(
        django_filters.ChoiceFilter(field_name="title", choices=[("draft", "draft"), (1, "1")])
    )
    assert read.choice_labels == (("draft", "draft"), ("1", "1"))
    schema = parameters_schema(Parameters.of(read))["properties"]["read"]
    assert schema["enum"] == ["draft", "1"]
    assert "anyOf" not in schema


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


def test_a_csv_filter_of_dates_reads_strings_with_no_format() -> None:
    # An element takes no format but a decimal, so a date's is left to the
    # FilterSet's own field, as a text element's whole reading is.
    class DateInFilter(django_filters.BaseInFilter, django_filters.DateFilter): ...

    class Dated(django_filters.FilterSet):
        days = DateInFilter(field_name="date_joined__date", lookup_expr="in")

    assert filter_set_parameters(Dated) == Parameters.of(
        Parameter("days", "array", items="string", help=CSV_HELP)
    )


def test_an_author_s_help_text_names_both_bounds_of_a_range() -> None:
    class Priced(django_filters.FilterSet):
        pk_range = django_filters.RangeFilter(field_name="pk", help_text="Rows in this pk window.")

    assert filter_set_parameters(Priced) == Parameters.of(
        Parameter(
            "pk_range_min", "string", format="decimal", help="Rows in this pk window.", **BOUNDED
        ),
        Parameter(
            "pk_range_max", "string", format="decimal", help="Rows in this pk window.", **BOUNDED
        ),
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


def _matched(arguments: dict[str, Any]) -> list[int]:
    params = filter_set_parameters(_ById)
    checked = check_arguments(params, arguments)
    rows = shape_queryset(Note.objects.all(), _spec(_ById), checked, source_label="x")
    return list(rows.values_list("pk", flat=True))


@pytest.mark.django_db
@pytest.mark.parametrize(
    "arguments_for",
    [
        # What a query string or a JSON string hands on: the digits as sent.
        pytest.param(lambda pk: {"pk": str(pk)}, id="string"),
        # A JSON number was already exact: the decoder makes it an int.
        pytest.param(lambda pk: {"pk": pk}, id="number"),
        pytest.param(
            lambda pk: {"pk_range_min": str(pk), "pk_range_max": str(pk)}, id="range-bounds"
        ),
    ],
)
@pytest.mark.parametrize("index", [0, 1])
def test_a_number_filter_matches_a_key_past_a_float_s_precision_exactly(
    big_ids: list[int], arguments_for: Any, index: int
) -> None:
    # A number filter's form field is a ``DecimalField``, which reads a string
    # exactly. Declared a JSON number, its string was read as a float on the
    # way, and 2**53 + 1 came back as 2**53: the filter answered with the
    # neighbouring row.
    assert _matched(arguments_for(big_ids[index])) == [big_ids[index]]


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


class _Bounded(django_filters.FilterSet):
    """Each number filter a caller can reach with a decimal string, by lookup."""

    pk = django_filters.NumberFilter()
    pk_lt = django_filters.NumberFilter(field_name="pk", lookup_expr="lt")
    pk_gt = django_filters.NumberFilter(field_name="pk", lookup_expr="gt")
    pk_range = django_filters.RangeFilter(field_name="pk")
    pks = NumberInFilter(field_name="pk", lookup_expr="in")


_BOUNDED_NAMES = ["pk", "pk_lt", "pk_gt", "pk_range_min", "pk_range_max", "pks"]
_ABOVE = "Ensure this value is less than or equal to 1e+50."
_BELOW = "Ensure this value is greater than or equal to -1e+50."


def _at(name: str, messages: list[str]) -> dict[str, Any]:
    """Where a refusal of ``name``'s one value sits: at the name, or a CSV filter's at index 0."""
    return {name: {0: messages}} if name == "pks" else {name: messages}


def _sent(name: str, value: str) -> dict[str, Any]:
    """One value of ``name`` as a transport hands it on: a CSV filter's as a list of one."""
    return {name: [value]} if name == "pks" else {name: value}


def _dispatch_refused(arguments: dict[str, Any]) -> None:
    # The permission check refuses every call, so the shape check answering is
    # what proves it ran first, and nothing past it - the FilterSet's own
    # validators, the query - is reached by a value it let through.
    spec = SelectorSpec(
        kind=SelectorKind.LIST, selector=notes, filter_set=_Bounded, permissions=[Refuse()]
    )
    dispatch(
        spec,
        principal=make_user("ada"),
        arguments=arguments,
    )


@pytest.mark.django_db
@pytest.mark.parametrize("name", _BOUNDED_NAMES)
@pytest.mark.parametrize(
    ("value", "message"),
    [
        # Cheap to convert if the guard ever regresses: a value whose integer
        # has a million digits would hang the suite rather than fail it.
        ("1e400", _ABOVE),
        ("-1e400", _BELOW),
        # The spelling that held a worker for minutes. Safe here whatever
        # regresses: the permission check refuses every call, so a value the
        # shape check let through ends at NotPermitted, never at ``int()``.
        ("1E+999999999", _ABOVE),
        ("-1E+999999999", _BELOW),
        # Just past the float django-filter's validator compares against,
        # which is 1.00000000000000007...e50 rather than 10**50.
        ("1.0000000000000001e50", _ABOVE),
        ("-1.0000000000000001e50", _BELOW),
    ],
)
def test_a_number_past_django_filter_s_bound_is_refused_by_the_shape_check(
    name: str, value: str, message: str
) -> None:
    # A range's bounds have no validator in django-filter, and a number
    # filter's has none below, so either value reached the integer field's
    # ``int()``: twenty bytes of query string spelling ``1E+999999999`` built a
    # billion-digit integer and held a worker for minutes.
    with pytest.raises(InvalidArguments) as caught:
        _dispatch_refused(_sent(name, value))
    assert caught.value.detail == _at(name, [message])


@pytest.mark.django_db
@pytest.mark.parametrize("name", _BOUNDED_NAMES)
@pytest.mark.parametrize(
    "value", ["1e50", "-1e50", "100000000000000000000000000000000000000000000000001"]
)
def test_a_number_at_django_filter_s_bound_passes_the_shape_check(name: str, value: str) -> None:
    # Inclusive, and the same float django-filter compares against, so 10**50
    # and 10**50 + 1 both sit inside it, as they do in django-filter.
    with pytest.raises(NotPermitted):
        _dispatch_refused(_sent(name, value))


@pytest.mark.django_db
def test_a_json_number_past_the_bound_is_refused_too() -> None:
    with pytest.raises(InvalidArguments) as caught:
        _dispatch_refused({"pk_range_max": 1e60, "pk_range_min": -1e60})
    assert caught.value.detail == {"pk_range_max": [_ABOVE], "pk_range_min": [_BELOW]}


@pytest.mark.django_db
@pytest.mark.parametrize(
    "arguments",
    [
        pytest.param({"pks": ["1", "1E+999999999", "-1E+999999999"]}, id="strings"),
        pytest.param({"pks": [1, 1e60, -1e60]}, id="numbers"),
    ],
)
def test_a_csv_number_filter_s_element_past_the_bound_is_refused_at_its_index(
    arguments: dict[str, Any],
) -> None:
    # Each element is bounded as a number filter's value is, in the words and
    # with the codes a DRF field gives, before anything converts it.
    with pytest.raises(InvalidArguments) as caught:
        _dispatch_refused(arguments)
    assert coded(caught.value.detail) == {
        "pks": {1: [(_ABOVE, "max_value")], 2: [(_BELOW, "min_value")]}
    }


class _ByIds(django_filters.FilterSet):
    pks = NumberInFilter(field_name="pk", lookup_expr="in")


@pytest.mark.django_db
@pytest.mark.parametrize(
    "arguments_for",
    [
        pytest.param(lambda pk: {"pks": ["1", str(pk)]}, id="strings"),
        pytest.param(lambda pk: {"pks": [1, pk]}, id="numbers"),
    ],
)
def test_a_csv_number_filter_matches_a_key_past_a_float_s_precision_exactly(
    big_ids: list[int], arguments_for: Any
) -> None:
    params = filter_set_parameters(_ByIds)
    checked = check_arguments(params, arguments_for(big_ids[1]))
    rows = shape_queryset(Note.objects.all(), _spec(_ByIds), checked, source_label="x")
    assert list(rows.values_list("pk", flat=True)) == [big_ids[1]]


_FORTY_DIGITS = "0.1234567890123456789012345678901234567891"
"""A fraction no float holds: read through one, it comes back as 0.12345678901234568."""


class _Recorded(django_filters.FilterSet):
    """Records the values its CSV number filter hands on, as django-filter cleaned them."""

    amounts = NumberInFilter(method="record")
    seen: ClassVar[list[Any]] = []

    def record(self, queryset: Any, name: str, value: Any) -> Any:
        self.seen.append(value)
        return queryset


@pytest.mark.django_db
@pytest.mark.parametrize(
    "arguments",
    [
        pytest.param({"amounts": [_FORTY_DIGITS, "2"]}, id="strings"),
        pytest.param({"amounts": [_FORTY_DIGITS, 2]}, id="a-string-and-a-number"),
    ],
)
def test_a_csv_number_filter_s_fraction_reaches_the_filter_exactly(
    arguments: dict[str, Any],
) -> None:
    # Read as a float on the way, the fraction reached the filter rounded to
    # seventeen digits; a decimal element stays the string it spells.
    _Recorded.seen.clear()
    params = filter_set_parameters(_Recorded)
    checked = check_arguments(params, arguments)
    shape_queryset(Note.objects.all(), _spec(_Recorded), checked, source_label="x")
    assert _Recorded.seen == [[Decimal(_FORTY_DIGITS), Decimal(2)]]
