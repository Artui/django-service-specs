from __future__ import annotations

import pytest

from django_service_specs.authorization.unrestricted import Unrestricted
from django_service_specs.registry.registered_spec import RegisteredSpec
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from tests.specs.utils import Foreign, ForeignWithContract


def _noop() -> None:
    return None


def _service() -> ServiceSpec:
    return ServiceSpec(service=_noop, permissions=[Unrestricted()])


class TestRegisteredSpec:
    def test_defaults_to_no_tags(self) -> None:
        spec = _service()
        entry = RegisteredSpec(name="refund_order", spec=spec)
        assert entry.name == "refund_order"
        assert entry.spec is spec
        assert entry.tags == frozenset()

    def test_carries_tags(self) -> None:
        entry = RegisteredSpec(
            name="list_orders",
            spec=SelectorSpec(kind=SelectorKind.LIST, selector=list, permissions=[Unrestricted()]),
            tags=frozenset({"read", "public"}),
        )
        assert entry.tags == {"read", "public"}

    def test_accepts_positional_arguments(self) -> None:
        spec = SelectorSpec(kind=SelectorKind.RETRIEVE, selector=list, permissions=[Unrestricted()])
        entry = RegisteredSpec("get_order", spec)
        assert entry.name == "get_order"
        assert entry.spec is spec

    def test_frozen(self) -> None:
        entry = RegisteredSpec(name="refund_order", spec=_service())
        with pytest.raises(AttributeError):
            entry.name = "other"  # type: ignore[misc]

    def test_kind_is_not_stored(self) -> None:
        # Derived by isinstance wherever it is needed, so it can never drift
        # from the spec it describes.
        entry = RegisteredSpec(
            name="list_orders",
            spec=SelectorSpec(kind=SelectorKind.LIST, selector=list, permissions=[Unrestricted()]),
        )
        assert not hasattr(entry, "kind")


class TestAgentContract:
    def test_a_kernel_spec_has_none(self) -> None:
        assert RegisteredSpec("refund_order", _service()).agent_contract is None

    def test_a_declaration_with_no_agent_contract_has_none(self) -> None:
        assert RegisteredSpec("refund_order", Foreign(_service())).agent_contract is None

    def test_a_declaration_answers_its_own(self) -> None:
        contract = object()
        entry = RegisteredSpec("refund_order", ForeignWithContract(_service(), contract=contract))
        assert entry.agent_contract is contract

    def test_an_agent_contract_attribute_that_is_not_callable_is_not_read(self) -> None:
        class Holding(Foreign):
            agent_contract = "a value, not the method"

        assert RegisteredSpec("refund_order", Holding(_service())).agent_contract is None

    def test_it_is_read_only_and_not_a_field(self) -> None:
        entry = RegisteredSpec("refund_order", _service())
        with pytest.raises(AttributeError):
            entry.agent_contract = object()  # type: ignore[misc]
        with pytest.raises(TypeError, match="agent_contract"):
            RegisteredSpec("refund_order", _service(), agent_contract=object())  # type: ignore[call-arg]
