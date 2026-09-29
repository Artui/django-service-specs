from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from django_service_specs.parameters.parameter import Parameter
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.schema.spec_input_schema import spec_input_schema
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.validation.unknown_arguments import UnknownArguments
from django_service_specs.validation.validation_context import ValidationContext
from django_service_specs.validation.validator import Validator
from tests.dispatch.utils import OPEN, PK, note_by_pk, notes_of

ROW = Parameters.of(Parameter("title", "string", required=True))


class Rows(Validator):
    """Declares a list of rows, so the policy has a level below the top to reach."""

    def __init__(self) -> None:
        self.asked = 0

    def parameters(self) -> Parameters:
        self.asked += 1
        return Parameters.of(Parameter("rows", "array", items=ROW, required=True))

    def validate(self, arguments: Mapping[str, Any], context: ValidationContext) -> dict[str, Any]:
        return dict(arguments)


def edit(**_: Any) -> None:
    return None


class TestSpecInputSchema:
    def test_a_selector_specs_schema_is_its_reads(self) -> None:
        spec = SelectorSpec(
            kind=SelectorKind.LIST,
            selector=notes_of,
            permissions=OPEN,
            reads=Parameters.of(Parameter("search", "string", help="Part of the title.")),
        )

        assert spec_input_schema(spec) == {
            "type": "object",
            "properties": {"search": {"type": "string", "description": "Part of the title."}},
            "additionalProperties": False,
        }

    def test_a_service_specs_schema_is_its_targets_reads_then_its_validators_parameters(
        self,
    ) -> None:
        spec = ServiceSpec(
            service=edit,
            permissions=OPEN,
            validator=Rows(),
            instance_selector_spec=SelectorSpec(
                kind=SelectorKind.RETRIEVE, selector=note_by_pk, reads=PK
            ),
        )

        schema = spec_input_schema(spec)

        assert list(schema["properties"]) == ["pk", "rows"]
        assert schema["required"] == ["pk", "rows"]

    @pytest.mark.parametrize("policy", [UnknownArguments.IGNORE, "ignore"])
    def test_the_policy_reaches_every_level(self, policy: Any) -> None:
        spec = ServiceSpec(service=edit, permissions=OPEN, validator=Rows())

        assert spec_input_schema(spec, unknown_arguments=policy) == {
            "type": "object",
            "properties": {
                "rows": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"title": {"type": "string"}},
                        "required": ["title"],
                    },
                }
            },
            "required": ["rows"],
        }

    def test_the_declaration_is_read_on_every_call(self) -> None:
        validator = Rows()
        spec = ServiceSpec(service=edit, permissions=OPEN, validator=validator)
        assert validator.asked == 0

        spec_input_schema(spec)
        spec_input_schema(spec)

        assert validator.asked == 2
