from __future__ import annotations

import dataclasses
import re
from collections.abc import Callable, Mapping
from typing import Any

import pytest
from asgiref.sync import async_to_sync
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ImproperlyConfigured
from django.db.models import Q
from typing_extensions import TypedDict

from django_service_specs.authorization.unrestricted import Unrestricted
from django_service_specs.dispatch.adispatch import adispatch
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.parameters import Parameter, Parameters
from django_service_specs.schema.spec_input_schema import spec_input_schema
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.affordance import Affordance
from django_service_specs.types.selector_kind import SelectorKind
from django_service_specs.types.unset import UnsetType
from django_service_specs.validation.validated import Validated
from django_service_specs.validation.validation_context import ValidationContext
from django_service_specs.validation.validator import Validator
from tests.adapters.filters.utils import TitleFilter
from tests.specs.utils import PK, Bare, Named, Nobody, Titled

RETRIEVE = SelectorSpec(kind=SelectorKind.RETRIEVE, selector=list, reads=PK)
LIST = SelectorSpec(kind=SelectorKind.LIST, selector=list)
PRESENTED_LIST = SelectorSpec(kind=SelectorKind.LIST, selector=list, presenter=Named())
ON_THE_ROW = Affordance(code="note_archived", reason="Archived.", when=Q(archived=False))
ON_NOTHING = Affordance(code="books_closed", reason="The books are closed.", when=lambda: True)


def test_defaults() -> None:
    spec = ServiceSpec(service=print)
    assert spec.permissions is None
    assert spec.atomic is True
    assert spec.target_selector_spec() is None
    assert spec.parameters() == Parameters()
    assert spec.presenter_for_output() is None
    assert spec.output() is None
    assert spec.affordances is None
    assert spec.idempotent is None
    assert spec.allow_none is False


@pytest.mark.parametrize("idempotent", [True, False])
def test_idempotent_is_kept_as_declared(idempotent: bool) -> None:
    # ``None`` is the default and means undeclared, so a declared ``False``
    # has to survive as itself rather than collapse into silence.
    assert ServiceSpec(service=print, idempotent=idempotent).idempotent is idempotent


def test_parameters_are_the_targets_reads_then_the_validators() -> None:
    spec = ServiceSpec(
        service=print,
        permissions=[Unrestricted()],
        validator=Titled(),
        instance_selector_spec=RETRIEVE,
    )
    assert [p.name for p in spec.parameters()] == ["pk", "title"]
    assert spec.target_selector_spec() is RETRIEVE
    assert ServiceSpec(service=print, collection_selector_spec=LIST).target_selector_spec() is LIST


def test_a_name_the_target_and_the_validator_both_declare_is_refused_when_read() -> None:
    # Refused on read, not at construction: a Validator may need the app
    # registry to answer, and specs are built at import time.
    spec = ServiceSpec(service=print, validator=Titled("pk"), instance_selector_spec=RETRIEVE)
    with pytest.raises(ImproperlyConfigured, match="declared by two sources"):
        spec.parameters()


def test_a_validator_parameter_named_after_a_seed_is_refused_when_read() -> None:
    spec = ServiceSpec(service=print, validator=Titled("data"))
    with pytest.raises(ImproperlyConfigured, match=r"\['data'\], which dispatch seeds"):
        spec.parameters()


def test_the_output_is_the_spec_presenters_or_else_the_output_selectors() -> None:
    own = ServiceSpec(service=print, presenter=Named())
    assert own.presenter_for_output() is own.presenter
    assert own.output() == Named().output()
    borrowed = ServiceSpec(service=print, output_selector_spec=PRESENTED_LIST)
    assert borrowed.presenter_for_output() is PRESENTED_LIST.presenter
    assert ServiceSpec(service=print, output_selector_spec=LIST).presenter_for_output() is None


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"service": None}, "ServiceSpec.service must be callable"),
        ({"permissions": [Unrestricted]}, "holds the class Unrestricted"),
        ({"validator": Titled}, "the class Titled, which is not a Validator instance"),
        ({"validator": object()}, "is object, which is not a Validator instance"),
        (
            {"instance_selector_spec": LIST},
            "instance_selector_spec is a LIST; it must be a RETRIEVE",
        ),
        ({"collection_selector_spec": RETRIEVE}, "collection_selector_spec is a RETRIEVE"),
        ({"instance_selector_spec": object()}, "instance_selector_spec must be a SelectorSpec"),
        (
            {"instance_selector_spec": RETRIEVE, "collection_selector_spec": LIST},
            "both an instance and a collection selector",
        ),
        ({"output_selector_spec": object()}, "output_selector_spec must be a SelectorSpec"),
        ({"presenter": object()}, "not a Presenter instance"),
        (
            {"presenter": Named(), "output_selector_spec": PRESENTED_LIST},
            "declares a presenter and so does its output selector",
        ),
        ({"metadata": 1}, "metadata must be a mapping"),
        ({"kwargs": {"tenant": 1}}, "ServiceSpec.kwargs must be callable; got dict"),
        ({"input_data": 3}, "ServiceSpec.input_data must be callable; got int"),
        ({"progress_reporter": 3}, "ServiceSpec.progress_reporter must be callable; got int"),
        ({"preconditions": print}, "ServiceSpec.preconditions takes a sequence of callables"),
        ({"preconditions": [3]}, r"ServiceSpec.preconditions\[0\] must be callable; got int"),
        ({"reads": [PK.items[0]]}, "ServiceSpec.reads must be Parameters"),
        ({"reads": Parameters.of(Parameter("user", "integer"))}, r"\['user'\], which dispatch"),
        (
            {"reads": PK, "instance_selector_spec": RETRIEVE},
            r"\['pk'\] are declared by two sources",
        ),
    ],
)
def test_refuses_at_construction(kwargs: dict, message: str) -> None:
    with pytest.raises(ImproperlyConfigured, match=message):
        ServiceSpec(**{"service": print, **kwargs})


