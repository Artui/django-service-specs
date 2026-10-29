"""``flat_arguments``: a query string or a form's fields read by the declaration, uncoerced.

Every source here is Django's own ``QueryDict``, parsed from the query string a
browser sends, so what is read back is what a real client's request carries;
one test hands in a bare ``MultiValueDict``, the type the signature names.
What comes back is strings and lists of strings: where a docstring claims a
refusal, the test runs the value through ``coerce_flat`` as a transport does,
and asserts the refusal it answers with.

Called through the package root, which is where a transport reads it.
"""

from __future__ import annotations

from typing import Any

import django_filters
import pytest
from django.http import QueryDict
from django.test import override_settings
from django.utils.datastructures import MultiValueDict

import django_service_specs
from django_service_specs.adapters.filters.filter_set_parameters import filter_set_parameters
from django_service_specs.parameters.coerce_flat import coerce_flat
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.parameters import Parameter, Parameters

NESTED = "This argument has nested parameters, which a flat transport cannot send."
WHOLE = "Enter a whole number."
TOO_MANY = "Ensure this field has no more than %s elements."

FLAT = Parameters.of(
    Parameter("pk", "integer"),
    Parameter("count", "integer"),
    Parameter("active", "boolean"),
    Parameter("title", "string"),
    Parameter("ids", "array", items="integer"),
    Parameter("words", "array", items="string"),
    Parameter("tags", "array"),
)
BOOK = Parameters.of(Parameter("title", "string", required=True))
BLANKS = Parameters.of(
    Parameter("since", "string", format="date"),
    Parameter("price", "string", format="decimal"),
    Parameter("status", "string", choices=("draft", "live")),
    Parameter("shelf", "string", choices=("", "top")),
    Parameter("labels", "array", items="string", choices=("a", "b")),
)
CSV = Parameters.of(
    Parameter("pks", "array", items="number"),
    Parameter("ids", "array", items="integer"),
    Parameter("flags", "array", items="boolean"),
    Parameter("words", "array", items="string"),
    Parameter("tags", "array"),
    Parameter("books", "array", items=BOOK),
    # An ordering, as django-filter's OrderingFilter offers it: no choice
    # holds a comma, so a comma can only be separating two of them.
    Parameter("o", "array", items="string", choices=("title", "-title", "pk", "-pk")),
    # Choices that hold a comma, so a comma may be part of one.
    Parameter("places", "array", items="string", choices=("Paris, France", "Paris")),
    # Choices with no element type: whatever an element is, it is not read as
    # a string the declaration promised, so it is taken whole.
    Parameter("marks", "array", choices=("a", "b")),
)
DECIMAL_PKS = Parameters.of(Parameter("pks", "array", items="string", format="decimal"))


class _Ordered(django_filters.FilterSet):
    o = django_filters.OrderingFilter(fields=["title", "pk"])


def read(query: str, parameters: Parameters = FLAT) -> dict[str, Any]:
    return django_service_specs.flat_arguments(parameters, QueryDict(query))


def refusal(query: str, parameters: Parameters) -> dict[Any, Any]:
    """What ``coerce_flat`` refuses in what was read, as a transport calls the two."""
    with pytest.raises(InvalidArguments) as caught:
        coerce_flat(parameters, read(query, parameters))
    return caught.value.detail


class TestRepeatedKeys:
    def test_a_scalar_takes_the_last_of_repeated_values(self) -> None:
        # QueryDict's own reading of a repeated key, so a query string built by
        # appending reads as the client's last word rather than its first.
        assert read("count=1&count=2&title=a&title=b") == {"count": "2", "title": "b"}

    def test_an_array_takes_every_value(self) -> None:
        assert read("ids=1&ids=2&ids=3") == {"ids": ["1", "2", "3"]}

    def test_a_single_value_for_an_array_is_a_one_element_list(self) -> None:
        assert read("ids=7") == {"ids": ["7"]}

    def test_a_value_is_handed_on_as_the_string_it_arrived_as(self) -> None:
        # Coercing is ``coerce_flat``'s, after the transport has merged its
        # route: nothing is parsed, so nothing is refused here.
        assert read("count=many&active=maybe&ids=x") == {
            "count": "many",
            "active": "maybe",
            "ids": ["x"],
        }

    def test_an_undeclared_key_passes_through_for_the_closed_set_to_refuse(self) -> None:
        # Left to check_arguments, under the caller's policy; the blank one is
        # kept too, since a blank only means "absent" for a declared type.
        assert read("colour=red&shade=") == {"colour": "red", "shade": ""}

    def test_a_multi_value_dict_is_read_as_a_query_dict_is(self) -> None:
        # The type the signature names, which a form's fields and a parsed
        # body's are as well as a query string's.
        source = MultiValueDict({"count": ["1", "2"], "ids": ["1,2", "3"], "title": [""]})
        assert django_service_specs.flat_arguments(FLAT, source) == {
            "count": "2",
            "ids": ["1", "2", "3"],
            "title": "",
        }

    def test_the_csrf_token_is_never_an_argument(self) -> None:
        assert read("csrfmiddlewaretoken=t0k3n&count=2") == {"count": "2"}


