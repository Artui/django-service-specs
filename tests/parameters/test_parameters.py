from __future__ import annotations

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_service_specs.parameters.parameter import Parameter
from django_service_specs.parameters.parameters import Parameters

PK = Parameter("pk", "integer", required=True)
TITLE = Parameter("title", "string")


def test_any_iterable_is_stored_as_an_ordered_tuple() -> None:
    params = Parameters([PK, TITLE])
    assert params.items == (PK, TITLE)
    assert list(params) == [PK, TITLE]
    assert len(params) == 2
    assert Parameters.of(PK, TITLE) == params


def test_names_and_get() -> None:
    params = Parameters.of(PK, TITLE)
    assert params.names() == frozenset({"pk", "title"})
    assert params.get("title") is TITLE
    assert params.get("missing") is None


def test_add_concatenates_in_order() -> None:
    assert (Parameters.of(PK) + Parameters.of(TITLE)).items == (PK, TITLE)


def test_a_name_declared_twice_is_refused_at_construction() -> None:
    with pytest.raises(ImproperlyConfigured, match=r"\['pk'\] more than once"):
        Parameters.of(PK, Parameter("pk", "string"))


def test_a_name_two_sources_declare_is_refused_at_add() -> None:
    with pytest.raises(ImproperlyConfigured, match=r"\['pk'\] are declared by two sources"):
        Parameters.of(PK) + Parameters.of(Parameter("pk", "string"))
