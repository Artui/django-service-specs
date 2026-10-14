from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from django.utils import translation
from django.utils.translation import gettext_lazy

from django_service_specs.parameters.check_arguments import check_arguments
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.parameter import Parameter
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.schema.parameters_schema import parameters_schema
from django_service_specs.validation.unknown_arguments import UnknownArguments

PUBLISHER = Parameters.of(Parameter("name", "string", required=True))
BOOK = Parameters.of(
    Parameter("title", "string", required=True),
    Parameter("publisher", "object", fields=PUBLISHER),
    Parameter("extra", "object"),
)
AUTHOR = Parameters.of(
    Parameter("name", "string", required=True),
    Parameter("books", "array", items=BOOK),
    Parameter("flags", "object", fields=Parameters()),
    Parameter("meta", "object"),
)
"""Every kind of object the shape check meets: the top, rows, an object inside a
row, a declared-but-empty object, and a free-form one at two depths."""


def one(parameter: Parameter, **kwargs: Any) -> dict[str, Any]:
    """The schema of a single parameter, as it sits among its object's properties."""
    return parameters_schema(Parameters.of(parameter), **kwargs)["properties"][parameter.name]


def refused(parameters: Parameters, arguments: Any, **kwargs: Any) -> dict[Any, Any]:
    with pytest.raises(InvalidArguments) as caught:
        check_arguments(parameters, arguments, **kwargs)
    return caught.value.detail


def walk(schema: dict[str, Any]) -> list[dict[str, Any]]:
    """Every schema node - the root, each property, each array's items - however deep."""
    nodes = [schema]
    for prop in schema.get("properties", {}).values():
        nodes += walk(prop)
    if "items" in schema:
        nodes += walk(schema["items"])
    return nodes


class TestObjects:
    def test_an_empty_declaration_is_a_closed_object_with_no_properties(self) -> None:
        assert parameters_schema(Parameters()) == {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        }

    def test_properties_follow_declaration_order(self) -> None:
        schema = parameters_schema(
            Parameters.of(
                Parameter("b", "string"), Parameter("a", "string"), Parameter("c", "string")
            )
        )

        assert list(schema["properties"]) == ["b", "a", "c"]

    def test_required_lists_the_required_names_in_declaration_order(self) -> None:
        schema = parameters_schema(
            Parameters.of(
                Parameter("z", "string", required=True),
                Parameter("optional", "string"),
                Parameter("a", "integer", required=True),
            )
        )

        assert schema["required"] == ["z", "a"]

    def test_an_optional_parameter_is_not_required(self) -> None:
        # With nothing required the key is left out rather than stated empty.
        assert parameters_schema(Parameters.of(Parameter("title", "string"))) == {
            "type": "object",
            "properties": {"title": {"type": "string"}},
            "additionalProperties": False,
        }

    def test_a_required_parameter_with_a_default_is_not_required(self) -> None:
        # The shape check does not refuse its absence, since the Validator
        # supplies the default, so a schema listing it would refuse a call that runs.
        parameters = Parameters.of(
            Parameter("title", "string", required=True),
            Parameter("status", "string", required=True, default="draft"),
        )

        assert check_arguments(parameters, {"title": "Lathe"}) == {"title": "Lathe"}
        assert parameters_schema(parameters)["required"] == ["title"]


