from __future__ import annotations

from django_service_specs.schema.utils import allow_null


class TestAllowNull:
    def test_the_type_becomes_a_list_with_null(self) -> None:
        assert allow_null({"type": "string", "format": "date"}) == {
            "type": ["string", "null"],
            "format": "date",
        }

    def test_the_type_keeps_its_place_before_the_other_keywords(self) -> None:
        widened = allow_null({"type": "object", "properties": {}, "required": ["a"]})

        assert list(widened) == ["type", "properties", "required"]

    def test_the_schema_passed_in_is_left_alone(self) -> None:
        schema = {"type": "integer"}

        widened = allow_null(schema)

        assert schema == {"type": "integer"}
        assert widened is not schema

    def test_an_untyped_node_admits_null_already_and_is_copied_as_it_is(self) -> None:
        # A file's node, and an array's undeclared element: neither states a
        # type, so null is among the values it admits without a word added.
        schema = {"description": "The minutes."}

        widened = allow_null(schema)

        assert widened == {"description": "The minutes."}
        assert widened is not schema