class TestCommaSeparatedArrays:
    """``?pks=1,2``: the spelling django-filter's CSV filters advertise.

    Splitting is the element type's to allow. A number, an integer and a
    boolean can never hold a comma, so the split is unambiguous; a string
    can, so a string array (declared or not) takes its value whole, unless
    its choices hold no comma, when a value holding one can only be several
    choices. ``_splits`` names the test holding each condition.
    """

    @pytest.mark.parametrize(
        ("query", "expected"),
        [
            ("pks=1,2.5", {"pks": ["1", "2.5"]}),
            ("ids=1,2,3", {"ids": ["1", "2", "3"]}),
            ("flags=true,0,False", {"flags": ["true", "0", "False"]}),
            # A boolean is the type that cares: " true" is no spelling of one.
            ("flags=true, false ,1", {"flags": ["true", "false", "1"]}),
            ("ids=1&ids=2", {"ids": ["1", "2"]}),
            ("ids=1,2&ids=3&ids=4,5", {"ids": ["1", "2", "3", "4", "5"]}),
            # ``?o=title,-pk``: the spelling django-filter's OrderingFilter
            # takes. No choice holds a comma, so a value holding one is several
            # choices.
            ("o=title,-pk&o=pk", {"o": ["title", "-pk", "pk"]}),
        ],
        ids=[
            "number",
            "integer",
            "boolean",
            "space-around-a-part-trimmed",
            "repeated-keys",
            "repeated-keys-and-commas",
            "string-whose-choices-hold-no-comma",
        ],
    )
    def test_an_array_reads_a_comma_separated_value_as_its_elements(
        self, query: str, expected: dict[str, Any]
    ) -> None:
        assert read(query, CSV) == expected

    def test_a_decimal_array_reads_a_comma_separated_value_as_its_elements_exactly(self) -> None:
        # A decimal never holds a comma, so ``?pks=1,2`` splits as a number's
        # does, and each part stays the string it spells, digits and all.
        fraction = "0.1234567890123456789012345678901234567891"
        query = f"pks=1,{fraction}, 3 &pks=4"
        assert read(query, DECIMAL_PKS) == {"pks": ["1", fraction, "3", "4"]}

    def test_blank_elements_of_a_decimal_array_are_dropped(self) -> None:
        # No decimal is blank, so a blank element is absent, as a number's is.
        assert read("pks=&pks=1", DECIMAL_PKS) == {"pks": ["1"]}
        assert read("pks=", DECIMAL_PKS) == {}

    @pytest.mark.parametrize(
        ("query", "expected"),
        [
            # A comma is part of a string; the whole value is the element.
            ("words=a,b&words=c", {"words": ["a,b", "c"]}),
            # One choice holds a comma, so the whole value may be that choice.
            ("places=Paris, France&places=Paris", {"places": ["Paris, France", "Paris"]}),
            ("marks=a,b", {"marks": ["a,b"]}),
            ("tags=a,b", {"tags": ["a,b"]}),
        ],
        ids=[
            "string",
            "string-whose-choices-hold-a-comma",
            "no-declared-element-with-choices",
            "no-declared-element",
        ],
    )
    def test_an_array_that_may_hold_a_comma_is_not_split(
        self, query: str, expected: dict[str, Any]
    ) -> None:
        assert read(query, CSV) == expected

    @pytest.mark.parametrize("query", ["o=title,-pk", "o=title&o=-pk"])
    def test_an_ordering_filter_s_two_fields_read_as_two_elements(self, query: str) -> None:
        # The declaration django-filter's own OrderingFilter produces, rather
        # than one written to look like it.
        assert read(query, filter_set_parameters(_Ordered)) == {"o": ["title", "-pk"]}

    def test_an_array_of_rows_is_not_split_and_stays_refused_by_name(self) -> None:
        assert read("books=a,b", CSV) == {"books": ["a,b"]}
        assert refusal("books=a,b", CSV) == {"books": [NESTED]}

    @pytest.mark.parametrize(
        ("query", "parts", "index"),
        [
            ("ids=1,,3", ["1", "", "3"], 1),
            ("ids=1,", ["1", ""], 1),
            ("ids=,1", ["", "1"], 0),
            ("ids=1, ,3", ["1", "", "3"], 1),
        ],
    )
    def test_an_empty_part_is_kept_for_coerce_flat_to_refuse_at_its_index(
        self, query: str, parts: list[str], index: int
    ) -> None:
        # Not dropped as a blank element is: a stray comma is a mistake in the
        # value, and the reader's wording for one is the element's own.
        assert read(query, CSV) == {"ids": parts}
        assert refusal(query, CSV) == {"ids": {index: [WHOLE]}}

    def test_the_refused_part_is_named_by_its_index_in_the_whole_list(self) -> None:
        assert read("ids=1&ids=2,,3", CSV) == {"ids": ["1", "2", "", "3"]}
        assert refusal("ids=1&ids=2,,3", CSV) == {"ids": {2: [WHOLE]}}

    def test_a_blank_value_is_still_absent(self) -> None:
        assert read("ids=&ids=1,2", CSV) == {"ids": ["1", "2"]}
        assert read("ids=", CSV) == {}