class TestTheClosedArgumentSet:
    def test_reject_closes_the_top_every_declared_object_and_every_row(self) -> None:
        closed_book = {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "publisher": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                    "additionalProperties": False,
                },
                "extra": {"type": "object"},
            },
            "required": ["title"],
            "additionalProperties": False,
        }

        assert parameters_schema(AUTHOR) == {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "books": {"type": "array", "items": closed_book, "maxItems": 1000},
                "flags": {"type": "object", "properties": {}, "additionalProperties": False},
                "meta": {"type": "object"},
            },
            "required": ["name"],
            "additionalProperties": False,
        }

    def test_ignore_closes_nothing_at_any_depth(self) -> None:
        schema = parameters_schema(AUTHOR, unknown_arguments=UnknownArguments.IGNORE)

        assert [node for node in walk(schema) if "additionalProperties" in node] == []
        # Still the same description otherwise: only the closing keyword went.
        assert schema["properties"]["books"]["items"]["required"] == ["title"]

    def test_the_schema_closes_exactly_where_the_shape_check_refuses_an_unknown_key(self) -> None:
        # One unknown key at every level, including inside both free-form
        # objects. The levels the shape check refuses it at are the levels the
        # schema closes, and none other.
        arguments = {
            "name": "Ursula",
            "x": 1,
            "books": [
                {"title": "Lathe", "x": 1, "publisher": {"name": "Ace", "x": 1}, "extra": {"x": 1}}
            ],
            "flags": {"x": 1},
            "meta": {"x": 1},
        }
        detail = refused(AUTHOR, arguments)

        def refused_at(tree: Any, path: tuple[Any, ...] = ()) -> set[tuple[Any, ...]]:
            found = {path} if "x" in tree else set()
            for key, value in tree.items():
                if isinstance(value, dict):
                    found |= refused_at(value, (*path, key))
            return found

        def closed_at(schema: dict[str, Any], path: tuple[Any, ...] = ()) -> set[tuple[Any, ...]]:
            found = {path} if schema.get("additionalProperties") is False else set()
            for name, prop in schema.get("properties", {}).items():
                found |= closed_at(prop, (*path, name))
            if "items" in schema:
                found |= closed_at(schema["items"], (*path, 0))
            return found

        assert (
            refused_at(detail)
            == closed_at(parameters_schema(AUTHOR))
            == {
                (),
                ("books", 0),
                ("books", 0, "publisher"),
                ("flags",),
            }
        )

    def test_the_policys_plain_value_is_accepted(self) -> None:
        # "reject" rather than "ignore": compared by identity without being
        # normalized, a plain "reject" would quietly describe the open set.
        assert parameters_schema(AUTHOR, unknown_arguments="reject") == parameters_schema(AUTHOR)
        assert parameters_schema(AUTHOR, unknown_arguments="ignore") == parameters_schema(
            AUTHOR, unknown_arguments=UnknownArguments.IGNORE
        )

    def test_a_value_that_is_neither_policy_raises(self) -> None:
        with pytest.raises(ValueError, match="'drop' is not a valid UnknownArguments"):
            parameters_schema(AUTHOR, unknown_arguments="drop")


class TestTypes:
    @pytest.mark.parametrize("json_type", ["string", "integer", "number", "boolean"])
    def test_a_scalar_states_its_type(self, json_type: str) -> None:
        assert one(Parameter("value", json_type)) == {"type": json_type}

    @pytest.mark.parametrize("fmt", ["decimal", "date-time", "date"])
    def test_a_format_is_stated_beside_its_string_type(self, fmt: str) -> None:
        assert one(Parameter("value", "string", format=fmt)) == {"type": "string", "format": fmt}

    def test_a_decimal_is_a_string_though_the_shape_check_also_accepts_a_number(self) -> None:
        # The documented convention, held here so it stays a decision rather
        # than drifting into one: the schema advertises the lossless form only.
        price = Parameter("price", "string", format="decimal")

        assert check_arguments(Parameters.of(price), {"price": 12.5}) == {"price": 12.5}
        assert one(price) == {"type": "string", "format": "decimal"}

    def test_an_object_with_no_fields_is_a_free_form_object(self) -> None:
        assert one(Parameter("meta", "object")) == {"type": "object"}

    def test_an_array_of_a_type_name_states_the_type_of_its_items(self) -> None:
        assert one(Parameter("ids", "array", items="integer")) == {
            "type": "array",
            "maxItems": 1000,
            "items": {"type": "integer"},
        }

    def test_an_array_of_rows_describes_each_row_as_an_object(self) -> None:
        assert one(Parameter("books", "array", items=PUBLISHER)) == {
            "type": "array",
            "maxItems": 1000,
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
                "additionalProperties": False,
            },
        }

    def test_an_array_with_no_items_accepts_any_element(self) -> None:
        assert one(Parameter("anything", "array")) == {
            "type": "array",
            "items": {},
            "maxItems": 1000,
        }


class TestNullable:
    def test_a_nullable_scalar_admits_null_by_its_type(self) -> None:
        assert one(Parameter("on", "string", format="date", nullable=True)) == {
            "type": ["string", "null"],
            "format": "date",
        }

    def test_a_nullable_object_admits_null_beside_its_properties(self) -> None:
        assert one(Parameter("publisher", "object", fields=PUBLISHER, nullable=True)) == {
            "type": ["object", "null"],
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
            "additionalProperties": False,
        }

    def test_a_nullable_free_form_object_and_array_admit_null(self) -> None:
        assert one(Parameter("meta", "object", nullable=True)) == {"type": ["object", "null"]}
        assert one(Parameter("ids", "array", items="integer", nullable=True)) == {
            "type": ["array", "null"],
            "maxItems": 1000,
            "items": {"type": "integer"},
        }

    def test_a_parameter_that_is_not_nullable_does_not_admit_null(self) -> None:
        assert one(Parameter("title", "string")) == {"type": "string"}