class TestInputDataNeedsAValidator:
    """``input_data`` merges over the Validator's arguments, so with none it reaches nothing."""

    def test_input_data_with_no_validator_is_refused_at_construction(self) -> None:
        with pytest.raises(ImproperlyConfigured) as refused:
            ServiceSpec(service=print, permissions=[Unrestricted()], input_data=_title)
        message = str(refused.value)
        assert "ServiceSpec.input_data merges over the Validator's arguments" in message
        assert "has no validator, so it would reach nothing" in message
        assert "Declare a validator, or use kwargs" in message

    def test_input_data_beside_a_validator_is_accepted(self) -> None:
        # Holds the ``validator is None`` conjunct of the refusal: without it
        # this is refused.
        spec = ServiceSpec(service=print, validator=Titled(), input_data=_title)
        assert spec.input_data is _title

    def test_a_spec_without_input_data_needs_no_validator(self) -> None:
        # Holds the ``input_data is not None`` conjunct: without it every
        # spec with no Validator, this one included, is refused.
        assert ServiceSpec(service=print).input_data is None


class _WholeOnly(Titled):
    """A Validator that builds every field, and says so."""

    supports_partial = False


def _a_service() -> None: ...


class _DecidedWhenBuilt(Titled):
    """A Validator whose answer depends on what it is built over, so it is set per instance."""

    def __init__(self, *, binds_part: bool) -> None:
        self.supports_partial = binds_part


class TestPartialNeedsAValidatorThatCanBindPart:
    """``partial`` is refused when the spec is declared wherever no call could honour it."""

    def test_partial_with_no_validator_is_refused_at_construction(self) -> None:
        with pytest.raises(ImproperlyConfigured) as refused:
            ServiceSpec(service=_a_service, permissions=[Unrestricted()], partial=True)
        message = str(refused.value)
        assert "ServiceSpec for _a_service declares partial=True with no validator" in message
        assert "declare a validator, or drop partial" in message

    def test_partial_with_no_validator_answers_before_many_does(self) -> None:
        # Both refuse a spec with no Validator; the partial one is checked
        # first, so the message names the declaration that does nothing.
        with pytest.raises(ImproperlyConfigured) as refused:
            ServiceSpec(service=_a_service, many=True, partial=True)
        message = str(refused.value)
        assert "declares partial=True with no validator" in message
        assert "many=True" not in message

    def test_partial_with_a_validator_that_cannot_bind_part_is_refused(self) -> None:
        with pytest.raises(ImproperlyConfigured) as refused:
            ServiceSpec(service=_a_service, validator=_WholeOnly(), partial=True)
        message = str(refused.value)
        assert "ServiceSpec for _a_service declares partial=True with a _WholeOnly" in message
        assert "which cannot validate a partial call" in message
        assert "bind only what was sent, such as FormValidator, or a custom one" in message

    def test_the_same_validator_on_a_whole_spec_is_accepted(self) -> None:
        # The refusal is about the pair: a Validator that builds every field
        # serves every spec that is not partial.
        assert ServiceSpec(service=_a_service, validator=_WholeOnly()).partial is False

    def test_a_validator_that_can_bind_part_is_accepted(self) -> None:
        assert Titled.supports_partial is True
        spec = ServiceSpec(service=_a_service, validator=Titled(), partial=True)
        assert spec.partial is True

    def test_an_instance_level_false_is_refused_at_construction(self) -> None:
        """Read off the instance, so an answer decided in ``__init__`` refuses
        the spec where it is declared rather than on its first call."""
        with pytest.raises(ImproperlyConfigured, match="which cannot validate a partial call"):
            ServiceSpec(
                service=_a_service, validator=_DecidedWhenBuilt(binds_part=False), partial=True
            )

    def test_an_instance_level_true_over_a_class_level_false_is_accepted(self) -> None:
        validator = _WholeOnly()
        validator.supports_partial = True
        assert ServiceSpec(service=_a_service, validator=validator, partial=True).partial is True
        built = _DecidedWhenBuilt(binds_part=True)
        assert ServiceSpec(service=_a_service, validator=built, partial=True).partial is True

    def test_a_validator_class_is_refused_as_not_an_instance_first(self) -> None:
        # A class has the attribute too, so the instance check must answer
        # before the partial one reads it.
        with pytest.raises(ImproperlyConfigured) as refused:
            ServiceSpec(service=_a_service, validator=_WholeOnly, partial=True)
        message = str(refused.value)
        assert "is the class _WholeOnly, which is not a Validator instance" in message
        assert "partial" not in message


class TestEngineFields:
    """The fields a dispatch reads beyond the declaration: partial, preconditions, providers."""

    def test_partial_is_kept_as_declared_and_off_by_default(self) -> None:
        assert ServiceSpec(service=print).partial is False
        assert ServiceSpec(service=print, validator=Titled(), partial=True).partial is True

    def test_the_providers_and_preconditions_are_kept_in_declaration_order(self) -> None:
        def scope() -> dict:
            return {}

        spec = ServiceSpec(
            service=print,
            kwargs=scope,
            validator=Bare(),
            input_data=dict,
            progress_reporter=print,
            preconditions=[print, len],
        )
        assert spec.kwargs is scope
        assert spec.input_data is dict
        assert spec.progress_reporter is print
        assert spec.preconditions == (print, len)
        bare = ServiceSpec(service=print)
        assert (bare.kwargs, bare.input_data, bare.progress_reporter, bare.preconditions) == (
            None,
            None,
            None,
            None,
        )

    def test_a_target_selector_s_kwargs_provider_is_its_own_to_run(self) -> None:
        # Not refused: a nested lookup's ``kwargs`` scopes the lookup, as
        # djangorestframework-services runs it.
        target = SelectorSpec(kind=SelectorKind.RETRIEVE, selector=list, reads=PK, kwargs=dict)
        assert ServiceSpec(service=print, instance_selector_spec=target).instance_selector_spec


