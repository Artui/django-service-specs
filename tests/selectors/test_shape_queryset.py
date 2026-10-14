"""Tests for ``shape_queryset`` — the five shaping fields, ``filter_set`` last."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, ClassVar

import django
import django_filters
import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth.models import Group, Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ImproperlyConfigured
from django.db.models import Count, QuerySet
from django.db.models.functions import Length
from django.test import RequestFactory

from django_service_specs.authorization.unrestricted import Unrestricted
from django_service_specs.dispatch.adispatch import adispatch
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.http.request_arguments import request_arguments
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.parameter import Parameter
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.pool.base_pool import base_pool
from django_service_specs.selectors.shape_queryset import shape_queryset
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from tests.adapter_app.models import Author as BookAuthor
from tests.adapter_app.models import Book, Edition, Placement
from tests.dispatch.utils import make_user
from tests.dispatch_app.models import Note
from tests.filters.utils import (
    EditionNumberFilters,
    NoteFilters,
    NoteKeyFilters,
    RequestScopedFilter,
    TitleFilter,
    UserKeyFilters,
)
from tests.parameters.utils import coded


def _bare_selector() -> Any:
    """A placeholder ``selector`` — shape_queryset never calls it."""
    return None


class TestNoShapingDeclared:
    def test_returns_the_queryset_unchanged(self) -> None:
        spec = SelectorSpec(kind=SelectorKind.LIST, selector=_bare_selector)
        qs = Permission.objects.all()
        assert shape_queryset(qs, spec, {}, source_label="x") is qs


@pytest.mark.django_db
class TestSelectRelated:
    def test_applied_to_the_queryset(self) -> None:
        spec = SelectorSpec(
            kind=SelectorKind.LIST,
            selector=_bare_selector,
            select_related=["content_type"],
        )
        result = shape_queryset(Permission.objects.all(), spec, {}, source_label="x")
        assert result.query.select_related == {"content_type": {}}

    def test_composes_with_a_real_fetch(self) -> None:
        """Not just a flag on the query — it actually joins and resolves."""
        permission = Permission.objects.first()
        assert permission is not None
        spec = SelectorSpec(
            kind=SelectorKind.RETRIEVE,
            selector=_bare_selector,
            select_related=["content_type"],
        )
        result = shape_queryset(
            Permission.objects.filter(pk=permission.pk), spec, {}, source_label="x"
        )
        fetched = result.first()
        assert fetched is not None
        assert fetched.content_type == permission.content_type


@pytest.mark.django_db
class TestPrefetchRelated:
    def test_applied_to_the_queryset(self) -> None:
        group = Group.objects.create(name="editors")
        user = User.objects.create(username="ada")
        user.groups.add(group)

        spec = SelectorSpec(
            kind=SelectorKind.LIST,
            selector=_bare_selector,
            prefetch_related=["groups"],
        )
        result = shape_queryset(User.objects.all(), spec, {}, source_label="x")
        assert "groups" in result._prefetch_related_lookups
        assert list(result.get(pk=user.pk).groups.all()) == [group]


@pytest.mark.django_db
class TestAnnotations:
    def test_applied_to_the_queryset(self) -> None:
        content_type = ContentType.objects.first()
        assert content_type is not None
        spec = SelectorSpec(
            kind=SelectorKind.LIST,
            selector=_bare_selector,
            annotations={"perm_count": Count("permission")},
        )
        result = shape_queryset(ContentType.objects.all(), spec, {}, source_label="x")
        assert "perm_count" in result.query.annotation_select
        fetched = result.get(pk=content_type.pk)
        assert fetched.perm_count == Permission.objects.filter(content_type=content_type).count()


@pytest.mark.django_db
class TestExtendQueryset:
    def test_called_with_the_pool_and_the_queryset_so_far(self) -> None:
        captured: dict[str, Any] = {}

        def extend(*, queryset: QuerySet[Any], tenant: str) -> QuerySet[Any]:
            captured["queryset_type"] = type(queryset).__name__
            captured["tenant"] = tenant
            return queryset

        spec = SelectorSpec(kind=SelectorKind.LIST, selector=_bare_selector, extend_queryset=extend)
        shape_queryset(Permission.objects.all(), spec, {"tenant": "acme"}, source_label="x")
        assert captured == {"queryset_type": "QuerySet", "tenant": "acme"}

    def test_resolved_by_declare_to_receive(self) -> None:
        """A pool entry the callable did not declare is not forwarded."""

        def extend(*, queryset: QuerySet[Any]) -> QuerySet[Any]:
            return queryset.none()

        spec = SelectorSpec(kind=SelectorKind.LIST, selector=_bare_selector, extend_queryset=extend)
        result = shape_queryset(
            Permission.objects.all(), spec, {"unused": "ignored"}, source_label="x"
        )
        assert result.count() == 0

    def test_a_read_the_pool_lacks_is_the_callable_s_own_error(self) -> None:
        """A transport shaping rows itself bound no arguments, so no caller
        could have sent ``title``, read or not: asking for it as a missing
        argument would ask for a value nobody can send."""
        spec = SelectorSpec(
            kind=SelectorKind.LIST,
            selector=_bare_selector,
            extend_queryset=lambda *, queryset, title: queryset.filter(title=title),
            reads=Parameters.of(Parameter("title", "string")),
        )
        ada = make_user("ada")

        with pytest.raises(TypeError, match="title"):
            shape_queryset(Note.objects.all(), spec, base_pool(user=ada), source_label="x")

    def test_runs_after_declarative_shaping(self) -> None:
        """``extend_queryset`` sees the already select_related-shaped queryset."""
        observed: dict[str, Any] = {}

        def extend(*, queryset: QuerySet[Any]) -> QuerySet[Any]:
            observed["select_related"] = dict(queryset.query.select_related)
            return queryset

        spec = SelectorSpec(
            kind=SelectorKind.LIST,
            selector=_bare_selector,
            select_related=["content_type"],
            extend_queryset=extend,
        )
        shape_queryset(Permission.objects.all(), spec, {}, source_label="x")
        assert observed["select_related"] == {"content_type": {}}

    def test_its_return_is_the_shaped_queryset(self) -> None:
        def extend(*, queryset: QuerySet[Any]) -> QuerySet[Any]:
            return queryset.none()

        spec = SelectorSpec(kind=SelectorKind.LIST, selector=_bare_selector, extend_queryset=extend)
        result = shape_queryset(Permission.objects.all(), spec, {}, source_label="x")
        assert list(result) == []


@pytest.mark.django_db
class TestNonQuerysetReturn:
    def test_raises_when_declarative_shaping_is_configured(self) -> None:
        spec = SelectorSpec(
            kind=SelectorKind.LIST,
            selector=_bare_selector,
            select_related=["content_type"],
        )
        with pytest.raises(ImproperlyConfigured, match="not a Django QuerySet"):
            shape_queryset([{"id": 1}], spec, {}, source_label="ServiceSpec.output_selector_spec")

    def test_raises_when_extend_queryset_is_the_only_shaping_declared(self) -> None:
        """Covers the branch where extend_queryset alone triggers the guard."""

        def extend(*, queryset: QuerySet[Any]) -> QuerySet[Any]:
            return queryset

        spec = SelectorSpec(kind=SelectorKind.LIST, selector=_bare_selector, extend_queryset=extend)
        with pytest.raises(ImproperlyConfigured, match="not a Django QuerySet"):
            shape_queryset("not-a-queryset", spec, {}, source_label="SelectorSpec.selector")

    def test_error_names_the_source_label(self) -> None:
        spec = SelectorSpec(
            kind=SelectorKind.LIST,
            selector=_bare_selector,
            annotations={"n": Count("id")},
        )
        with pytest.raises(ImproperlyConfigured, match="SelectorSpec.selector"):
            shape_queryset(object(), spec, {}, source_label="SelectorSpec.selector")


def _titles(rows: Any) -> list[str]:
    return sorted(row.title for row in rows)


def _three_notes() -> Any:
    ada = make_user("ada")
    for title, archived in (("draft", False), ("final", True), ("other", False)):
        Note.objects.create(owner=ada, title=title, archived=archived)
    return ada


def _filtered(filter_set: Any, **kwargs: Any) -> SelectorSpec:
    return SelectorSpec(
        kind=SelectorKind.LIST,
        selector=_notes,
        permissions=[Unrestricted()],
        filter_set=filter_set,
        **kwargs,
    )


def _notes() -> QuerySet[Note]:
    return Note.objects.all()


@pytest.mark.django_db
class TestFilterSet:
    def test_the_filters_read_their_arguments_from_the_pool(self) -> None:
        _three_notes()
        spec = _filtered(NoteFilters)
        rows = shape_queryset(Note.objects.all(), spec, {"archived": False}, source_label="x")
        assert _titles(rows) == ["draft", "other"]

    def test_a_filter_not_sent_narrows_nothing(self) -> None:
        _three_notes()
        rows = shape_queryset(Note.objects.all(), _filtered(TitleFilter), {}, source_label="x")
        assert _titles(rows) == ["draft", "final", "other"]

    def test_a_pool_s_data_is_not_the_filters_data(self) -> None:
        # The filters read only the names they declare, never a mapping a
        # pool happens to carry under ``data``.
        _three_notes()
        pool = {"data": {"title": "draft"}}
        rows = shape_queryset(Note.objects.all(), _filtered(TitleFilter), pool, source_label="x")
        assert _titles(rows) == ["draft", "final", "other"]

    def test_a_value_the_filterset_refuses_is_refused_rather_than_ignored(self) -> None:
        # Read without ``is_valid()``, a non-strict FilterSet answers the
        # unfiltered rows for a value it cannot use.
        _three_notes()
        with pytest.raises(InvalidArguments) as caught:
            shape_queryset(
                Note.objects.all(), _filtered(NoteFilters), {"owner": "0"}, source_label="x"
            )
        assert caught.value.detail == {
            "owner": ["Select a valid choice. That choice is not one of the available choices."]
        }

    def test_a_value_the_filterset_refuses_keeps_django_s_code(self) -> None:
        # The ModelChoiceField's own code, which ``str`` would strip.
        _three_notes()
        with pytest.raises(InvalidArguments) as caught:
            shape_queryset(
                Note.objects.all(), _filtered(NoteFilters), {"owner": "0"}, source_label="x"
            )
        assert coded(caught.value.detail) == {
            "owner": [
                (
                    "Select a valid choice. That choice is not one of the available choices.",
                    "invalid_choice",
                )
            ]
        }

    def test_a_range_filter_s_refusal_is_keyed_by_the_filter_s_name(self) -> None:
        # Its arguments are ``pk_range_min`` and ``pk_range_max``, and
        # django-filter validates the two as one form field, called ``pk_range``.
        # Called directly, so the shape check is not there to answer first.
        with pytest.raises(InvalidArguments) as caught:
            shape_queryset(
                Note.objects.all(),
                _filtered(NoteFilters),
                {"pk_range_min": "x"},
                source_label="x",
            )
        assert list(caught.value.detail) == ["pk_range"]

    def test_the_request_reaches_a_filterset_that_takes_one(self) -> None:
        ada = _three_notes()
        Note.objects.create(owner=make_user("bob"), title="bob's")
        pool = {"mine": True, "request": SimpleNamespace(user=ada)}
        rows = shape_queryset(
            Note.objects.all(), _filtered(RequestScopedFilter), pool, source_label="x"
        )
        assert _titles(rows) == ["draft", "final", "other"]

    def test_a_filter_that_takes_no_request_is_not_handed_one(self) -> None:
        # Its constructor takes no ``request``, so handing it one would be a
        # ``TypeError``: it is handed only what it declares.
        class NoRequest(TitleFilter):
            def __init__(self, data: Any = None, queryset: Any = None) -> None:
                super().__init__(data=data, queryset=queryset)

        _three_notes()
        pool = {"title": "draft", "request": SimpleNamespace(user=None)}
        rows = shape_queryset(Note.objects.all(), _filtered(NoRequest), pool, source_label="x")
        assert _titles(rows) == ["draft"]

    def test_it_runs_after_extend_queryset(self) -> None:
        # ``extend_queryset`` sees the declaratively shaped rows and no filter,
        # so a slice or an ordering it applies is never made over filtered rows
        # it did not ask for.
        _three_notes()
        received: list[QuerySet[Any]] = []

        def extend(*, queryset: QuerySet[Any]) -> QuerySet[Any]:
            received.append(queryset)
            return queryset.filter(archived=False)

        spec = _filtered(TitleFilter, extend_queryset=extend)
        rows = shape_queryset(Note.objects.all(), spec, {"title": "draft"}, source_label="x")
        assert _titles(rows) == ["draft"]
        assert _titles(received[0]) == ["draft", "final", "other"]

    def test_it_alone_refuses_a_return_that_is_not_a_queryset(self) -> None:
        # The fifth condition of the nothing-to-shape guard: without it, a
        # list met by a filter would be returned unfiltered.
        with pytest.raises(ImproperlyConfigured, match="not a Django QuerySet"):
            shape_queryset([{"id": 1}], _filtered(TitleFilter), {}, source_label="x")


class _Recorded(NoteFilters):
    """``NoteFilters``, keeping the data it was bound with."""

    seen: ClassVar[list[Any]] = []

    def __init__(self, data: Any = None, queryset: Any = None, **kwargs: Any) -> None:
        type(self).seen.append(data)
        super().__init__(data=data, queryset=queryset, **kwargs)


@pytest.mark.django_db
class TestFilterData:
    def test_a_csv_filter_s_list_reaches_it_as_the_string_it_splits(self) -> None:
        # At django-filter's declared floor the CSV widget calls ``.split`` on
        # what it is handed, so a list would raise there. A multiple choice
        # reads a list as a list, and is handed one.
        _Recorded.seen.clear()
        pool = {"pks": [1, 2], "kinds": ["draft", "final"]}
        shape_queryset(Note.objects.all(), _filtered(_Recorded), pool, source_label="x")
        assert _Recorded.seen == [{"pks": "1,2", "kinds": ["draft", "final"]}]

    def test_a_csv_filter_sent_a_string_is_handed_it_unchanged(self) -> None:
        # A transport shaping rows itself may hand over the query string's own
        # spelling, which is already what the widget splits.
        _Recorded.seen.clear()
        shape_queryset(Note.objects.all(), _filtered(_Recorded), {"pks": "1,2"}, source_label="x")
        assert _Recorded.seen == [{"pks": "1,2"}]


@pytest.mark.django_db
class TestFilterSetThroughDispatch:
    def test_a_filter_argument_narrows_the_list(self) -> None:
        ada = _three_notes()
        result = dispatch(_filtered(NoteFilters), principal=ada, arguments={"kind": "final"})
        assert _titles(result.value) == ["final"]

    def test_a_filter_argument_of_the_wrong_shape_is_refused_by_the_shape_check(self) -> None:
        ada = _three_notes()
        with pytest.raises(InvalidArguments) as caught:
            dispatch(_filtered(NoteFilters), principal=ada, arguments={"kind": "neither"})
        assert caught.value.detail == {
            "kind": ["Select a valid choice. neither is not one of the available choices."]
        }

    def test_a_value_only_the_filterset_can_judge_is_refused_by_it(self) -> None:
        # The shape check accepts any string for a related row's key; the
        # FilterSet is the one that knows no such row exists, and its message,
        # not the shape check's, is the one that comes back.
        ada = _three_notes()
        with pytest.raises(InvalidArguments) as caught:
            dispatch(_filtered(NoteFilters), principal=ada, arguments={"owner": "0"})
        [message] = caught.value.detail["owner"]
        assert message == "Select a valid choice. That choice is not one of the available choices."
        # The shape check's own wording names the value it refused.
        assert "0 is not one of" not in message

    def test_a_retrieve_is_filtered_before_it_collapses_to_its_row(self) -> None:
        ada = _three_notes()
        spec = SelectorSpec(
            kind=SelectorKind.RETRIEVE,
            selector=_notes,
            permissions=[Unrestricted()],
            filter_set=TitleFilter,
            allow_none=True,
        )
        result = dispatch(spec, principal=ada, arguments={"title": "other"})
        assert result.value.title == "other"


@pytest.mark.django_db
def test_a_query_string_reaches_the_filters_through_the_http_transport() -> None:
    # What a FilterSet is mostly for: ``?archived=false`` read by the HTTP
    # transport against the spec's Parameters, then dispatched.
    ada = _three_notes()
    spec = _filtered(NoteFilters)
    request = RequestFactory().get("/notes", {"archived": "false", "kinds": ["draft", "final"]})
    arguments = request_arguments(request, spec.parameters())
    result = dispatch(spec, principal=ada, arguments=arguments)
    assert _titles(result.value) == ["draft"]


@pytest.mark.django_db
def test_a_csv_filter_takes_its_values_as_repeated_keys_over_http() -> None:
    ada = _three_notes()
    pks = sorted(Note.objects.values_list("pk", flat=True))
    spec = _filtered(NoteFilters)
    request = RequestFactory().get("/notes", {"pks": [str(pks[0]), str(pks[2])]})
    arguments = request_arguments(request, spec.parameters())
    result = dispatch(spec, principal=ada, arguments=arguments)
    assert _titles(result.value) == ["draft", "other"]


@pytest.mark.django_db(transaction=True)
async def test_adispatch_filters_an_async_selector_s_rows() -> None:
    async def notes() -> QuerySet[Note]:
        return Note.objects.all()

    ada = await sync_to_async(_three_notes)()
    spec = SelectorSpec(
        kind=SelectorKind.LIST,
        selector=notes,
        permissions=[Unrestricted()],
        filter_set=NoteFilters,
    )
    result = await adispatch(spec, principal=ada, arguments={"archived": True})
    assert await sync_to_async(_titles)(result.value) == ["final"]


@pytest.mark.django_db
def test_a_csv_filter_s_key_past_two_to_the_fifty_third_matches_its_own_row_over_http() -> None:
    # Read through ``float``, 2**53 + 1 became 2**53 and matched the
    # neighbour's row. A CSV filter's numbers are decimal strings, handed on
    # with every digit they were sent with.
    ada = make_user("ada")
    Note.objects.create(pk=2**53, owner=ada, title="neighbour")
    Note.objects.create(pk=2**53 + 1, owner=ada, title="mine")
    spec = _filtered(NoteFilters)
    request = RequestFactory().get("/notes", {"pks": [str(2**53 + 1)]})
    arguments = request_arguments(request, spec.parameters())
    result = dispatch(spec, principal=ada, arguments=arguments)
    assert _titles(result.value) == ["mine"]


_ABOVE = ("Ensure this value is less than or equal to 9223372036854775807.", "max_value")
_BELOW = ("Ensure this value is greater than or equal to -9223372036854775808.", "min_value")
_PAST_TOP = str(2**63)
_PAST_BOTTOM = str(-(2**63) - 1)


class _Shelved(django_filters.FilterSet):
    """A filter on a relation over two columns, beside one on a plain column."""

    shelf = django_filters.NumberFilter(field_name="shelf")
    title = django_filters.CharFilter()


def _shelved() -> SelectorSpec:
    return SelectorSpec(
        kind=SelectorKind.LIST,
        selector=Placement.objects.all,
        permissions=[Unrestricted()],
        filter_set=_Shelved,
    )


def _outcome(call: Any) -> Any:
    """What ``call`` returns, or the type and words of what it raises."""
    try:
        return call()
    except Exception as error:
        return (type(error), str(error))


@pytest.mark.django_db
class TestAFilterValuePastItsColumn:
    """A number no integer column can hold, sent to a filter on one.

    Refused at the argument that carried it, in the words and with the code of
    Django's own range validators, rather than handed to the driver, which
    raises ``OverflowError``: for ``in`` and ``range`` on every Django, and
    for every lookup on 4.2's SQLite, which states no range. Each value sits
    far inside the 1e50 bound the shape check and django-filter hold a number
    filter to, so the column's range is the one that answers.
    """

    @pytest.mark.parametrize(
        ("filter_set", "arguments", "detail"),
        [
            pytest.param(NoteKeyFilters, {"pk": _PAST_TOP}, {"pk": [_ABOVE]}, id="exact"),
            pytest.param(NoteFilters, {"min_pk": _PAST_TOP}, {"min_pk": [_ABOVE]}, id="gte"),
            pytest.param(
                NoteFilters,
                {"pks": ["1", _PAST_TOP, _PAST_BOTTOM]},
                {"pks": {1: [_ABOVE], 2: [_BELOW]}},
                id="in",
            ),
            pytest.param(
                NoteFilters,
                {"pk_between": ["1", _PAST_TOP]},
                {"pk_between": {1: [_ABOVE]}},
                id="csv-range",
            ),
            pytest.param(
                NoteFilters,
                {"pk_range_min": _PAST_BOTTOM, "pk_range_max": _PAST_TOP},
                {"pk_range_min": [_BELOW], "pk_range_max": [_ABOVE]},
                id="range",
            ),
            pytest.param(
                NoteFilters,
                {"pk_range_max": _PAST_TOP},
                {"pk_range_max": [_ABOVE]},
                id="range-top-alone",
            ),
            pytest.param(
                NoteKeyFilters,
                {"owner_key": _PAST_TOP},
                {"owner_key": [_ABOVE]},
                id="foreign-key",
            ),
            pytest.param(
                NoteKeyFilters,
                {"owner_min": _PAST_BOTTOM},
                {"owner_min": [_BELOW]},
                id="through-a-relation",
            ),
        ],
    )
    def test_it_is_refused_at_the_argument_that_sent_it(
        self, filter_set: Any, arguments: dict[str, Any], detail: dict[str, Any]
    ) -> None:
        ada = _three_notes()
        with pytest.raises(InvalidArguments) as caught:
            # Read, because the rows are a queryset until something does.
            list(dispatch(_filtered(filter_set), principal=ada, arguments=arguments).value)
        assert coded(caught.value.detail) == detail

    def test_the_keys_at_either_end_of_the_column_s_range_are_filtered_on(self) -> None:
        ada = _three_notes()
        ends = [str(2**63 - 1), str(-(2**63))]
        spec = _filtered(NoteFilters)
        assert list(dispatch(spec, principal=ada, arguments={"pks": ends}).value) == []
        arguments = {"pk_range_min": ends[1], "pk_range_max": ends[0]}
        rows = dispatch(spec, principal=ada, arguments=arguments).value
        assert _titles(rows) == ["draft", "final", "other"]

    def test_a_lookup_reading_the_value_as_text_is_left_to_it(self) -> None:
        # ``contains`` matches the column's digits and never converts the
        # value, so no integer is too large for it.
        ada = _three_notes()
        rows = dispatch(
            _filtered(NoteKeyFilters), principal=ada, arguments={"pk_digits": _PAST_TOP}
        )
        assert list(rows.value) == []

    def test_a_filter_with_a_method_is_left_to_its_method(self) -> None:
        # The method decides what the value means; this one reads a key no
        # note can have as every note.
        ada = _three_notes()
        rows = dispatch(
            _filtered(NoteKeyFilters), principal=ada, arguments={"pk_or_any": _PAST_TOP}
        )
        assert _titles(rows.value) == ["draft", "final", "other"]

    def test_a_related_row_is_matched_as_its_key(self) -> None:
        # A model choice filter's value is the row, which no integer column
        # reads as a number: the lookup reads it as the row's own key.
        ada = _three_notes()
        rows = dispatch(_filtered(NoteFilters), principal=ada, arguments={"owner": str(ada.pk)})
        assert _titles(rows.value) == ["draft", "final", "other"]

    def test_a_choice_filter_s_null_choice_is_left_to_it(self) -> None:
        # ``null`` is no number, and the filter reads it as ``isnull``.
        # Called directly, since the shape check offers only the choices.
        class Levels(django_filters.FilterSet):
            level = django_filters.ChoiceFilter(
                field_name="pk", choices=[(1, "One")], null_label="None"
            )

        _three_notes()
        rows = shape_queryset(
            Note.objects.all(), _filtered(Levels), {"level": "null"}, source_label="x"
        )
        assert list(rows) == []

    def test_a_transform_on_the_filter_s_path_is_left_to_the_lookup(self) -> None:
        # ``year`` is no column, so there is no column's range to hold it to.
        ada = _three_notes()
        arguments = {"joined_in": str(ada.date_joined.year)}
        rows = dispatch(_filtered(NoteKeyFilters), principal=ada, arguments=arguments)
        assert _titles(rows.value) == ["draft", "final", "other"]

    def test_a_filter_on_an_annotation_is_left_to_the_database(self) -> None:
        class ByLength(django_filters.FilterSet):
            title_length = django_filters.NumberFilter()

        ada = _three_notes()
        spec = _filtered(ByLength, annotations={"title_length": Length("title")})
        rows = dispatch(spec, principal=ada, arguments={"title_length": "5"})
        assert _titles(rows.value) == ["draft", "final", "other"]

    def test_a_relation_over_several_columns_leaves_a_call_sending_nothing_alone(self) -> None:
        # A FilterSet declaring a filter on it is asked about every filter it
        # declares, on every call: a relation comparing two columns with a
        # value has no one column's range, and must not raise for asking.
        Placement.objects.create(title="t", shelf_row=5, shelf_position=1)
        rows = shape_queryset(Placement.objects.all(), _shelved(), {}, source_label="x")
        assert [row.title for row in rows] == ["t"]

    def test_a_number_sent_to_a_relation_over_several_columns_is_the_database_s(self) -> None:
        # Answered as the FilterSet alone answers it, which is Django's to
        # decide and differs by version: so the oracle is django-filter's own.
        Placement.objects.create(title="t", shelf_row=5, shelf_position=1)
        queryset = Placement.objects.all()
        expected = _outcome(lambda: [row.title for row in _Shelved({"shelf": "5"}, queryset).qs])
        answered = _outcome(
            lambda: [
                row.title
                for row in shape_queryset(queryset, _shelved(), {"shelf": "5"}, source_label="x")
            ]
        )
        assert answered == expected

    @pytest.mark.skipif(
        django.VERSION < (4, 2, 2),
        reason="Django fixed a DecimalField query past max_digits in 4.2.2",
    )
    def test_a_decimal_column_takes_a_number_past_any_integer_s(self) -> None:
        # The 1e50 bound is the only one a number filter on a decimal or float
        # column has: neither holds an integer column's range.
        class Prices(django_filters.FilterSet):
            max_price = django_filters.NumberFilter(field_name="price", lookup_expr="lte")

        ada = make_user("ada")
        Book.objects.create(author=BookAuthor.objects.create(name="Ada"), title="t", price=1)
        spec = SelectorSpec(
            kind=SelectorKind.LIST,
            selector=Book.objects.all,
            permissions=[Unrestricted()],
            filter_set=Prices,
        )
        rows = dispatch(spec, principal=ada, arguments={"max_price": _PAST_TOP}).value
        assert [book.title for book in rows] == ["t"]

    def test_an_object_that_is_no_filterset_is_left_to_the_database(self) -> None:
        # It reads its own data, so there is no bound form to read values off.
        class Duck:
            base_filters: ClassVar[dict[str, Any]] = {"pk": django_filters.NumberFilter()}

            def __init__(self, data: Any = None, queryset: Any = None) -> None:
                self.qs = queryset

            def is_valid(self) -> bool:
                return True

        ada = _three_notes()
        rows = dispatch(_filtered(Duck), principal=ada, arguments={"pk": _PAST_TOP})
        assert _titles(rows.value) == ["draft", "final", "other"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("filter_set", "arguments", "detail"),
    [
        pytest.param(NoteKeyFilters, {"pk": _PAST_TOP}, {"pk": [_ABOVE]}, id="exact"),
        pytest.param(NoteFilters, {"pks": [_PAST_TOP]}, {"pks": {0: [_ABOVE]}}, id="in"),
        pytest.param(
            NoteFilters,
            {"pk_range_min": "1", "pk_range_max": _PAST_TOP},
            {"pk_range_max": [_ABOVE]},
            id="range",
        ),
        pytest.param(NoteFilters, {"min_pk": _PAST_BOTTOM}, {"min_pk": [_BELOW]}, id="gte"),
    ],
)
async def test_adispatch_refuses_a_filter_value_past_its_column(
    filter_set: Any, arguments: dict[str, Any], detail: dict[str, Any]
) -> None:
    async def notes() -> QuerySet[Note]:
        return Note.objects.all()

    ada = await sync_to_async(_three_notes)()
    spec = SelectorSpec(
        kind=SelectorKind.LIST,
        selector=notes,
        permissions=[Unrestricted()],
        filter_set=filter_set,
    )
    with pytest.raises(InvalidArguments) as caught:
        result = await adispatch(spec, principal=ada, arguments=arguments)
        await sync_to_async(list)(result.value)
    assert coded(caught.value.detail) == detail


def _users_filtered(filter_set: Any) -> SelectorSpec:
    return SelectorSpec(
        kind=SelectorKind.LIST,
        selector=User.objects.all,
        permissions=[Unrestricted()],
        filter_set=filter_set,
    )


@pytest.mark.django_db
class TestAKeyReachedThroughAnyRelation:
    """A many-to-many and a reverse foreign key compare the related row's key.

    So the number is held to that key's column, as a foreign key's is: past
    it, the driver raises ``OverflowError`` on every Django version.
    """

    @pytest.mark.parametrize(
        ("arguments", "detail"),
        [
            pytest.param({"group_key": _PAST_TOP}, {"group_key": [_ABOVE]}, id="many-to-many"),
            pytest.param({"note_key": _PAST_BOTTOM}, {"note_key": [_BELOW]}, id="reverse"),
            pytest.param(
                {"note_keys": ["1", _PAST_TOP]}, {"note_keys": {1: [_ABOVE]}}, id="reverse-in"
            ),
        ],
    )
    def test_it_is_refused_at_the_argument_that_sent_it(
        self, arguments: dict[str, Any], detail: dict[str, Any]
    ) -> None:
        ada = make_user("ada")
        with pytest.raises(InvalidArguments) as caught:
            list(
                dispatch(_users_filtered(UserKeyFilters), principal=ada, arguments=arguments).value
            )
        assert coded(caught.value.detail) == detail

    def test_a_key_inside_the_range_is_matched_through_either(self) -> None:
        ada = _three_notes()
        group = Group.objects.create(name="staff")
        ada.groups.add(group)
        make_user("bob")
        note = Note.objects.filter(owner=ada).first()
        spec = _users_filtered(UserKeyFilters)
        for arguments in ({"group_key": str(group.pk)}, {"note_key": str(note.pk)}):
            rows = dispatch(spec, principal=ada, arguments=arguments).value
            assert [user.username for user in rows] == ["ada"]


_NO_CHOICE = (
    "Select a valid choice. That choice is not one of the available choices.",
    "invalid_choice",
)


def _no_choice_in_list(key: str) -> tuple[str, str]:
    return (f"Select a valid choice. {key} is not one of the available choices.", "invalid_choice")


@pytest.mark.django_db
@pytest.mark.usefixtures("unstated_ranges")
class TestARelatedRowsKeyPastItsColumn:
    """A model choice filter's key past the range of the column its rows are matched on.

    Its form field matches the key with a query before the FilterSet has
    cleaned anything, which handed the key to the driver: ``OverflowError``
    for a list on every Django version, and for one key where the backend
    states no range, as Django 4.2's SQLite does. No row holds such a key, so
    it is no choice, refused in the form field's own words.
    """

    @pytest.mark.parametrize(
        ("arguments", "detail"),
        [
            pytest.param({"group": _PAST_TOP}, {"group": [_NO_CHOICE]}, id="one"),
            pytest.param(
                {"groups": ["1", _PAST_BOTTOM]},
                {"groups": [_no_choice_in_list(_PAST_BOTTOM)]},
                id="a-list",
            ),
        ],
    )
    def test_it_is_no_choice(self, arguments: dict[str, Any], detail: dict[str, Any]) -> None:
        ada = make_user("ada")
        with pytest.raises(InvalidArguments) as caught:
            list(
                dispatch(_users_filtered(UserKeyFilters), principal=ada, arguments=arguments).value
            )
        assert coded(caught.value.detail) == detail

    def test_it_is_refused_beside_the_filterset_s_own_refusals(self) -> None:
        ada = make_user("ada")
        arguments = {"groups": [_PAST_TOP], "note_key": "x"}
        with pytest.raises(InvalidArguments) as caught:
            shape_queryset(
                User.objects.all(), _users_filtered(UserKeyFilters), arguments, source_label="x"
            )
        assert coded(caught.value.detail) == {
            "groups": [_no_choice_in_list(_PAST_TOP)],
            "note_key": [("Enter a number.", "invalid")],
        }
        assert ada.pk

    def test_a_key_inside_the_range_is_matched(self) -> None:
        ada = make_user("ada")
        group = Group.objects.create(name="staff")
        ada.groups.add(group)
        make_user("bob")
        spec = _users_filtered(UserKeyFilters)
        for arguments in ({"group": str(group.pk)}, {"groups": [str(group.pk)]}):
            rows = dispatch(spec, principal=ada, arguments=arguments).value
            assert [user.username for user in rows] == ["ada"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("unstated_ranges")
@pytest.mark.parametrize(
    ("arguments", "detail"),
    [
        pytest.param({"group": _PAST_TOP}, {"group": [_NO_CHOICE]}, id="one"),
        pytest.param(
            {"groups": [_PAST_TOP]}, {"groups": [_no_choice_in_list(_PAST_TOP)]}, id="a-list"
        ),
    ],
)
async def test_adispatch_refuses_a_related_row_s_key_past_its_column(
    arguments: dict[str, Any], detail: dict[str, Any]
) -> None:
    async def users() -> QuerySet[User]:
        return User.objects.all()

    ada = await sync_to_async(make_user)("ada")
    spec = SelectorSpec(
        kind=SelectorKind.LIST,
        selector=users,
        permissions=[Unrestricted()],
        filter_set=UserKeyFilters,
    )
    with pytest.raises(InvalidArguments) as caught:
        result = await adispatch(spec, principal=ada, arguments=arguments)
        await sync_to_async(list)(result.value)
    assert coded(caught.value.detail) == detail


def _editions() -> QuerySet[Edition]:
    return Edition.objects.all()


def _two_editions() -> Any:
    book = Book.objects.create(author=BookAuthor.objects.create(name="Ada"), title="t", price=1)
    for number in (1, 2):
        Edition.objects.create(book=book, number=number)
    return make_user("ada")


def _numbers(rows: Any) -> list[int]:
    return sorted(edition.number for edition in rows)


_UNDER_ZERO = "-1"


@pytest.mark.django_db
class TestANumberInsideSixtyFourBitsIsTheDatabases:
    """A filter value a signed 64-bit integer holds is answered, whatever the column's type states.

    A positive column states no negative number on Django 5.0 and later, and
    none at all on 4.2's SQLite; ``-1`` is a value the driver binds either way,
    and ``gte=-1`` means every row. Each case runs with the range the backend
    states and with none, so it has one answer on every version.
    """

    @pytest.fixture(params=["stated", "unstated"])
    def ranges(self, request: pytest.FixtureRequest) -> None:
        if request.param == "unstated":
            request.getfixturevalue("unstated_ranges")

    @pytest.mark.usefixtures("ranges")
    @pytest.mark.parametrize(
        ("arguments", "numbers"),
        [
            pytest.param({"number": _UNDER_ZERO}, [], id="exact"),
            pytest.param({"number_min": _UNDER_ZERO}, [1, 2], id="gte"),
            pytest.param({"numbers": [_UNDER_ZERO, "2"]}, [2], id="in"),
            pytest.param(
                {"number_range_min": _UNDER_ZERO, "number_range_max": "1"}, [1], id="range"
            ),
        ],
    )
    def test_it_is_answered(self, arguments: dict[str, Any], numbers: list[int]) -> None:
        ada = _two_editions()
        spec = SelectorSpec(
            kind=SelectorKind.LIST,
            selector=_editions,
            permissions=[Unrestricted()],
            filter_set=EditionNumberFilters,
        )
        assert _numbers(dispatch(spec, principal=ada, arguments=arguments).value) == numbers

    @pytest.mark.usefixtures("ranges")
    @pytest.mark.parametrize(
        ("arguments", "detail"),
        [
            pytest.param({"number": _PAST_TOP}, {"number": [_ABOVE]}, id="above"),
            pytest.param({"number_min": _PAST_BOTTOM}, {"number_min": [_BELOW]}, id="below"),
        ],
    )
    def test_past_sixty_four_bits_it_is_refused_in_those_bits_words(
        self, arguments: dict[str, Any], detail: dict[str, Any]
    ) -> None:
        ada = _two_editions()
        spec = SelectorSpec(
            kind=SelectorKind.LIST,
            selector=_editions,
            permissions=[Unrestricted()],
            filter_set=EditionNumberFilters,
        )
        with pytest.raises(InvalidArguments) as caught:
            list(dispatch(spec, principal=ada, arguments=arguments).value)
        assert coded(caught.value.detail) == detail