class TestBlanks:
    def test_a_blank_value_for_a_type_that_is_not_a_string_is_absent(self) -> None:
        # Kept, ``""`` reaches coerce_flat as an integer and is refused as
        # "Enter a whole number.", which is not what a left-blank field means.
        assert read("count=&active=&pk=4") == {"pk": "4"}

    def test_a_blank_string_is_kept(self) -> None:
        # A string's blank is a value, the empty string, and dropping it would
        # make it unsendable.
        assert read("title=") == {"title": ""}

    def test_a_blank_untyped_read_is_kept(self) -> None:
        # An untyped read is handed what was sent, so ``?pk=`` reaches it as
        # the empty string, as a string's does, rather than being dropped.
        assert read("pk=", Parameters.of(Parameter("pk", "any"))) == {"pk": ""}

    def test_blank_elements_of_a_non_string_array_are_dropped(self) -> None:
        assert read("ids=1&ids=&ids=3") == {"ids": ["1", "3"]}

    def test_an_array_whose_every_element_is_blank_is_absent(self) -> None:
        # A multi-value input left blank: nothing was chosen, so nothing is
        # sent, and a required array reads as missing rather than as ``[]``.
        assert read("ids=&ids=") == {}

    def test_blank_elements_of_a_string_array_are_kept(self) -> None:
        assert read("words=a&words=") == {"words": ["a", ""]}

    def test_a_blank_date_is_absent(self) -> None:
        # A filter form's empty date input. Kept, it reached the shape check as
        # a malformed date, refusing a form that was only left blank.
        assert read("since=&price=", BLANKS) == {}

    def test_a_blank_the_choices_leave_out_is_absent(self) -> None:
        # An "any status" option whose value is blank: the shape check would
        # refuse it as no valid choice, and an array's choices constrain each
        # of its elements the same way.
        assert read("status=&labels=&labels=a", BLANKS) == {"labels": ["a"]}

    def test_a_blank_the_choices_name_is_kept(self) -> None:
        assert read("shelf=", BLANKS) == {"shelf": ""}

    def test_blank_elements_of_an_undeclared_element_type_are_kept(self) -> None:
        # coerce_flat reads an undeclared element as the string it arrived as,
        # so its blank is a string's blank.
        assert read("tags=&tags=x") == {"tags": ["", "x"]}


class TestArrayLength:
    """A flat array's commas never build past its bound, and the list stays over it."""

    def test_a_comma_list_past_the_default_maximum_is_refused_at_its_name(self) -> None:
        # The spelling that reaches round Django's DATA_UPLOAD_MAX_NUMBER_FIELDS:
        # one key, any number of values.
        query = "ids=" + ",".join(map(str, range(1001)))
        assert len(read(query, CSV)["ids"]) == 1001
        assert refusal(query, CSV) == {"ids": [TOO_MANY % 1000]}

    def test_a_comma_list_at_the_default_maximum_is_read(self) -> None:
        query = "ids=" + ",".join(map(str, range(1000)))
        assert read(query, CSV) == {"ids": [str(n) for n in range(1000)]}

    @override_settings(SERVICE_SPECS_MAX_ARRAY_LENGTH=3)
    @pytest.mark.parametrize(
        ("query", "handed_on"),
        [
            ("ids=1,2,3,4,5,6", ["1", "2", "3", "4,5,6"]),
            ("ids=1&ids=2&ids=3&ids=4&ids=5", ["1", "2", "3", "4"]),
            ("ids=1,2&ids=3,4,5&ids=6", ["1", "2", "3", "4,5"]),
            ("ids=1,2,3", ["1", "2", "3"]),
        ],
        ids=["one-value", "repeated-keys", "mixed", "at-the-bound"],
    )
    def test_a_flat_array_is_split_no_further_than_one_past_its_maximum(
        self, query: str, handed_on: list[str]
    ) -> None:
        # Invisible to every message, which is the length's either way: what is
        # held is the list built on the way, one element past the bound and no
        # more, so a value of a million commas is never split a million times.
        # One past rather than at it, or a list over the bound would be cut to
        # one that is accepted.
        assert read(query, CSV) == {"ids": handed_on}

    @override_settings(SERVICE_SPECS_MAX_ARRAY_LENGTH=None)
    def test_a_setting_of_none_splits_every_comma(self) -> None:
        assert read("ids=1,2,3,4", CSV) == {"ids": ["1", "2", "3", "4"]}

    @override_settings(SERVICE_SPECS_MAX_ARRAY_LENGTH=3)
    def test_a_declared_maximum_bounds_the_split_rather_than_the_default(self) -> None:
        wide = Parameters.of(Parameter("ids", "array", items="integer", max_length=5))
        assert read("ids=1,2,3,4,5", wide) == {"ids": ["1", "2", "3", "4", "5"]}
        assert read("ids=1,2,3,4,5,6", wide) == {"ids": ["1", "2", "3", "4", "5", "6"]}
        assert refusal("ids=1,2,3,4,5,6", wide) == {"ids": [TOO_MANY % 5]}
