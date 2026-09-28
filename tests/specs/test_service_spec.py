from __future__ import annotations

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_service_specs.authorization.unrestricted import Unrestricted
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from tests.specs.utils import PK, Named, Titled

RETRIEVE = SelectorSpec(kind=SelectorKind.RETRIEVE, selector=list, reads=PK)
LIST = SelectorSpec(kind=SelectorKind.LIST, selector=list)
PRESENTED_LIST = SelectorSpec(kind=SelectorKind.LIST, selector=list, presenter=Named())


def test_defaults() -> None:
    spec = ServiceSpec(service=print)
    assert spec.permissions is None
    assert spec.atomic is True
    assert spec.target_selector_spec() is None
    assert spec.parameters() == Parameters()
    assert spec.presenter_for_output() is None
    assert spec.output() is None


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