class TestChoices:
    def test_choices_are_an_enum_beside_the_type(self) -> None:
        assert one(Parameter("ordering", "string", choices=["title", "-title"])) == {
            "type": "string",
            "enum": ["title", "-title"],
        }

    def test_a_nullable_parameter_with_choices_adds_null_to_its_enum(self) -> None:
        status = Parameter("status", "string", choices=["draft", "published"], nullable=True)

        # The shape check lets null through before reading the choices.
        assert check_arguments(Parameters.of(status), {"status": None}) == {"status": None}
        assert one(status) == {"type": ["string", "null"], "enum": ["draft", "published", None]}

    def test_a_nullable_parameter_whose_choices_list_null_lists_it_once(self) -> None:
        status = Parameter("status", "string", choices=["draft", None], nullable=True)

        assert one(status) == {"type": ["string", "null"], "enum": ["draft", None]}

    def test_an_arrays_choices_constrain_each_item_and_not_the_array(self) -> None:
        assert one(Parameter("tags", "array", items="string", choices=["red", "blue"])) == {
            "type": "array",
            "maxItems": 1000,
            "items": {"type": "string", "enum": ["red", "blue"]},
        }

    def test_a_nullable_arrays_items_do_not_admit_null(self) -> None:
        tags = Parameter("tags", "array", items="string", choices=["red"], nullable=True)

        # Null is the array's to take, and an element's only where items_nullable says so.
        assert check_arguments(Parameters.of(tags), {"tags": None}) == {"tags": None}
        assert refused(Parameters.of(tags), {"tags": [None]}) == {
            "tags": {0: ["Expected a string."]}
        }
        assert one(tags) == {
            "type": ["array", "null"],
            "maxItems": 1000,
            "items": {"type": "string", "enum": ["red"]},
        }

    def test_a_nullable_element_admits_null_in_its_items_and_its_enum(self) -> None:
        ids = Parameter("ids", "array", items="integer", items_nullable=True, choices=[1, 2])

        # The shape check keeps a null element without reading the choices, so an
        # enum that did not list it would refuse a call that runs.
        assert check_arguments(Parameters.of(ids), {"ids": [1, None]}) == {"ids": [1, None]}
        assert one(ids) == {
            "type": "array",
            "maxItems": 1000,
            "items": {"type": ["integer", "null"], "enum": [1, 2, None]},
        }

    def test_a_nullable_elements_choices_that_list_null_list_it_once(self) -> None:
        ids = Parameter("ids", "array", items="integer", items_nullable=True, choices=[1, None])

        assert one(ids)["items"] == {"type": ["integer", "null"], "enum": [1, None]}

    def test_a_nullable_row_admits_null_beside_its_properties(self) -> None:
        publishers = Parameter("publishers", "array", items=PUBLISHER, items_nullable=True)

        assert one(publishers) == {
            "type": "array",
            "maxItems": 1000,
            "items": {
                "type": ["object", "null"],
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
                "additionalProperties": False,
            },
        }

    def test_an_untyped_arrays_choices_are_an_enum_with_no_type(self) -> None:
        assert one(Parameter("any", "array", choices=[1, "one"])) == {
            "type": "array",
            "maxItems": 1000,
            "items": {"enum": [1, "one"]},
        }

    def test_choices_json_cannot_carry_are_left_out_whole(self) -> None:
        # Listing only the values JSON can carry would claim the others are
        # refused, so the enum goes and the type stays.
        rate = Parameter("rate", "string", format="decimal", choices=["1.5", Decimal("2.5")])

        assert one(rate) == {"type": "string", "format": "decimal"}
        assert one(Parameter("rates", "array", choices=[Decimal("1")])) == {
            "type": "array",
            "maxItems": 1000,
            "items": {},
        }


