from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from typing_extensions import TypedDict

from django_service_specs.dispatch.check_requested_input import check_requested_input
from django_service_specs.parameters.check_arguments import check_arguments
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.parameter import Parameter
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.pool.pool_seeds import PoolSeeds
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.selector_kind import SelectorKind
from django_service_specs.validation.validation_context import ValidationContext
from django_service_specs.validation.validator import Validator
from tests.specs.utils import Foreign

pytestmark = pytest.mark.django_db

Check = Callable[[ServiceSpec | SelectorSpec, Any], None]

# The wording of each check, so a test asserts which one answered and that
# the check before it did not.
UNDECLARED = "declares no top-level parameter"
NOT_A_SCHEMA = "instead of a schema object"
UNRENDERABLE = "which not every transport can render"
DISAGREES = "would fail the shape check"
SERVER_OWNED = "fills it, so the caller's answer would be dropped"


class Declaring(Validator):
    """A Validator that declares the parameters it is given and validates nothing."""

    def __init__(self, *parameters: Parameter) -> None:
        self._parameters = Parameters.of(*parameters)

    def parameters(self) -> Parameters:
        return self._parameters

    def validate(self, arguments: Mapping[str, Any], context: ValidationContext) -> dict[str, Any]:
        return dict(arguments)


def service(**kwargs: Any) -> None: ...


def declaring(*parameters: Parameter) -> ServiceSpec:
    """A service spec whose Validator declares ``parameters`` at the top level."""
    return ServiceSpec(service=service, validator=Declaring(*parameters))


@pytest.fixture
def check(django_assert_num_queries: Any) -> Check:
    """``check_requested_input``, run where a query would fail the test."""

    def run(spec: ServiceSpec | SelectorSpec, schema: Any) -> None:
        with django_assert_num_queries(0):
            check_requested_input(spec, schema)

    return run


def refusal(check: Check, spec: ServiceSpec | SelectorSpec, schema: Any) -> str:
    with pytest.raises(ImproperlyConfigured) as raised:
        check(spec, schema)
    return str(raised.value)


class TestAnswerable:
    def test_a_boolean_asked_for_a_declared_boolean_passes(self, check: Check) -> None:
        check(declaring(Parameter("confirmed", "boolean")), {"confirmed": {"type": "boolean"}})

    def test_an_array_of_enum_values_passes(self, check: Check) -> None:
        spec = declaring(Parameter("tags", "array", items="string"))
        check(spec, {"tags": {"type": "array", "items": {"type": "string", "enum": ["a", "b"]}}})

    def test_an_array_of_titled_values_passes(self, check: Check) -> None:
        spec = declaring(Parameter("tags", "array", items="string"))
        titled = {"anyOf": [{"const": "a", "title": "A"}, {"const": "b", "title": "B"}]}
        check(spec, {"tags": {"type": "array", "items": titled}})

    def test_no_schema_asks_nothing(self, check: Check) -> None:
        check(declaring(), None)

    def test_an_empty_schema_asks_nothing(self, check: Check) -> None:
        check(declaring(), {})

    def test_a_selector_spec_reads_its_reads(self, check: Check) -> None:
        spec = SelectorSpec(
            selector=service,
            kind=SelectorKind.RETRIEVE,
            reads=Parameters.of(Parameter("confirmed", "boolean")),
        )
        check(spec, {"confirmed": {"type": "boolean"}})

    def test_a_reads_parameter_of_a_many_spec_carries_the_answer(self, check: Check) -> None:
        spec = ServiceSpec(
            service=service,
            many=True,
            validator=Declaring(Parameter("title", "string")),
            reads=Parameters.of(Parameter("confirmed", "boolean")),
        )
        check(spec, {"confirmed": {"type": "boolean"}})

    def test_every_key_is_checked(self, check: Check) -> None:
        spec = declaring(Parameter("confirmed", "boolean"))
        message = refusal(
            check, spec, {"confirmed": {"type": "boolean"}, "reason": {"type": "string"}}
        )
        assert "'reason'" in message
        assert UNDECLARED in message


