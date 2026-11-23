from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from typing_extensions import TypedDict

from django_service_specs import route_captures as exported
from django_service_specs.authorization.unrestricted import Unrestricted
from django_service_specs.parameters.parameters import Parameter, Parameters
from django_service_specs.specs.route_captures import route_captures
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.server_owned_keys import server_owned_keys
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.selector_kind import SelectorKind
from tests.dispatch.utils import A_CALL, DeclaredToACall
from tests.specs.utils import PK, Foreign, Titled

OPEN = [Unrestricted()]


class _Team(TypedDict):
    team_id: int


def _team() -> _Team:
    return {"team_id": 1}


def _target(**declaration: Any) -> SelectorSpec:
    return SelectorSpec(kind=SelectorKind.RETRIEVE, selector=list, reads=PK, **declaration)


def _org() -> ServiceSpec:
    return ServiceSpec(
        service=print,
        permissions=OPEN,
        reads=Parameters.of(Parameter("org", "string", required=True)),
        shapes=Parameters.of(Parameter("fields", "string")),
        validator=Titled("title", "id"),
        instance_selector_spec=_target(),
    )


def _split(spec: Any, captured: Mapping[str, Any], **kwargs: Any) -> tuple[set[str], set[str]]:
    arguments, namesakes = route_captures(spec, captured, **kwargs)
    return set(arguments), set(namesakes)


@pytest.mark.parametrize("name", ["org", "pk", "fields"], ids=["read", "target-read", "shape"])
def test_a_capture_naming_a_declared_parameter_is_an_argument(name: str) -> None:
    assert _split(_org(), {name: "x"}) == ({name}, set())


def test_a_capture_named_like_a_validator_field_is_a_namesake_and_no_argument() -> None:
    assert _split(_org(), {"id": 42}) == (set(), {"id"})


def test_a_capture_naming_neither_is_in_neither_set() -> None:
    assert _split(_org(), {"slug": "x"}) == (set(), set())


def test_one_route_splits_into_all_three() -> None:
    captured = {"org": "acme", "pk": 4, "id": 42, "slug": "x"}
    assert _split(_org(), captured) == ({"org", "pk"}, {"id"})


def test_it_reads_names_only_so_a_list_of_them_splits_the_same() -> None:
    assert _split(_org(), ["org", "id"]) == ({"org"}, {"id"})


def test_a_selector_spec_has_no_namesake() -> None:
    spec = SelectorSpec(kind=SelectorKind.RETRIEVE, selector=list, permissions=OPEN, reads=PK)
    assert _split(spec, {"pk": 1, "id": 2}) == ({"pk"}, set())


def test_a_spec_source_splits_as_the_spec_it_compiles_to() -> None:
    assert _split(Foreign(_org()), {"org": "a", "id": 1}) == ({"org"}, {"id"})


def test_a_field_declared_only_to_a_call_is_a_namesake_under_that_call_alone() -> None:
    spec = ServiceSpec(
        service=print, permissions=OPEN, validator=DeclaredToACall(Parameter("extra", "string"))
    )
    assert _split(spec, {"extra": 1}) == (set(), set())
    assert _split(spec, {"extra": 1}, call_context=A_CALL) == (set(), {"extra"})


def _many(**declaration: Any) -> ServiceSpec:
    return ServiceSpec(
        service=print, permissions=OPEN, many=True, validator=Titled("title", "org"), **declaration
    )


def test_a_many_spec_s_row_field_is_a_namesake() -> None:
    assert _split(_many(), {"title": "x"}) == (set(), {"title"})


def test_a_many_spec_s_read_wins_over_a_row_field_of_its_name() -> None:
    spec = _many(reads=Parameters.of(Parameter("org", "string", required=True)))
    assert _split(spec, {"org": "acme", "title": "x"}) == ({"org"}, {"title"})


def test_a_capture_naming_a_many_spec_s_list_is_refused() -> None:
    with pytest.raises(ImproperlyConfigured, match=r"captures items.*the caller's list"):
        route_captures(_many(), {"items": "x"})


def test_a_mapping_onto_a_validator_field_is_refused_naming_both() -> None:
    with pytest.raises(ImproperlyConfigured, match=r"maps the capture hashid onto id, .* field"):
        route_captures(_org(), {"hashid": 1}, mapped={"hashid": "id"})


def test_an_identity_mapping_onto_a_field_is_refused_whatever_the_route_captured() -> None:
    with pytest.raises(ImproperlyConfigured, match=r"maps the capture id onto id"):
        route_captures(_org(), {}, mapped={"id": "id"})


def test_a_mapping_onto_a_read_or_to_none_stands() -> None:
    mapped = {"organisation": "org", "id": None}
    assert _split(_org(), {"org": "a"}, mapped=mapped) == ({"org"}, set())


def test_the_capture_rule_names_what_the_provider_rule_names() -> None:
    # The target's ``kwargs`` key named like a field is a namesake to both readers.
    spec = ServiceSpec(
        service=print,
        permissions=OPEN,
        validator=Titled("team_id"),
        instance_selector_spec=_target(kwargs=_team),
    )
    assert "team_id" not in server_owned_keys(spec)
    assert _split(spec, {"team_id": 7}) == (set(), {"team_id"})


def test_the_package_root_exports_it() -> None:
    assert exported is route_captures


def test_a_service_spec_with_no_validator_has_no_namesake() -> None:
    spec = ServiceSpec(service=print, permissions=OPEN, reads=PK)
    assert _split(spec, {"pk": 1, "id": 2}) == ({"pk"}, set())