class TestChoiceLabels:
    def test_labelled_choices_are_any_of_pairs_of_const_and_title(self) -> None:
        # ``anyOf`` rather than ``oneOf``: the entries are disjoint, so the two
        # admit the same values, and ``oneOf`` is the one keyword an OpenAI
        # strict schema and Gemini's both refuse.
        status = Parameter(
            "status",
            "string",
            choices=["draft", "live"],
            choice_labels={"draft": "Draft", "live": "Published"},
        )

        assert one(status) == {
            "type": "string",
            "anyOf": [
                {"const": "draft", "title": "Draft"},
                {"const": "live", "title": "Published"},
            ],
        }

    def test_labels_that_only_repeat_their_values_stay_an_enum(self) -> None:
        # A title restating its constant tells a reader nothing the enum does
        # not, so the schema a declaration had before it was labelled is kept.
        rank = Parameter("rank", "integer", choices=[1, 2], choice_labels={1: "1", 2: "2"})

        assert one(rank) == {"type": "integer", "enum": [1, 2]}

    def test_an_unlabelled_choice_is_a_const_with_no_title(self) -> None:
        status = Parameter(
            "status", "string", choices=["draft", "live"], choice_labels={"live": "Published"}
        )

        assert one(status)["anyOf"] == [{"const": "draft"}, {"const": "live", "title": "Published"}]

    def test_a_nullable_parameter_adds_an_untitled_null(self) -> None:
        # ``{"type": "null"}`` rather than ``{"const": null}``: Google's schema
        # transform drops a null ``const`` and leaves ``{}``, which matches
        # every value.
        status = Parameter(
            "status", "string", choices=["live"], choice_labels={"live": "On"}, nullable=True
        )

        assert check_arguments(Parameters.of(status), {"status": None}) == {"status": None}
        assert one(status) == {
            "type": ["string", "null"],
            "anyOf": [{"const": "live", "title": "On"}, {"type": "null"}],
        }

    def test_a_labelled_null_is_listed_once(self) -> None:
        status = Parameter(
            "status",
            "string",
            choices=["live", None],
            choice_labels={None: "Unset"},
            nullable=True,
        )

        assert one(status)["anyOf"] == [{"const": "live"}, {"type": "null", "title": "Unset"}]

    def test_a_choice_declared_twice_is_one_entry(self) -> None:
        # Listed once, so the entries stay disjoint and a reader meets each
        # value under one title. ``True``
        # is not ``1`` to JSON, although Python finds them equal, so pairs keep
        # the two labels apart where a mapping's keys would merge them.
        rank = Parameter(
            "rank", "integer", choices=[1, 1, True], choice_labels=[(1, "One"), (True, "Yes")]
        )

        assert one(rank)["anyOf"] == [{"const": 1, "title": "One"}, {"const": True, "title": "Yes"}]

    def test_an_arrays_labelled_choices_go_on_its_items(self) -> None:
        tags = Parameter(
            "tags",
            "array",
            items="string",
            items_nullable=True,
            choices=["red"],
            choice_labels={"red": "Red"},
        )

        assert one(tags) == {
            "type": "array",
            "maxItems": 1000,
            "items": {
                "type": ["string", "null"],
                "anyOf": [{"const": "red", "title": "Red"}, {"type": "null"}],
            },
        }

    def test_a_lazy_label_is_rendered_in_the_active_language(self) -> None:
        answer = Parameter(
            "answer", "boolean", choices=[True], choice_labels={True: gettext_lazy("Yes")}
        )
        with translation.override("fr"):
            title = one(answer)["anyOf"][0]["title"]

        assert type(title) is str
        assert title == "Oui"

    def test_labelled_choices_json_cannot_carry_are_left_out_whole(self) -> None:
        rate = Parameter(
            "rate",
            "string",
            format="decimal",
            choices=[Decimal("1")],
            choice_labels={Decimal("1"): "One"},
        )

        assert one(rate) == {"type": "string", "format": "decimal"}


class TestFiles:
    def test_a_file_states_no_type(self) -> None:
        # No JSON value is a file, so any JSON type stated here would be false;
        # what a multipart body carries, a JSON Schema has no keyword for.
        assert one(Parameter("notes", "file")) == {}

    def test_a_nullable_file_is_still_untyped(self) -> None:
        # An untyped node admits null already, so there is no type to widen.
        notes = Parameter("notes", "file", nullable=True, help="The minutes.")

        assert one(notes) == {"description": "The minutes."}

    def test_an_array_of_files_has_untyped_items(self) -> None:
        notes = Parameter("notes", "array", items="file", items_nullable=True)

        assert one(notes) == {"type": "array", "items": {}, "maxItems": 1000}

    def test_a_required_file_is_required(self) -> None:
        schema = parameters_schema(Parameters.of(Parameter("notes", "file", required=True)))

        assert schema["required"] == ["notes"]