class TestReads:
    """``reads``: what a service spec takes with no Validator in front of it."""

    def test_reads_sit_between_the_target_s_and_the_validator_s(self) -> None:
        spec = ServiceSpec(
            service=print,
            reads=Parameters.of(Parameter("project_pk", "integer", required=True)),
            validator=Titled(),
            instance_selector_spec=RETRIEVE,
        )
        assert [p.name for p in spec.parameters()] == ["pk", "project_pk", "title"]
        assert ServiceSpec(service=print).reads == Parameters()

    def test_the_input_schema_describes_each_read(self) -> None:
        spec = ServiceSpec(
            service=print,
            reads=Parameters.of(Parameter("project_pk", "integer", required=True)),
            validator=Titled(),
        )
        schema = spec_input_schema(spec)
        assert schema["properties"]["project_pk"] == {"type": "integer"}
        assert schema["required"] == ["project_pk"]

    def test_a_read_the_validator_also_declares_is_refused_when_read(self) -> None:
        # The Validator's names are read lazily, as everywhere in parameters().
        spec = ServiceSpec(
            service=print,
            reads=Parameters.of(Parameter("title", "string")),
            validator=Titled(),
        )
        with pytest.raises(ImproperlyConfigured, match=r"\['title'\] are declared by two sources"):
            spec.parameters()

    def test_a_target_selector_s_filters_are_its_service_s_parameters(self) -> None:
        collection = SelectorSpec(kind=SelectorKind.LIST, selector=list, filter_set=TitleFilter)
        spec = ServiceSpec(service=print, collection_selector_spec=collection)
        assert spec.parameters() == Parameters.of(Parameter("title", "string"))


@pytest.mark.parametrize(
    ("role", "nested", "message"),
    [
        (
            "instance_selector_spec",
            {"kind": SelectorKind.RETRIEVE, "preconditions": [print]},
            "ServiceSpec.instance_selector_spec declares preconditions, which are never run "
            "on a nested selector",
        ),
        (
            "collection_selector_spec",
            {"kind": SelectorKind.LIST, "progress_reporter": print},
            "ServiceSpec.collection_selector_spec declares a progress_reporter, which is "
            "never run on a nested selector",
        ),
        (
            "output_selector_spec",
            {"kind": SelectorKind.LIST, "kwargs": dict},
            "ServiceSpec.output_selector_spec declares kwargs, which an output selector never runs",
        ),
    ],
)
def test_a_nested_selector_declaring_what_never_runs_is_refused(
    role: str, nested: dict, message: str
) -> None:
    # Built inside the test, so the declaration the refusal is about is the
    # one that fails, rather than this module's collection.
    selector_spec = SelectorSpec(selector=list, **nested)
    with pytest.raises(ImproperlyConfigured) as refused:
        ServiceSpec(service=print, **{role: selector_spec})
    assert str(refused.value).startswith(message)


def test_a_presenter_beside_an_unpresented_output_selector_is_fine() -> None:
    spec = ServiceSpec(service=print, presenter=Named(), output_selector_spec=LIST)
    assert spec.presenter_for_output() is spec.presenter


class TestAffordances:
    def test_a_list_is_kept_in_declaration_order_as_a_tuple(self) -> None:
        spec = ServiceSpec(service=print, affordances=[ON_NOTHING, ON_THE_ROW])
        assert spec.affordances == (ON_NOTHING, ON_THE_ROW)

    @pytest.mark.parametrize(
        "affordances",
        [ON_THE_ROW, {ON_THE_ROW}, (a for a in [ON_THE_ROW])],
        ids=["single", "set", "generator"],
    )
    def test_anything_but_a_sequence_is_refused(self, affordances: object) -> None:
        with pytest.raises(ImproperlyConfigured) as refused:
            ServiceSpec(service=print, affordances=affordances)  # type: ignore[arg-type]
        assert str(refused.value) == (
            "ServiceSpec.affordances takes a sequence of Affordance declarations; got "
            f"{type(affordances).__name__}. Wrap a single one in a list: affordances=[...]."
        )

    def test_an_entry_that_is_not_an_affordance_is_refused_by_index(self) -> None:
        with pytest.raises(ImproperlyConfigured) as refused:
            ServiceSpec(service=print, affordances=[ON_THE_ROW, Q(archived=False)])  # type: ignore[list-item]
        assert str(refused.value) == "ServiceSpec.affordances[1] must be an Affordance; got Q."

    def test_a_code_declared_twice_is_refused(self) -> None:
        again = Affordance(code="note_archived", reason="Reworded.", when=lambda: True)
        with pytest.raises(ImproperlyConfigured) as refused:
            ServiceSpec(service=print, affordances=[ON_THE_ROW, again])
        assert str(refused.value).startswith(
            "ServiceSpec.affordances declares the code 'note_archived' twice."
        )

    # The guard is ``is_row_condition(when) and (collection_selector_spec is not
    # None or many)``; service_spec.py names the test holding each operand.
    def test_a_row_condition_on_a_collection_operation_is_refused(self) -> None:
        with pytest.raises(ImproperlyConfigured) as refused:
            ServiceSpec(
                service=print, collection_selector_spec=LIST, affordances=[ON_NOTHING, ON_THE_ROW]
            )
        assert str(refused.value).startswith(
            "ServiceSpec.affordances[1] ('note_archived') is a condition on the row, and this "
            "spec operates on a collection"
        )

    def test_a_callable_condition_on_a_collection_operation_is_fine(self) -> None:
        spec = ServiceSpec(service=print, collection_selector_spec=LIST, affordances=[ON_NOTHING])
        assert spec.affordances == (ON_NOTHING,)

    def test_a_row_condition_on_a_one_row_operation_is_fine(self) -> None:
        spec = ServiceSpec(service=print, instance_selector_spec=RETRIEVE, affordances=[ON_THE_ROW])
        assert spec.affordances == (ON_THE_ROW,)


