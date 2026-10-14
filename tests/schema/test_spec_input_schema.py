from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from typing_extensions import TypedDict

from django_service_specs.dispatch.utils import shape_check
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.parameters import Parameter, Parameters
from django_service_specs.schema.spec_input_schema import spec_input_schema
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.server_owned_keys import server_owned_keys
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.selector_kind import SelectorKind
from django_service_specs.types.unknown_arguments import UnknownArguments
from django_service_specs.validation.validation_context import ValidationContext
from django_service_specs.validation.validator import Validator
from tests.dispatch.utils import OPEN, PK, note_by_pk, notes_of
from tests.specs.utils import Foreign

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
                    "maxItems": 1000,
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


def test_a_many_spec_takes_its_reads_and_the_list_of_rows() -> None:
    # Built here rather than at module level, so a tree without ``many``
    # fails this test alone.
    class Row(Validator):
        def parameters(self) -> Parameters:
            return Parameters.of(Parameter("title", "string", required=True))

        def validate(
            self, arguments: Mapping[str, Any], context: ValidationContext
        ) -> dict[str, Any]:
            return dict(arguments)

    reads = Parameters.of(Parameter("confirmed", "boolean"))
    spec = ServiceSpec(service=print, permissions=OPEN, many=True, validator=Row(), reads=reads)
    assert spec_input_schema(spec) == {
        "type": "object",
        "properties": {
            "confirmed": {"type": "boolean"},
            "items": {
                "type": "array",
                "maxItems": 1000,
                "items": {
                    "type": "object",
                    "properties": {"title": {"type": "string"}},
                    "required": ["title"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["items"],
        "additionalProperties": False,
    }


TAG = Parameters.of(Parameter("label", "string", required=True))


class _Project(TypedDict):
    project: int


def the_project() -> _Project:
    """A typed ``kwargs`` provider: it fills ``project``, so dispatch demands it of nobody."""
    return {"project": 1}


class Article(Validator):
    """Required fields at every depth: the top, an object's fields, an array's rows."""

    def parameters(self) -> Parameters:
        return Parameters.of(
            Parameter("title", "string", required=True),
            Parameter("body", "string", required=True),
            Parameter("meta", "object", fields=TAG, required=True),
            Parameter("tags", "array", items=TAG, required=True),
        )

    def validate(self, arguments: Mapping[str, Any], context: ValidationContext) -> dict[str, Any]:
        return dict(arguments)


def article_spec(*, partial: bool) -> ServiceSpec:
    return ServiceSpec(
        service=edit,
        permissions=OPEN,
        validator=Article(),
        partial=partial,
        reads=Parameters.of(Parameter("project", "integer", required=True)),
        instance_selector_spec=SelectorSpec(
            kind=SelectorKind.RETRIEVE, selector=note_by_pk, reads=PK
        ),
    )


class TestPartial:
    def test_a_partial_spec_requires_none_of_its_validators_parameters_at_any_depth(
        self,
    ) -> None:
        schema = spec_input_schema(article_spec(partial=True))

        # The reads still name the row and its scope; the Validator's fields,
        # an object's and each row's included, may each be left out.
        assert schema["required"] == ["pk", "project"]
        assert "required" not in schema["properties"]["meta"]
        assert "required" not in schema["properties"]["tags"]["items"]

    def test_a_spec_that_is_not_partial_requires_every_required_parameter(self) -> None:
        schema = spec_input_schema(article_spec(partial=False))

        assert schema["required"] == ["pk", "project", "title", "body", "meta", "tags"]
        assert schema["properties"]["meta"]["required"] == ["label"]
        assert schema["properties"]["tags"]["items"]["required"] == ["label"]

    def test_a_partial_spec_with_no_target_keeps_its_reads_required(self) -> None:
        spec = ServiceSpec(
            service=edit,
            permissions=OPEN,
            validator=Article(),
            partial=True,
            reads=Parameters.of(Parameter("project", "integer", required=True)),
        )

        assert spec_input_schema(spec)["required"] == ["project"]

    def test_an_update_naming_its_row_by_pk_requires_the_pk_alone(self) -> None:
        # The case docs/schema.md states: a target read ``pk``, and a Validator
        # requiring ``title`` and ``body``.
        class TitleAndBody(Validator):
            def parameters(self) -> Parameters:
                return Parameters.of(
                    Parameter("title", "string", required=True),
                    Parameter("body", "string", required=True),
                )

            def validate(
                self, arguments: Mapping[str, Any], context: ValidationContext
            ) -> dict[str, Any]:
                return dict(arguments)

        spec = ServiceSpec(
            service=edit,
            permissions=OPEN,
            validator=TitleAndBody(),
            partial=True,
            instance_selector_spec=SelectorSpec(
                kind=SelectorKind.RETRIEVE, selector=note_by_pk, reads=PK
            ),
        )

        assert spec_input_schema(spec)["required"] == ["pk"]

    def test_a_read_a_provider_fills_is_listed_as_declared_and_owned_by_the_server(
        self,
    ) -> None:
        # The schema relaxes only what ``partial`` relaxes. A read a typed
        # provider fills stays required here, and ``server_owned_keys`` is how
        # a transport learns to take it out.
        spec = ServiceSpec(
            service=edit,
            permissions=OPEN,
            validator=Article(),
            partial=True,
            reads=Parameters.of(Parameter("project", "integer", required=True)),
            kwargs=the_project,
        )

        assert spec_input_schema(spec)["required"] == ["project"]
        assert "project" in server_owned_keys(spec)

    def test_a_partial_spec_leaves_its_parameters_declaration_as_it_was(self) -> None:
        spec = article_spec(partial=True)

        spec_input_schema(spec)

        assert spec.parameters().get("title") == Parameter("title", "string", required=True)

    @pytest.mark.parametrize("partial", [True, False])
    def test_the_schema_requires_exactly_what_the_shape_check_refuses_when_absent(
        self, partial: bool
    ) -> None:
        spec = article_spec(partial=partial)
        whole = {
            "pk": 1,
            "project": 2,
            "title": "t",
            "body": "b",
            "meta": {"label": "m"},
            "tags": [{"label": "x"}],
        }
        schema = spec_input_schema(spec)

        for name in whole:
            call = {key: value for key, value in whole.items() if key != name}
            assert (name in schema.get("required", ())) == _refused(spec, call)
        for name, inner in (("meta", schema["properties"]["meta"]), ("tags", None)):
            node = inner if inner is not None else schema["properties"]["tags"]["items"]
            empty: Any = {} if name == "meta" else [{}]
            call = {**whole, name: empty}
            assert ("label" in node.get("required", ())) == _refused(spec, call)


class _Title(TypedDict):
    title: str


def the_title() -> _Title:
    """A typed ``input_data`` provider: it fills the Validator's ``title``."""
    return {"title": "server"}


class _Pk(TypedDict):
    pk: int


def the_pk() -> _Pk:
    """A typed ``kwargs`` provider on the target selector: it fills the lookup's ``pk``."""
    return {"pk": 1}


def _filled_spec(*, partial: bool, filled: str) -> ServiceSpec:
    providers: dict[str, Any] = {
        "nothing": {},
        "a-read": {"kwargs": the_project},
        "a-validator-field": {"input_data": the_title},
    }
    target = SelectorSpec(
        kind=SelectorKind.RETRIEVE,
        selector=note_by_pk,
        reads=PK,
        **({"kwargs": the_pk} if filled == "a-target-read" else {}),
    )
    return ServiceSpec(
        service=edit,
        permissions=OPEN,
        validator=Article(),
        partial=partial,
        reads=Parameters.of(Parameter("project", "integer", required=True)),
        instance_selector_spec=target,
        **providers.get(filled, {}),
    )


@pytest.mark.parametrize("filled", ["nothing", "a-read", "a-validator-field", "a-target-read"])
@pytest.mark.parametrize("partial", [True, False])
def test_the_schema_less_server_owned_keys_requires_what_the_shape_check_demands(
    partial: bool, filled: str
) -> None:
    # The two read ``partial`` through one function, and a key a typed
    # provider fills is the one place they part: the schema lists it as
    # declared and ``server_owned_keys`` names it for a transport to take out,
    # where the shape check never demands it. Less that set, they agree.
    spec = _filled_spec(partial=partial, filled=filled)
    whole = {
        "pk": 1,
        "project": 2,
        "title": "t",
        "body": "b",
        "meta": {"label": "m"},
        "tags": [{"label": "x"}],
    }
    schema = spec_input_schema(spec)
    required = set(schema.get("required", ())) - server_owned_keys(spec)
    assert required == {name for name in whole if _refused(spec, _without(whole, name))}
    for name, empty in (("meta", {}), ("tags", [{}])):
        node = schema["properties"][name]
        node = node if name == "meta" else node["items"]
        assert ("label" in node.get("required", ())) == _refused(spec, {**whole, name: empty})


def _without(call: Mapping[str, Any], name: str) -> dict[str, Any]:
    return {key: value for key, value in call.items() if key != name}


def _refused(spec: ServiceSpec, call: Mapping[str, Any]) -> bool:
    try:
        shape_check(spec, spec.parameters(), call, unknown_arguments=UnknownArguments.REJECT)
    except InvalidArguments:
        return True
    return False


class TestPartialMany:
    def test_a_partial_many_spec_requires_the_list_and_its_reads_and_nothing_in_a_row(
        self,
    ) -> None:
        class Row(Validator):
            def parameters(self) -> Parameters:
                return Parameters.of(
                    Parameter("title", "string", required=True),
                    Parameter("meta", "object", fields=TAG, required=True),
                )

            def validate(
                self, arguments: Mapping[str, Any], context: ValidationContext
            ) -> dict[str, Any]:
                return dict(arguments)

        # A read may share a row field's name, and stays required as declared.
        reads = Parameters.of(Parameter("title", "string", required=True))
        spec = ServiceSpec(
            service=print, permissions=OPEN, many=True, partial=True, validator=Row(), reads=reads
        )

        schema = spec_input_schema(spec)

        assert schema["required"] == ["title", "items"]
        row = schema["properties"]["items"]["items"]
        assert "required" not in row
        assert "required" not in row["properties"]["meta"]
        assert not _refused(spec, {"title": "t", "items": [{}, {"meta": {}}]})


def test_passthrough_is_refused() -> None:
    spec = SelectorSpec(kind=SelectorKind.RETRIEVE, selector=note_by_pk, reads=PK)
    with pytest.raises(ValueError, match=r"UnknownArguments\.PASSTHROUGH is refused"):
        spec_input_schema(spec, unknown_arguments=UnknownArguments.PASSTHROUGH)


def test_a_foreign_declaration_is_described_as_its_compiled_spec() -> None:
    spec = SelectorSpec(kind=SelectorKind.RETRIEVE, selector=note_by_pk, reads=PK)
    assert spec_input_schema(Foreign(spec)) == spec_input_schema(spec)