class TestUndeclared:
    def test_a_key_no_parameter_declares_is_refused(self, check: Check) -> None:
        message = refusal(check, declaring(), {"confirmed": {"type": "boolean"}})
        assert "'confirmed'" in message
        assert UNDECLARED in message
        assert "many" not in message

    def test_a_key_declared_only_inside_a_many_row_is_refused(self, check: Check) -> None:
        spec = ServiceSpec(
            service=service, many=True, validator=Declaring(Parameter("confirmed", "boolean"))
        )
        message = refusal(check, spec, {"confirmed": {"type": "boolean"}})
        assert "'confirmed'" in message
        assert UNDECLARED in message
        # The hint names where a value asked once for the call belongs.
        assert "reads" in message

    def test_a_selector_spec_is_given_no_many_hint(self, check: Check) -> None:
        # Holds the ``isinstance`` half of the hint's guard: a selector spec
        # has no ``many`` to read.
        message = refusal(
            check,
            SelectorSpec(selector=service, kind=SelectorKind.LIST),
            {"confirmed": {"type": "boolean"}},
        )
        assert UNDECLARED in message
        assert "many" not in message

    def test_the_undeclared_check_answers_before_the_fragment_is_read(self, check: Check) -> None:
        message = refusal(check, declaring(), {"confirmed": "boolean"})
        assert UNDECLARED in message
        assert NOT_A_SCHEMA not in message

    def test_a_schema_that_is_no_mapping_is_refused(self, check: Check) -> None:
        message = refusal(check, declaring(), ["confirmed"])
        assert "not a mapping" in message


class _Confirmed(TypedDict):
    confirmed: bool


def fill_confirmed() -> _Confirmed:
    return {"confirmed": False}


class TestServerOwned:
    def test_a_declared_key_a_provider_fills_is_refused(self, check: Check) -> None:
        # Declared at the top level, so the undeclared check passes it, and the
        # provider's value replaces whatever the caller answers.
        spec = ServiceSpec(
            service=service,
            reads=Parameters.of(Parameter("confirmed", "boolean")),
            kwargs=fill_confirmed,
        )
        message = refusal(check, spec, {"confirmed": {"type": "boolean"}})
        assert "'confirmed'" in message
        assert SERVER_OWNED in message
        assert UNDECLARED not in message

    def test_the_server_owned_check_answers_before_the_fragment_is_read(self, check: Check) -> None:
        spec = ServiceSpec(
            service=service,
            reads=Parameters.of(Parameter("confirmed", "boolean")),
            kwargs=fill_confirmed,
        )
        message = refusal(check, spec, {"confirmed": "boolean"})
        assert SERVER_OWNED in message
        assert NOT_A_SCHEMA not in message

    def test_the_pool_seeds_given_are_the_ones_read(self, django_assert_num_queries: Any) -> None:
        # A parameter a registered seed occupies is refused at the call, and
        # the parameters are assembled against the default seeds, so a seed
        # registered for the call is read from the keyword or not at all.
        spec = declaring(Parameter("confirmed", "boolean"))
        schema = {"confirmed": {"type": "boolean"}}
        seeds = PoolSeeds().extend(confirmed=lambda: None)
        with django_assert_num_queries(0):
            check_requested_input(spec, schema)
            with pytest.raises(ImproperlyConfigured) as raised:
                check_requested_input(spec, schema, pool_seeds=seeds)
        assert SERVER_OWNED in str(raised.value)


class TestNotASchema:
    @pytest.mark.parametrize("fragment", ["boolean", True, None, ["boolean"]])
    def test_a_fragment_that_is_no_schema_object_is_refused(
        self, check: Check, fragment: Any
    ) -> None:
        message = refusal(
            check, declaring(Parameter("confirmed", "boolean")), {"confirmed": fragment}
        )
        assert "'confirmed'" in message
        assert NOT_A_SCHEMA in message


class TestUnrenderable:
    def test_a_type_list_is_refused(self, check: Check) -> None:
        spec = declaring(Parameter("confirmed", "boolean", nullable=True))
        message = refusal(check, spec, {"confirmed": {"type": ["boolean", "null"]}})
        assert "'confirmed'" in message
        assert UNRENDERABLE in message

    @pytest.mark.parametrize(
        "fragment",
        [
            pytest.param({"type": "object"}, id="bare"),
            # Holds the ``array`` half of the multi-select rule: enum items do
            # not make an object a list of values.
            pytest.param({"type": "object", "items": {"enum": ["a"]}}, id="with-enum-items"),
        ],
    )
    def test_an_object_is_refused(self, check: Check, fragment: dict[str, Any]) -> None:
        # Declared an object, so only renderability can refuse it.
        spec = declaring(Parameter("address", "object"))
        message = refusal(check, spec, {"address": fragment})
        assert "'address'" in message
        assert UNRENDERABLE in message
        assert DISAGREES not in message

    def test_a_fragment_naming_no_type_is_refused(self, check: Check) -> None:
        spec = declaring(Parameter("confirmed", "any"))
        message = refusal(check, spec, {"confirmed": {"enum": [True]}})
        assert UNRENDERABLE in message

    @pytest.mark.parametrize(
        "items",
        [
            pytest.param({"type": "string"}, id="no-enum"),
            pytest.param({"enum": "ab"}, id="enum-not-a-list"),
            pytest.param({"anyOf": {"const": "a"}}, id="any-of-not-a-list"),
            pytest.param(["a", "b"], id="items-not-a-schema-object"),
            pytest.param(None, id="no-items"),
        ],
    )
    def test_an_array_without_enum_items_is_refused(self, check: Check, items: Any) -> None:
        # Declared an array of strings, so only renderability can refuse it.
        spec = declaring(Parameter("tags", "array", items="string"))
        fragment = {"type": "array"} if items is None else {"type": "array", "items": items}
        message = refusal(check, spec, {"tags": fragment})
        assert "'tags'" in message
        assert UNRENDERABLE in message
        assert DISAGREES not in message


