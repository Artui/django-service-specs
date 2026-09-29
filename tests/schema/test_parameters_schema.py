from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

import pytest
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
                "books": {"type": "array", "items": closed_book},
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
            "items": {"type": "integer"},
        }

    def test_an_array_of_rows_describes_each_row_as_an_object(self) -> None:
        assert one(Parameter("books", "array", items=PUBLISHER)) == {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
                "additionalProperties": False,
            },
        }

    def test_an_array_with_no_items_accepts_any_element(self) -> None:
        assert one(Parameter("anything", "array")) == {"type": "array", "items": {}}


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
            "items": {"type": "string", "enum": ["red"]},
        }

    def test_a_nullable_element_admits_null_in_its_items_and_its_enum(self) -> None:
        ids = Parameter("ids", "array", items="integer", items_nullable=True, choices=[1, 2])

        # The shape check keeps a null element without reading the choices, so an
        # enum that did not list it would refuse a call that runs.
        assert check_arguments(Parameters.of(ids), {"ids": [1, None]}) == {"ids": [1, None]}
        assert one(ids) == {
            "type": "array",
            "items": {"type": ["integer", "null"], "enum": [1, 2, None]},
        }

    def test_a_nullable_elements_choices_that_list_null_list_it_once(self) -> None:
        ids = Parameter("ids", "array", items="integer", items_nullable=True, choices=[1, None])

        assert one(ids)["items"] == {"type": ["integer", "null"], "enum": [1, None]}

    def test_a_nullable_row_admits_null_beside_its_properties(self) -> None:
        publishers = Parameter("publishers", "array", items=PUBLISHER, items_nullable=True)

        assert one(publishers) == {
            "type": "array",
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
            "items": {"enum": [1, "one"]},
        }

    def test_choices_json_cannot_carry_are_left_out_whole(self) -> None:
        # Listing only the values JSON can carry would claim the others are
        # refused, so the enum goes and the type stays.
        rate = Parameter("rate", "string", format="decimal", choices=["1.5", Decimal("2.5")])

        assert one(rate) == {"type": "string", "format": "decimal"}
        assert one(Parameter("rates", "array", choices=[Decimal("1")])) == {
            "type": "array",
            "items": {},
        }


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
