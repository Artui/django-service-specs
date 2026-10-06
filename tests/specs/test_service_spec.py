from __future__ import annotations

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.db.models import Q

from django_service_specs.authorization.unrestricted import Unrestricted
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.affordance import Affordance
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
    ],
)
def test_refuses_at_construction(kwargs: dict, message: str) -> None:
    with pytest.raises(ImproperlyConfigured, match=message):
        ServiceSpec(**{"service": print, **kwargs})


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