class TestMany:
    """``many``: a list of rows, each validated by the spec's Validator.

    Every spec here is built inside its test rather than at module level, so a
    tree without the field fails each test on its own rather than the module.
    """

    def test_off_by_default_with_items_as_the_list_s_name(self) -> None:
        spec = ServiceSpec(service=print)
        assert spec.many is False
        assert spec.many_argument == "items"

    def test_the_top_level_is_the_reads_then_the_list_of_rows(self) -> None:
        reads = Parameters.of(Parameter("confirmed", "boolean"))
        spec = ServiceSpec(service=print, many=True, validator=Titled("title"), reads=reads)
        assert spec.parameters() == Parameters.of(
            Parameter("confirmed", "boolean"),
            Parameter(
                "items",
                "array",
                required=True,
                items=Parameters.of(Parameter("title", "string")),
            ),
        )

    def test_the_list_travels_under_its_declared_name(self) -> None:
        spec = ServiceSpec(service=print, many=True, many_argument="rows", validator=Titled())
        assert spec.parameters().names() == frozenset({"rows"})

    def test_a_row_field_may_share_a_read_s_name(self) -> None:
        # A row's fields are not top-level arguments, so a ``title`` read
        # beside the list is a different argument from each row's ``title``.
        reads = Parameters.of(Parameter("title", "string"))
        spec = ServiceSpec(service=print, many=True, validator=Titled("title"), reads=reads)
        assert spec.parameters().names() == frozenset({"title", "items"})

    @pytest.mark.parametrize("name", ["", "1st", "two words", "rows!", "röws", 3])
    def test_a_name_that_is_not_an_ascii_identifier_is_refused(self, name: object) -> None:
        with pytest.raises(ImproperlyConfigured) as refused:
            ServiceSpec(service=print, many=True, many_argument=name, validator=Titled())
        assert str(refused.value).startswith(
            f"ServiceSpec.many_argument must be an ASCII identifier; got {name!r}."
        )

    @pytest.mark.parametrize(
        ("field", "value"),
        [("many_argument", "rows"), ("many_min_length", 1), ("many_max_length", 1)],
    )
    def test_a_declaration_without_many_is_refused(self, field: str, value: object) -> None:
        with pytest.raises(ImproperlyConfigured) as refused:
            ServiceSpec(service=print, **{field: value})
        assert str(refused.value).startswith(
            f"ServiceSpec declares {field}={value!r} without many=True."
        )

    @pytest.mark.parametrize(
        ("field", "value"),
        [("many_argument", "items"), ("many_min_length", None), ("many_max_length", None)],
    )
    def test_a_default_written_out_without_many_is_not_a_declaration(
        self, field: str, value: object
    ) -> None:
        # The other half of each guard above: every field carries its default
        # on every spec, so the default alone refuses nothing.
        assert ServiceSpec(service=print, **{field: value}).many is False

    @pytest.mark.parametrize(
        ("lengths", "carried"),
        [
            pytest.param({"many_min_length": 1, "many_max_length": 50}, (1, 50), id="declared"),
            # So an empty list runs, and the setting's maximum bounds the list
            # as it bounds every array.
            pytest.param({}, (None, None), id="none-by-default"),
        ],
    )
    def test_the_list_carries_its_declared_lengths(
        self, lengths: dict[str, int], carried: tuple[int | None, int | None]
    ) -> None:
        spec = ServiceSpec(service=print, many=True, validator=Titled("title"), **lengths)
        the_list = spec.parameters().get("items")
        assert the_list is not None
        assert (the_list.min_length, the_list.max_length) == carried

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"many_min_length": -1}, "min_length -1 is not a non-negative int"),
            ({"many_max_length": True}, "max_length True is not a non-negative int"),
            ({"many_min_length": 3, "many_max_length": 2}, "min_length 3 is past max_length 2"),
        ],
    )
    def test_a_length_no_list_could_meet_is_refused_at_construction(
        self, kwargs: dict[str, Any], message: str
    ) -> None:
        # Read by the list's own Parameter, so the rules are one rule; refused
        # when the spec is built, before any Validator is asked for its fields.
        with pytest.raises(ImproperlyConfigured, match=f"ServiceSpec.many_argument.*{message}"):
            ServiceSpec(service=print, many=True, validator=Titled(), **kwargs)

    def test_a_many_spec_needs_a_validator(self) -> None:
        with pytest.raises(ImproperlyConfigured) as refused:
            ServiceSpec(service=print, many=True)
        assert str(refused.value).startswith("ServiceSpec declares many=True with no validator.")

    @pytest.mark.parametrize(
        ("role", "selector"),
        [("instance", RETRIEVE), ("collection", LIST)],
    )
    def test_a_target_selector_beside_many_is_refused(
        self, role: str, selector: SelectorSpec
    ) -> None:
        with pytest.raises(ImproperlyConfigured) as refused:
            ServiceSpec(
                service=print,
                many=True,
                validator=Titled(),
                **{f"{role}_selector_spec": selector},
            )
        assert str(refused.value).startswith(
            f"ServiceSpec declares a {role}_selector_spec with many=True. A list of rows "
            "resolves no target"
        )

    def test_a_list_named_after_a_read_is_refused(self) -> None:
        reads = Parameters.of(Parameter("items", "string"))
        with pytest.raises(ImproperlyConfigured, match="declared by two sources"):
            ServiceSpec(service=print, many=True, validator=Titled(), reads=reads)

    def test_a_list_named_after_a_seed_is_refused(self) -> None:
        with pytest.raises(ImproperlyConfigured) as refused:
            ServiceSpec(service=print, many=True, many_argument="data", validator=Titled())
        assert str(refused.value).startswith(
            "ServiceSpec.many_argument declares the parameter(s) ['data'], which dispatch seeds"
        )

    def test_a_row_condition_on_a_many_spec_is_refused(self) -> None:
        with pytest.raises(ImproperlyConfigured) as refused:
            ServiceSpec(
                service=print, many=True, validator=Titled(), affordances=[ON_NOTHING, ON_THE_ROW]
            )
        assert str(refused.value).startswith(
            "ServiceSpec.affordances[1] ('note_archived') is a condition on the row, and this "
            "spec operates on a list of rows (many=True)"
        )

    def test_a_callable_condition_on_a_many_spec_is_fine(self) -> None:
        spec = ServiceSpec(service=print, many=True, validator=Titled(), affordances=[ON_NOTHING])
        assert spec.affordances == (ON_NOTHING,)