class TestDefaults:
    @pytest.mark.parametrize(
        "default", ["draft", 0, 1.5, False, None, ["a", 1], {"key": [None, True]}]
    )
    def test_a_default_json_can_carry_is_stated(self, default: Any) -> None:
        assert one(Parameter("value", "string", default=default)) == {
            "type": "string",
            "default": default,
        }

    def test_a_parameter_with_no_default_states_none(self) -> None:
        assert one(Parameter("value", "string")) == {"type": "string"}

    @pytest.mark.parametrize(
        "default",
        [Decimal("9.99"), dt.date(2026, 1, 1), dt.datetime.now, [Decimal("1")], {1: "x"}],
    )
    def test_a_default_json_cannot_carry_is_left_out(self, default: Any) -> None:
        assert one(Parameter("value", "string", default=default)) == {"type": "string"}

    def test_a_default_is_placed_as_declared_not_copied(self) -> None:
        declared = ["red"]

        assert one(Parameter("tags", "array", default=declared))["default"] is declared

    def test_a_default_is_stated_at_every_depth(self) -> None:
        row = Parameters.of(Parameter("status", "string", default="draft"))

        assert one(Parameter("books", "array", items=row))["items"]["properties"] == {
            "status": {"type": "string", "default": "draft"}
        }


class TestHelp:
    def test_help_is_the_description(self) -> None:
        assert one(Parameter("search", "string", help="Part of the title.")) == {
            "type": "string",
            "description": "Part of the title.",
        }

    def test_a_lazy_help_is_rendered_in_the_active_language(self) -> None:
        with translation.override("fr"):
            description = one(
                Parameter("title", "string", help=gettext_lazy("This field is required."))
            )["description"]

        assert type(description) is str
        assert description == "Ce champ est obligatoire."


class TestNothingElse:
    def test_no_title_reference_schema_key_or_bound_at_any_depth(self) -> None:
        declared = Parameters.of(
            Parameter("books", "array", items=BOOK, nullable=True, help="The rows."),
            Parameter("status", "string", choices=["a"], default="a", required=True),
        )
        keys = {key for node in walk(parameters_schema(declared)) for key in node}

        assert keys.isdisjoint({"title", "$ref", "$defs", "$schema", "maxLength", "minimum"})

    def test_every_call_builds_a_new_schema(self) -> None:
        first = parameters_schema(AUTHOR)
        first["properties"]["books"]["items"]["properties"]["title"]["x-mine"] = True

        assert (
            "x-mine"
            not in parameters_schema(AUTHOR)["properties"]["books"]["items"]["properties"]["title"]
        )


def test_a_bound_is_stated_beside_the_type() -> None:
    price = Parameter("price", "string", format="decimal", minimum=-1e50, maximum=1e50)
    floor = Parameter("n", "integer", minimum=0, nullable=True)
    schema = parameters_schema(Parameters.of(price, floor))
    assert schema["properties"] == {
        "price": {"type": "string", "format": "decimal", "minimum": -1e50, "maximum": 1e50},
        "n": {"type": ["integer", "null"], "minimum": 0},
    }


def test_an_array_states_its_element_s_format_and_bounds_on_items_and_not_on_itself() -> None:
    # The shape check reads them on each element, so the array node carries
    # neither: stated there, a reader would take ``minimum`` for a count.
    pks = Parameter("pks", "array", items="string", format="decimal", minimum=-1e50, maximum=1e50)
    ids = Parameter("ids", "array", items="integer", minimum=1, max_length=5, items_nullable=True)
    assert one(pks) == {
        "type": "array",
        "items": {"type": "string", "format": "decimal", "minimum": -1e50, "maximum": 1e50},
        "maxItems": 1000,
    }
    assert one(ids) == {
        "type": "array",
        "items": {"type": ["integer", "null"], "minimum": 1},
        "maxItems": 5,
    }


# --- array length ------------------------------------------------------------------------------------


def test_an_array_states_the_maximum_in_force_when_none_is_declared() -> None:
    # The shape check refuses past it, so a client that does not learn it
    # sends a call that cannot run.
    schema = parameters_schema(Parameters.of(Parameter("ids", "array", items="integer")))
    assert schema["properties"]["ids"] == {
        "type": "array",
        "items": {"type": "integer"},
        "maxItems": 1000,
    }