class TestDisagrees:
    @pytest.mark.parametrize(
        ("declared", "asked"),
        [
            pytest.param(Parameter("confirmed", "boolean"), "string", id="string-for-boolean"),
            pytest.param(Parameter("count", "integer"), "number", id="number-for-integer"),
            pytest.param(Parameter("count", "integer"), "string", id="string-for-integer"),
            pytest.param(Parameter("count", "number"), "boolean", id="boolean-for-number"),
            pytest.param(Parameter("note", "string"), "integer", id="integer-for-string"),
            pytest.param(
                Parameter("amount", "string", format="decimal"), "boolean", id="boolean-for-decimal"
            ),
            pytest.param(Parameter("upload", "file"), "string", id="string-for-file"),
            pytest.param(Parameter("address", "object"), "string", id="string-for-object"),
            pytest.param(Parameter("tags", "array"), "string", id="string-for-array"),
        ],
    )
    def test_a_scalar_type_the_parameter_does_not_take_is_refused(
        self, check: Check, declared: Parameter, asked: str
    ) -> None:
        message = refusal(check, declaring(declared), {declared.name: {"type": asked}})
        assert f"{declared.name!r}" in message
        assert DISAGREES in message
        assert UNRENDERABLE not in message

    def test_an_array_for_a_scalar_is_refused(self, check: Check) -> None:
        spec = declaring(Parameter("tag", "string"))
        fragment = {"type": "array", "items": {"enum": ["a"]}}
        message = refusal(check, spec, {"tag": fragment})
        assert "'tag'" in message
        assert DISAGREES in message

    def test_an_array_of_strings_for_an_array_of_integers_is_refused(self, check: Check) -> None:
        spec = declaring(Parameter("ids", "array", items="integer"))
        fragment = {"type": "array", "items": {"type": "string", "enum": ["a"]}}
        assert DISAGREES in refusal(check, spec, {"ids": fragment})

    def test_an_element_type_list_is_refused(self, check: Check) -> None:
        spec = declaring(Parameter("ids", "array", items="integer"))
        fragment = {"type": "array", "items": {"type": ["integer"], "enum": [1]}}
        assert DISAGREES in refusal(check, spec, {"ids": fragment})

    def test_an_untyped_enum_element_is_a_string(self, check: Check) -> None:
        # The untyped and the titled multi-select are both lists of strings.
        spec = declaring(Parameter("ids", "array", items="integer"))
        fragment = {"type": "array", "items": {"enum": [1, 2]}}
        assert DISAGREES in refusal(check, spec, {"ids": fragment})

    def test_an_integer_for_an_array_of_decimal_strings_is_refused(self, check: Check) -> None:
        # Holds the ``string`` half of the decimal rule: an array's format
        # describes its elements, and a number is no array.
        spec = declaring(Parameter("amounts", "array", items="string", format="decimal"))
        message = refusal(check, spec, {"amounts": {"type": "integer"}})
        assert DISAGREES in message

    def test_the_rows_of_a_many_spec_are_no_list_of_values(self, check: Check) -> None:
        # The list a many spec travels under is declared at the top level, and
        # its rows are objects, which no value of an enum is.
        spec = ServiceSpec(
            service=service, many=True, validator=Declaring(Parameter("title", "string"))
        )
        fragment = {"type": "array", "items": {"enum": ["a"]}}
        message = refusal(check, spec, {"items": fragment})
        assert "'items'" in message
        assert DISAGREES in message

    def test_an_array_of_objects_is_refused(self, check: Check) -> None:
        spec = declaring(Parameter("rows", "array", items="object"))
        fragment = {"type": "array", "items": {"type": "object", "enum": [{}]}}
        assert DISAGREES in refusal(check, spec, {"rows": fragment})