class TestReturnsMany:
    """``returns_many``: the service's own return is a list of rows, the output half of ``many``.

    Every spec here is built inside its test, as in ``TestMany``, so a tree
    without the field fails each test on its own rather than the module. What
    dispatch does with the field is in tests/dispatch/test_dispatch.py's
    ``TestReturnsMany``, and on the async path in test_adispatch.py.
    """

    def test_off_by_default(self) -> None:
        assert ServiceSpec(service=print).returns_many is False

    def test_kept_as_declared(self) -> None:
        assert ServiceSpec(service=print, returns_many=True).returns_many is True

    def test_the_input_is_left_alone(self) -> None:
        # The call's arguments are declared as they are without the field: no
        # list of rows, no ``many_argument``.
        declared: dict[str, Any] = {
            "service": print,
            "validator": Titled(),
            "instance_selector_spec": RETRIEVE,
        }
        plain = ServiceSpec(**declared)
        listed = ServiceSpec(**declared, returns_many=True)
        assert listed.parameters() == plain.parameters()
        assert spec_input_schema(listed) == spec_input_schema(plain)

    def test_beside_many_is_refused(self) -> None:
        # Sized with a Validator, so ``_check_many`` passes and this is the
        # refusal that answers.
        with pytest.raises(ImproperlyConfigured) as refused:
            ServiceSpec(service=print, many=True, validator=Titled(), returns_many=True)
        message = str(refused.value)
        assert message.startswith("ServiceSpec declares returns_many=True with many=True.")
        assert message.endswith("remove returns_many.")
        assert "no validator" not in message

    @pytest.mark.parametrize("kind", [SelectorKind.LIST, SelectorKind.RETRIEVE])
    def test_beside_an_output_selector_is_refused(self, kind: SelectorKind) -> None:
        reread = SelectorSpec(kind=kind, selector=list)
        with pytest.raises(ImproperlyConfigured) as refused:
            ServiceSpec(service=print, output_selector_spec=reread, returns_many=True)
        message = str(refused.value)
        assert message.startswith(
            "ServiceSpec declares returns_many=True beside an output_selector_spec."
        )
        assert message.endswith(
            "remove returns_many, or remove the output selector to present the service's "
            "own return as a list."
        )

    @pytest.mark.parametrize("kind", [SelectorKind.LIST, SelectorKind.RETRIEVE])
    def test_beside_many_and_an_output_selector_the_output_selector_answers(
        self, kind: SelectorKind
    ) -> None:
        # Both refusals could answer this input, and only one is true of it: a
        # ``many`` spec with a re-read presents what the re-read returns, one
        # value for a RETRIEVE, never the service's return as a list. Sized
        # with a Validator, so ``_check_many`` passes.
        reread = SelectorSpec(kind=kind, selector=list)
        with pytest.raises(ImproperlyConfigured) as refused:
            ServiceSpec(
                service=print,
                many=True,
                validator=Titled(),
                output_selector_spec=reread,
                returns_many=True,
            )
        message = str(refused.value)
        assert message.startswith(
            "ServiceSpec declares returns_many=True beside an output_selector_spec."
        )
        # The remedy names only what clears the refusal: without the re-read,
        # the many refusal would answer next.
        assert message.endswith(
            "remove returns_many; without the output selector, many presents the service's "
            "own return as a list already."
        )
        assert "with many=True" not in message
        assert "already presents what its service returns" not in message

    @pytest.mark.parametrize(
        "declared",
        [
            pytest.param({"many": True, "validator": Titled()}, id="beside-many"),
            pytest.param({"output_selector_spec": LIST}, id="beside-an-output-selector"),
        ],
    )
    def test_a_false_written_out_declares_nothing(self, declared: dict[str, Any]) -> None:
        # The other half of each refusal above: the field carries its default
        # on every spec, so the default alone refuses nothing.
        assert ServiceSpec(service=print, **declared, returns_many=False).returns_many is False

    def test_derive_carries_the_field(self) -> None:
        base = ServiceSpec(service=print, returns_many=True)
        assert base.derive(atomic=False).returns_many is True
        assert base.derive(returns_many=False).returns_many is False

    @pytest.mark.parametrize(
        ("base", "changes"),
        [
            pytest.param(
                {"returns_many": True},
                {"many": True, "validator": Titled()},
                id="many-onto-a-returns-many-spec",
            ),
            pytest.param(
                {"output_selector_spec": LIST},
                {"returns_many": True},
                id="returns-many-onto-a-spec-with-an-output-selector",
            ),
        ],
    )
    def test_derive_refuses_what_construction_refuses(
        self, base: dict[str, Any], changes: dict[str, Any]
    ) -> None:
        spec = ServiceSpec(service=print, **base)
        with pytest.raises(ImproperlyConfigured, match=r"^ServiceSpec declares returns_many=True"):
            spec.derive(**changes)


class _AsyncValidate(Titled):
    async def validate(  # A coroutine nobody awaits, where the values should be.
        self, arguments: Mapping[str, Any], context: ValidationContext
    ) -> dict[str, Any]:
        return dict(arguments)


class _AsyncValidated(Titled):
    async def validated(  # What dispatch calls, overridden as a coroutine.
        self, arguments: Mapping[str, Any], context: ValidationContext
    ) -> Validated:
        return Validated(values=dict(arguments), data=dict(arguments))


class _AsyncValidatedMany(Titled):
    async def validated_many(  # What dispatch calls on a many spec, as a coroutine.
        self,
        rows: Mapping[int, Mapping[str, Any]],
        context: ValidationContext,
        *,
        many_argument: str,
    ) -> Validated:
        return Validated(values={many_argument: []}, data=[])


class TestAnAsyncValidatorIsRefused:
    """Dispatch calls the Validator from sync code on both entry points and never awaits it.

    One case per method, because the methods are named in one tuple and
    coverage cannot see a name dropped from it.
    """

    @pytest.mark.parametrize(
        ("validator", "method"),
        [
            (_AsyncValidate(), "validate"),
            (_AsyncValidated(), "validated"),
            (_AsyncValidatedMany(), "validated_many"),
        ],
    )
    def test_at_construction(self, validator: Validator, method: str) -> None:
        named = f"ServiceSpec.validator.{method} is {type(validator).__name__}.{method}"
        with pytest.raises(ImproperlyConfigured, match=re.escape(named + ", an async callable")):
            ServiceSpec(service=print, validator=validator)

    def test_a_sync_validator_is_accepted(self) -> None:
        validator = Titled()
        assert ServiceSpec(service=print, validator=validator).validator is validator