@override_settings(SERVICE_SPECS_MAX_ARRAY_LENGTH=3)
def test_the_stated_default_follows_the_setting() -> None:
    schema = parameters_schema(Parameters.of(Parameter("ids", "array")))
    assert schema["properties"]["ids"] == {"type": "array", "items": {}, "maxItems": 3}


@override_settings(SERVICE_SPECS_MAX_ARRAY_LENGTH=None)
def test_a_setting_of_none_states_no_maximum() -> None:
    schema = parameters_schema(Parameters.of(Parameter("ids", "array")))
    assert schema["properties"]["ids"] == {"type": "array", "items": {}}


@override_settings(SERVICE_SPECS_MAX_ARRAY_LENGTH=None)
def test_declared_lengths_are_stated_as_min_and_max_items() -> None:
    both = Parameter("ids", "array", min_length=1, max_length=5, nullable=True)
    floor = Parameter("tags", "array", min_length=0)
    schema = parameters_schema(Parameters.of(both, floor))
    assert schema["properties"] == {
        "ids": {"type": ["array", "null"], "items": {}, "minItems": 1, "maxItems": 5},
        "tags": {"type": "array", "items": {}, "minItems": 0},
    }


class TestAny:
    def test_any_states_no_type(self) -> None:
        # Any JSON value is one, so any type stated here would be false.
        pk = Parameter("pk", "any", required=True, help="A key or a slug.")

        assert parameters_schema(Parameters.of(pk)) == {
            "type": "object",
            "properties": {"pk": {"description": "A key or a slug."}},
            "required": ["pk"],
            "additionalProperties": False,
        }

    def test_a_nullable_any_is_still_untyped(self) -> None:
        assert one(Parameter("pk", "any", nullable=True)) == {}

    def test_an_anys_default_is_stated(self) -> None:
        assert one(Parameter("pk", "any", default="abc")) == {"default": "abc"}


_UNCONFIGURED_PROBE = """
import json
from django.core.exceptions import ImproperlyConfigured
from django_service_specs.parameters.check_arguments import check_arguments
from django_service_specs.parameters.coerce_flat import coerce_flat
from django_service_specs.parameters.parameter import Parameter
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.schema.parameters_schema import parameters_schema

answers = []
for parameter in (
    Parameter("ids", "array", items="integer"),
    Parameter("ids", "array", items="integer", max_length=5),
):
    parameters = Parameters.of(parameter)
    for read in (
        lambda: parameters_schema(parameters)["properties"]["ids"],
        lambda: check_arguments(parameters, {"ids": [1, 2]}),
        lambda: coerce_flat(parameters, {"ids": ["1", "2"]}),
    ):
        try:
            answers.append(read())
        except ImproperlyConfigured:
            answers.append("ImproperlyConfigured")
print(json.dumps(answers))
"""


def test_an_undeclared_array_bound_needs_django_configured_to_describe_or_check() -> None:
    # The setting is the bound in force, so it is read rather than guessed: a
    # default stated before ``settings.configure()`` could describe a bound
    # the calls after it never meet, and the shape check and ``coerce_flat``
    # read it the same way. A declared maximum needs no setting.
    env = {key: value for key, value in os.environ.items() if key != "DJANGO_SETTINGS_MODULE"}
    completed = subprocess.run(
        [sys.executable, "-c", _UNCONFIGURED_PROBE],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == [
        "ImproperlyConfigured",
        "ImproperlyConfigured",
        "ImproperlyConfigured",
        {"type": "array", "items": {"type": "integer"}, "maxItems": 5},
        {"ids": [1, 2]},
        {"ids": [1, 2]},
    ]


@override_settings(SERVICE_SPECS_MAX_ARRAY_LENGTH=3)
def test_a_minimum_no_call_could_meet_is_refused_when_the_schema_is_built() -> None:
    # The schema states the maximum in force, which this declaration has none of.
    with pytest.raises(ImproperlyConfigured, match="min_length 4 is past the default maximum 3"):
        parameters_schema(Parameters.of(Parameter("ids", "array", min_length=4)))


@pytest.mark.parametrize("policy", [UnknownArguments.PASSTHROUGH, "passthrough"])
def test_passthrough_is_refused_rather_than_described_as_the_open_set(policy: Any) -> None:
    with pytest.raises(ValueError, match=r"UnknownArguments\.PASSTHROUGH is refused"):
        parameters_schema(AUTHOR, unknown_arguments=policy)