class TestAgrees:
    @pytest.mark.parametrize(
        ("declared", "asked"),
        [
            pytest.param(Parameter("count", "number"), "integer", id="integer-for-number"),
            pytest.param(Parameter("count", "number"), "number", id="number-for-number"),
            pytest.param(Parameter("count", "integer"), "integer", id="integer-for-integer"),
            pytest.param(Parameter("note", "string"), "string", id="string-for-string"),
            pytest.param(
                Parameter("when", "string", format="date-time"), "string", id="string-for-date"
            ),
            pytest.param(
                Parameter("amount", "string", format="decimal"), "string", id="string-for-decimal"
            ),
            pytest.param(
                Parameter("amount", "string", format="decimal"), "number", id="number-for-decimal"
            ),
            pytest.param(
                Parameter("amount", "string", format="decimal"),
                "integer",
                id="integer-for-decimal",
            ),
            pytest.param(Parameter("value", "any"), "boolean", id="boolean-for-any"),
            pytest.param(Parameter("value", "any"), "number", id="number-for-any"),
        ],
    )
    def test_a_scalar_type_the_parameter_takes_passes(
        self, check: Check, declared: Parameter, asked: str
    ) -> None:
        check(declaring(declared), {declared.name: {"type": asked}})

    @pytest.mark.parametrize(
        "declared",
        [
            pytest.param(Parameter("tags", "array"), id="array-of-anything"),
            pytest.param(Parameter("tags", "any"), id="any"),
            pytest.param(
                Parameter("amounts", "array", items="string", format="decimal"),
                id="array-of-decimals",
            ),
        ],
    )
    def test_an_array_of_enum_values_passes_where_any_string_element_is_taken(
        self, check: Check, declared: Parameter
    ) -> None:
        fragment = {"type": "array", "items": {"enum": ["1", "2"]}}
        check(declaring(declared), {declared.name: fragment})

    def test_a_typed_enum_element_is_read_as_its_type(self, check: Check) -> None:
        spec = declaring(Parameter("ids", "array", items="integer"))
        check(spec, {"ids": {"type": "array", "items": {"type": "integer", "enum": [1, 2]}}})


class TestTheShapeCheckAgrees:
    """The agreement rule read against ``check_arguments`` itself, so the two cannot drift."""

    @pytest.mark.parametrize(
        ("declared", "answer"),
        [
            pytest.param(Parameter("count", "number"), 3, id="integer-for-number"),
            pytest.param(Parameter("amount", "string", format="decimal"), 3, id="integer-decimal"),
            pytest.param(
                Parameter("amount", "string", format="decimal"), 2.5, id="number-for-decimal"
            ),
            pytest.param(Parameter("value", "any"), True, id="boolean-for-any"),
            pytest.param(Parameter("tags", "array"), ["a"], id="strings-for-array"),
            pytest.param(
                Parameter("amounts", "array", items="string", format="decimal"),
                ["1.5"],
                id="strings-for-decimals",
            ),
        ],
    )
    def test_an_answer_to_a_question_that_passes_is_taken(
        self, declared: Parameter, answer: Any
    ) -> None:
        check_arguments(Parameters.of(declared), {declared.name: answer})

    @pytest.mark.parametrize(
        ("declared", "answer"),
        [
            pytest.param(Parameter("count", "integer"), 5.5, id="number-for-integer"),
            pytest.param(Parameter("count", "integer"), "abc", id="string-for-integer"),
            pytest.param(Parameter("note", "string"), 3, id="integer-for-string"),
            pytest.param(
                Parameter("amount", "string", format="decimal"), True, id="boolean-for-decimal"
            ),
            pytest.param(Parameter("upload", "file"), "abc", id="string-for-file"),
            pytest.param(Parameter("ids", "array", items="integer"), ["a"], id="strings-for-ints"),
            pytest.param(
                Parameter(
                    "items",
                    "array",
                    items=Parameters.of(Parameter("title", "string")),
                ),
                ["a"],
                id="strings-for-rows",
            ),
        ],
    )
    def test_an_answer_to_a_question_that_is_refused_can_fail(
        self, declared: Parameter, answer: Any
    ) -> None:
        with pytest.raises(InvalidArguments):
            check_arguments(Parameters.of(declared), {declared.name: answer})


class TestSources:
    def test_a_source_is_checked_as_the_spec_it_compiles_to(self, check: Check) -> None:
        source: Any = Foreign(declaring(Parameter("confirmed", "boolean")))

        check(source, {"confirmed": {"type": "boolean"}})
        assert UNDECLARED in refusal(check, source, {"other": {"type": "boolean"}})
