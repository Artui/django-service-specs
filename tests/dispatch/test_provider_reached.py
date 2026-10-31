from __future__ import annotations

from typing import Any, TypedDict

import pytest

from django_service_specs import provider_reached as exported
from django_service_specs.dispatch.check_call import check_call
from django_service_specs.dispatch.provider_reached import provider_reached
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.parameters import Parameter, Parameters
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.selector_kind import SelectorKind
from django_service_specs.types.unset import UnsetType
from tests.dispatch.utils import OPEN, Titled, make_user
from tests.specs.utils import Foreign

_READS = Parameters.of(
    Parameter("club", "string", required=True),
    Parameter("locale", "string", required=True),
    Parameter("page", "integer", required=True),
)


class _Fills(TypedDict):
    club: str
    locale: str | UnsetType


def _typed() -> _Fills:
    return {"club": "c", "locale": "l"}


def _untyped() -> dict[str, Any]:
    return {}


def _listing(**declared: Any) -> SelectorSpec:
    return SelectorSpec(
        kind=SelectorKind.LIST, selector=lambda **_: [], permissions=OPEN, reads=_READS, **declared
    )


def test_it_is_exported_from_the_root() -> None:
    assert exported is provider_reached


def test_a_typed_provider_reaches_its_filled_and_its_declinable_keys() -> None:
    assert provider_reached(_listing(kwargs=_typed)) == {"club", "locale"}


def test_an_untyped_provider_reaches_every_read_in_its_seat() -> None:
    assert provider_reached(_listing(kwargs=_untyped)) == {"club", "locale", "page"}


def test_no_provider_reaches_nothing() -> None:
    assert provider_reached(_listing()) == frozenset()


def test_input_data_reaches_the_validator_s_fields_and_a_target_provider_its_reads() -> None:
    target = SelectorSpec(
        kind=SelectorKind.RETRIEVE,
        selector=lambda **_: None,
        permissions=OPEN,
        reads=Parameters.of(Parameter("pk", "integer", required=True)),
        kwargs=_untyped,
    )
    spec = ServiceSpec(
        service=lambda **_: None,
        permissions=OPEN,
        validator=Titled(),
        input_data=_untyped,
        instance_selector_spec=target.derive(permissions=None),
    )
    assert provider_reached(spec) == {"title", "pk"}


def test_a_declaration_is_read_as_the_spec_it_compiles_to() -> None:
    assert provider_reached(Foreign(_listing(kwargs=_typed))) == {"club", "locale"}


@pytest.mark.django_db
def test_it_is_the_set_check_call_relaxes() -> None:
    """A name it lists is not demanded of the caller; every other required read is."""
    ada = make_user("ada")
    spec = _listing(kwargs=_typed)
    with pytest.raises(InvalidArguments) as refused:
        check_call(spec, principal=ada, arguments={})
    assert set(refused.value.detail) == _READS.names() - provider_reached(spec) == {"page"}
    # Every read reached, so the call starts with none sent.
    check_call(_listing(kwargs=_untyped), principal=ada, arguments={})