# --- a typed provider and the parameters its values reach -----------------------------


class _FillsProject(TypedDict):
    project: int


class _FillsPk(TypedDict):
    pk: int


class _FillsTitle(TypedDict):
    title: str


class _MayFillProject(TypedDict):
    project: int | UnsetType


def _project() -> _FillsProject:
    return {"project": 1}


def _pk() -> _FillsPk:
    return {"pk": 1}


def _title() -> _FillsTitle:
    return {"title": "t"}


def _maybe_project() -> _MayFillProject:
    return {"project": 1}


PROJECT = Parameters.of(Parameter("project", "integer", required=True))
TARGET = "ServiceSpec.instance_selector_spec"


def _target(**kwargs: Any) -> SelectorSpec:
    return SelectorSpec(kind=SelectorKind.RETRIEVE, selector=list, reads=PK, **kwargs)


class TestProviderReach:
    """A typed provider filling a parameter its values never reach is refused.

    Every pair of a provider and a seat it does not reach, so each seat and
    each provider is held by its own case: the ``reads`` seats when the spec
    is built, the Validator's fields when ``parameters()`` assembles them.
    """

    @pytest.mark.parametrize(
        ("declaration", "provider", "key", "where", "reaching"),
        [
            pytest.param(
                {"reads": PROJECT, "validator": Bare(), "input_data": _project},
                "ServiceSpec.input_data",
                "project",
                "ServiceSpec.reads",
                "ServiceSpec.kwargs",
                id="input-data-on-a-read",
            ),
            pytest.param(
                {"instance_selector_spec": _target(), "validator": Bare(), "input_data": _pk},
                "ServiceSpec.input_data",
                "pk",
                f"{TARGET}.reads",
                f"{TARGET}.kwargs",
                id="input-data-on-a-target-read",
            ),
            pytest.param(
                {"instance_selector_spec": _target(), "kwargs": _pk},
                "ServiceSpec.kwargs",
                "pk",
                f"{TARGET}.reads",
                f"{TARGET}.kwargs",
                id="kwargs-on-a-target-read",
            ),
            pytest.param(
                {"reads": PROJECT, "instance_selector_spec": _target(kwargs=_project)},
                f"{TARGET}.kwargs",
                "project",
                "ServiceSpec.reads",
                "ServiceSpec.kwargs",
                id="target-kwargs-on-a-read",
            ),
            pytest.param(
                {
                    "reads": PROJECT,
                    "collection_selector_spec": SelectorSpec(
                        kind=SelectorKind.LIST, selector=list, kwargs=_project
                    ),
                },
                "ServiceSpec.collection_selector_spec.kwargs",
                "project",
                "ServiceSpec.reads",
                "ServiceSpec.kwargs",
                id="collection-kwargs-on-a-read",
            ),
        ],
    )
    def test_on_a_read_when_the_spec_is_built(
        self, declaration: dict[str, Any], provider: str, key: str, where: str, reaching: str
    ) -> None:
        named = (
            f"{provider} is annotated to fill {[key]!r}, which {where} declares, and its "
            f"values never reach {where}"
        )
        with pytest.raises(ImproperlyConfigured, match=re.escape(named)) as refused:
            ServiceSpec(service=print, **declaration)
        assert f"Only {reaching} fills {where}" in str(refused.value)

    @pytest.mark.parametrize(
        ("declaration", "provider"),
        [
            pytest.param({"kwargs": _title}, "ServiceSpec.kwargs", id="kwargs"),
            pytest.param(
                {"instance_selector_spec": _target(kwargs=_title)},
                f"{TARGET}.kwargs",
                id="target-kwargs",
            ),
            pytest.param({"kwargs": _title, "many": True}, "ServiceSpec.kwargs", id="many-row"),
        ],
    )
    def test_on_a_validator_field_when_parameters_are_assembled(
        self, declaration: dict[str, Any], provider: str
    ) -> None:
        # Built, since the Validator's fields may need the app registry and
        # are first read here.
        spec = ServiceSpec(service=print, validator=Titled(), **declaration)
        named = (
            f"{provider} is annotated to fill ['title'], which ServiceSpec.validator "
            "declares, and its values never reach ServiceSpec.validator"
        )
        with pytest.raises(ImproperlyConfigured, match=re.escape(named)) as refused:
            spec.parameters()
        assert "Only ServiceSpec.input_data fills ServiceSpec.validator" in str(refused.value)

    def test_a_provider_filling_the_parameters_its_values_reach_is_accepted(self) -> None:
        spec = ServiceSpec(
            service=print,
            reads=PROJECT,
            kwargs=_project,
            instance_selector_spec=_target(kwargs=_pk),
            validator=Titled(),
            input_data=_title,
        )
        assert spec.parameters().names() == {"pk", "project", "title"}

    @pytest.mark.parametrize(
        "provider",
        [
            pytest.param(_maybe_project, id="declinable"),
            pytest.param(lambda: {"project": 1}, id="untyped"),
        ],
    )
    def test_a_key_it_does_not_fill_naming_a_parameter_it_never_reaches_is_accepted(
        self, provider: Any
    ) -> None:
        spec = ServiceSpec(service=print, reads=PROJECT, validator=Bare(), input_data=provider)
        assert spec.parameters().names() == {"project"}

    def test_a_key_no_parameter_declares_is_accepted(self) -> None:
        spec = ServiceSpec(service=print, validator=Titled(), kwargs=_project, input_data=_pk)
        assert spec.parameters().names() == {"title"}

    def test_a_provider_annotation_resolving_after_the_build_is_refused_here(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A return annotation naming a type defined after the spec reads as
        # untyped when the spec is built, and as typed once it resolves.
        def late() -> Any:
            return {"project": 1}

        late.__annotations__["return"] = "_DefinedLater"
        spec = ServiceSpec(service=print, reads=PROJECT, validator=Bare(), input_data=late)
        monkeypatch.setitem(globals(), "_DefinedLater", _FillsProject)
        named = "ServiceSpec.input_data is annotated to fill ['project'], which ServiceSpec.reads"
        with pytest.raises(ImproperlyConfigured, match=re.escape(named)):
            spec.parameters()


def test_a_service_spec_compiles_to_itself() -> None:
    # What makes it a SpecSource, and how kernel_spec tells a spec from a
    # declaration that compiles to one without importing either class.
    spec = ServiceSpec(service=print)

    assert spec.as_kernel_spec() is spec


class TestDerive:
    """``derive`` builds a new spec through the constructor, changing only what it names."""

    def _base(self) -> ServiceSpec:
        return ServiceSpec(
            service=print,
            permissions=[Unrestricted()],
            reads=PROJECT,
            validator=Titled(),
            instance_selector_spec=RETRIEVE,
            presenter=Named(),
            affordances=[ON_NOTHING],
            preconditions=[print],
            metadata={"owner": "billing"},
        )

    def test_a_derived_permission_replaces_the_base_s(self) -> None:
        base = self._base()
        derived = base.derive(permissions=[Nobody()])

        assert [type(check) for check in derived.permissions or ()] == [Nobody]
        assert [type(check) for check in base.permissions or ()] == [Unrestricted]

    def test_derived_reads_replace_the_base_s_rather_than_extending_them(self) -> None:
        base = self._base()
        limit = Parameters.of(Parameter("limit", "integer"))
        derived = base.derive(reads=limit)

        assert derived.reads == limit
        assert derived.parameters().names() == {"pk", "limit", "title"}
        assert base.parameters().names() == {"pk", "project", "title"}

    def test_a_derived_validator_changes_the_parameters_the_spec_takes(self) -> None:
        derived = self._base().derive(validator=Titled("title", "body"))

        assert derived.parameters().names() == {"pk", "project", "title", "body"}

    def test_every_field_it_does_not_name_is_the_base_s_own(self) -> None:
        base = self._base()
        derived = base.derive(permissions=[Nobody()])

        for spec_field in dataclasses.fields(ServiceSpec):
            if spec_field.name != "permissions":
                assert getattr(derived, spec_field.name) is getattr(base, spec_field.name), (
                    spec_field.name
                )

    def test_it_never_mutates_the_base(self) -> None:
        base = self._base()
        before = {f.name: getattr(base, f.name) for f in dataclasses.fields(ServiceSpec)}
        base.derive(permissions=[Nobody()], reads=Parameters(), atomic=False)

        assert {f.name: getattr(base, f.name) for f in dataclasses.fields(ServiceSpec)} == before

    def test_no_changes_is_an_equal_new_spec(self) -> None:
        base = self._base()
        derived = base.derive()

        assert derived == base
        assert derived is not base

    def test_a_subclass_derives_its_own_class(self) -> None:
        @dataclasses.dataclass(frozen=True, kw_only=True)
        class Audited(ServiceSpec):
            audit_label: str = "default"

        base = Audited(service=print, permissions=[Unrestricted()], audit_label="refunds")
        derived = base.derive(atomic=False)

        assert type(derived) is Audited
        assert derived.audit_label == "refunds"
        assert base.derive(audit_label="other").audit_label == "other"

    def test_a_derived_spec_is_checked_as_a_fresh_declaration_is(self) -> None:
        with pytest.raises(ImproperlyConfigured, match=r"ServiceSpec\.permissions is empty"):
            self._base().derive(permissions=[])

    def test_a_combination_the_constructor_refuses_is_refused(self) -> None:
        # Each field valid alone; together the constructor refuses them, so
        # the check that answers is the combination's, not a per-field one.
        base = ServiceSpec(service=print, validator=Bare(), input_data=lambda: {})
        with pytest.raises(ImproperlyConfigured, match=r"ServiceSpec\.input_data merges over"):
            base.derive(validator=None)

    @pytest.mark.parametrize(
        ("changes", "named"),
        [
            # A misspelt field, which ``dataclasses.replace`` would also refuse
            # but in its own words.
            ({"permission": [Nobody()]}, "'permission'"),
            # A method rather than a field.
            ({"parameters": PK}, "'parameters'"),
            # Only the unknown names are listed, beside a known one.
            ({"atomic": False, "nope": 1, "also_nope": 2}, "'also_nope', 'nope'"),
            # What a transport answers for itself at the mount, never a spec
            # field, so it is not one a variant can carry either.
            ({"server_arguments": None}, "'server_arguments'"),
        ],
    )
    def test_a_name_that_is_not_a_field_is_refused(self, changes: dict, named: str) -> None:
        message = f"ServiceSpec.derive() takes the spec's own fields, and not {named}."
        with pytest.raises(TypeError, match=re.escape(message)):
            self._base().derive(**changes)


FIELDS = Parameters.of(Parameter("fields", "array", items="string"))


class _FillsFields(TypedDict):
    fields: list[str]


def _fields() -> _FillsFields:
    return {"fields": ["name"]}


class _Recording(Validator):
    """A Validator declaring ``title``, keeping the arguments it was handed."""

    def __init__(self) -> None:
        self.handed: dict[str, Any] = {}

    def parameters(self) -> Parameters:
        return Parameters.of(Parameter("title", "string"))

    def validate(self, arguments: Mapping[str, Any], context: ValidationContext) -> dict[str, Any]:
        self.handed = dict(arguments)
        return dict(arguments)


class TestShapes:
    """``shapes``: the arguments that shape what the presenter renders.

    Every spec here is built inside its test rather than at module level, so a
    tree without the field fails each test on its own rather than the module.
    """

    def test_none_by_default(self) -> None:
        assert ServiceSpec(service=print).shapes == Parameters()

    def test_shapes_sit_after_the_reads_and_before_the_validator_s(self) -> None:
        spec = ServiceSpec(
            service=print,
            reads=Parameters.of(Parameter("project_pk", "integer", required=True)),
            shapes=FIELDS,
            validator=Titled(),
            instance_selector_spec=RETRIEVE,
        )
        assert [p.name for p in spec.parameters()] == ["pk", "project_pk", "fields", "title"]

    def test_a_many_spec_takes_them_beside_its_reads_and_before_the_list(self) -> None:
        reads = Parameters.of(Parameter("confirmed", "boolean"))
        spec = ServiceSpec(service=print, many=True, validator=Titled(), reads=reads, shapes=FIELDS)
        assert [p.name for p in spec.parameters()] == ["confirmed", "fields", "items"]

    def test_the_input_schema_describes_each_shape_in_the_closed_set(self) -> None:
        spec = ServiceSpec(service=print, shapes=FIELDS, validator=Titled())
        schema = spec_input_schema(spec)
        assert schema["properties"]["fields"] == {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 1000,
        }
        assert schema["additionalProperties"] is False

    @pytest.mark.django_db
    @pytest.mark.parametrize("entry", [dispatch, async_to_sync(adispatch)], ids=["sync", "async"])
    def test_a_shape_reaches_neither_the_validator_nor_the_service(
        self, entry: Callable[..., Any]
    ) -> None:
        """Part of the closed set, so the call is not refused for sending one,
        and kept out of the Validator's arguments and the run's pool, whose
        ``fields`` keeps its default."""
        received: dict[str, Any] = {}

        def service(*, data: Any, fields: Any = "absent") -> None:
            received.update(data=data, fields=fields)

        validator = _Recording()
        spec = ServiceSpec(
            service=service, permissions=[Unrestricted()], shapes=FIELDS, validator=validator
        )
        entry(spec, principal=AnonymousUser(), arguments={"title": "t", "fields": ["name"]})
        assert validator.handed == {"title": "t"}
        assert received == {"data": {"title": "t"}, "fields": "absent"}

    def test_a_shape_s_declaration_is_shape_checked(self) -> None:
        spec = ServiceSpec(service=print, permissions=[Unrestricted()], shapes=FIELDS)
        with pytest.raises(InvalidArguments) as refused:
            dispatch(spec, principal=AnonymousUser(), arguments={"fields": "name"})
        assert "fields" in refused.value.detail

    def test_anything_but_parameters_is_refused(self) -> None:
        with pytest.raises(ImproperlyConfigured, match=r"ServiceSpec\.shapes must be Parameters"):
            ServiceSpec(service=print, shapes=[Parameter("fields", "string")])  # ty: ignore[invalid-argument-type]

    def test_a_shape_named_after_a_reserved_seed_is_refused(self) -> None:
        with pytest.raises(ImproperlyConfigured, match=r"ServiceSpec\.shapes declares .*'user'"):
            ServiceSpec(service=print, shapes=Parameters.of(Parameter("user", "string")))

    def test_a_shape_a_read_also_declares_is_refused(self) -> None:
        reads = Parameters.of(Parameter("fields", "string"))
        with pytest.raises(ImproperlyConfigured, match=r"\['fields'\] are declared by two sources"):
            ServiceSpec(service=print, reads=reads, shapes=FIELDS)

    def test_a_shape_the_target_selector_reads_is_refused(self) -> None:
        shapes = Parameters.of(Parameter("pk", "integer"))
        with pytest.raises(ImproperlyConfigured, match=r"\['pk'\] are declared by two sources"):
            ServiceSpec(service=print, shapes=shapes, instance_selector_spec=RETRIEVE)

    def test_a_shape_named_as_the_many_list_is_refused(self) -> None:
        shapes = Parameters.of(Parameter("items", "string"))
        with pytest.raises(ImproperlyConfigured, match=r"\['items'\] are declared by two sources"):
            ServiceSpec(service=print, many=True, validator=Titled(), shapes=shapes)

    def test_a_shape_the_validator_also_declares_is_refused_when_read(self) -> None:
        # The Validator's names are read lazily, as everywhere in parameters().
        shapes = Parameters.of(Parameter("title", "string"))
        spec = ServiceSpec(service=print, shapes=shapes, validator=Titled())
        with pytest.raises(ImproperlyConfigured, match=r"\['title'\] are declared by two sources"):
            spec.parameters()

    @pytest.mark.parametrize(
        ("changes", "provider"),
        [
            pytest.param({"kwargs": _fields}, "ServiceSpec.kwargs", id="kwargs"),
            pytest.param(
                {"input_data": _fields, "validator": Bare()},
                "ServiceSpec.input_data",
                id="input-data",
            ),
            pytest.param(
                {"instance_selector_spec": dataclasses.replace(RETRIEVE, kwargs=_fields)},
                r"ServiceSpec\.instance_selector_spec\.kwargs",
                id="target-kwargs",
            ),
        ],
    )
    def test_a_provider_annotated_to_fill_a_shape_is_refused(
        self, changes: dict[str, Any], provider: str
    ) -> None:
        """No provider's values reach the shapes, so a key one fills would be
        reported as the server's while dispatch still asked the caller for it."""
        with pytest.raises(
            ImproperlyConfigured, match=rf"{provider} is annotated to fill \['fields'\]"
        ):
            ServiceSpec(service=print, shapes=FIELDS, **changes)

    def test_the_refusal_says_no_provider_fills_a_shape(self) -> None:
        with pytest.raises(ImproperlyConfigured, match=r"No provider fills ServiceSpec\.shapes"):
            ServiceSpec(service=print, shapes=FIELDS, kwargs=_fields)

    @pytest.mark.parametrize("role", ["instance", "collection", "output"])
    def test_a_nested_selector_declaring_shapes_is_refused(self, role: str) -> None:
        """Its presenter never presents this spec's call, or presents it under
        this spec's shapes; one case per role, since coverage cannot see one
        dropped from the loop."""
        kind = SelectorKind.LIST if role == "collection" else SelectorKind.RETRIEVE
        nested = SelectorSpec(kind=kind, selector=list, shapes=FIELDS)
        with pytest.raises(
            ImproperlyConfigured, match=rf"ServiceSpec\.{role}_selector_spec declares shapes"
        ):
            ServiceSpec(service=print, **{f"{role}_selector_spec": nested})

    def test_a_derived_spec_replaces_its_shapes(self) -> None:
        base = ServiceSpec(service=print, shapes=FIELDS)
        assert base.derive(shapes=Parameters()).shapes == Parameters()
