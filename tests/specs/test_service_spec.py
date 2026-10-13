from __future__ import annotations

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.db.models import Q

from django_service_specs.authorization.unrestricted import Unrestricted
from django_service_specs.parameters.parameter import Parameter
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.schema.spec_input_schema import spec_input_schema
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.affordance import Affordance
from tests.filters.utils import TitleFilter
from tests.specs.utils import PK, Named, Titled

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


class TestEngineFields:
    """The fields a dispatch reads beyond the declaration: partial, preconditions, providers."""

    def test_partial_is_kept_as_declared_and_off_by_default(self) -> None:
        assert ServiceSpec(service=print).partial is False
        assert ServiceSpec(service=print, partial=True).partial is True

    def test_the_providers_and_preconditions_are_kept_in_declaration_order(self) -> None:
        def scope() -> dict:
            return {}

        spec = ServiceSpec(
            service=print,
            kwargs=scope,
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

    # The guard is ``is_row_condition(when) and collection_selector_spec is not
    # None``. The refusal holds the pair; the next two tests hold one half each:
    # delete either half and that test's spec is refused.
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

    def test_a_declared_name_without_many_is_refused(self) -> None:
        with pytest.raises(ImproperlyConfigured) as refused:
            ServiceSpec(service=print, many_argument="rows")
        assert str(refused.value).startswith(
            "ServiceSpec declares many_argument='rows' without many=True."
        )

    def test_the_default_name_written_out_without_many_is_not_a_declaration(self) -> None:
        # The other half of the guard above: the field carries its default on
        # every spec, so the default alone refuses nothing.
        assert ServiceSpec(service=print, many_argument="items").many is False

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
