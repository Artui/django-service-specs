"""Static typing contract for the mutation helpers.

The mutation helpers thread a ``ModelT = TypeVar("ModelT", bound=Model)``
through their signatures so callers that pass a concrete model class get a
``ChangeResult[SomeModel]`` back instead of a bare ``ChangeResult``.

We can't observe a TypeVar's resolution at runtime (it's erased to its
bound), but we can lock in the *shape* — the return is ``ChangeResult[T]``
parametrised by the same TypeVar declared in :mod:`change_result` — using
``typing.get_type_hints``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, get_args, get_origin, get_type_hints

import pytest

from django_service_specs.mutations.acreate_from_input import acreate_from_input
from django_service_specs.mutations.aupdate_from_input import aupdate_from_input
from django_service_specs.mutations.change_result import ChangeResult, ModelT
from django_service_specs.mutations.create_from_input import create_from_input
from django_service_specs.mutations.update_from_input import update_from_input
from tests.relations_app.models import Author


class TestMutationHelperReturnTypes:
    @pytest.mark.parametrize(
        "helper",
        [
            pytest.param(create_from_input, id="create_from_input"),
            pytest.param(update_from_input, id="update_from_input"),
            pytest.param(acreate_from_input, id="acreate_from_input"),
            pytest.param(aupdate_from_input, id="aupdate_from_input"),
        ],
    )
    def test_returns_change_result_of_model_t(self, helper: Callable[..., Any]) -> None:
        return_hint = get_type_hints(helper)["return"]
        assert get_origin(return_hint) is ChangeResult
        assert get_args(return_hint) == (ModelT,)


class TestMutationHelperModelParameter:
    @pytest.mark.parametrize(
        "helper",
        [
            pytest.param(create_from_input, id="create_from_input"),
            pytest.param(acreate_from_input, id="acreate_from_input"),
        ],
    )
    def test_model_is_type_of_model_t(self, helper: Callable[..., Any]) -> None:
        model_hint = get_type_hints(helper)["model"]
        assert get_origin(model_hint) is type
        assert get_args(model_hint) == (ModelT,)

    @pytest.mark.parametrize(
        "helper",
        [
            pytest.param(update_from_input, id="update_from_input"),
            pytest.param(aupdate_from_input, id="aupdate_from_input"),
        ],
    )
    def test_instance_is_model_t(self, helper: Callable[..., Any]) -> None:
        instance_hint = get_type_hints(helper)["instance"]
        assert instance_hint is ModelT


class TestChangeResultGeneric:
    def test_change_result_is_generic_over_model_t(self) -> None:
        instance_hint = get_type_hints(ChangeResult)["instance"]
        assert instance_hint is ModelT

    def test_parametrised_change_result_round_trips(self) -> None:
        """``ChangeResult[ConcreteModel]`` evaluates and exposes the arg."""
        parametrised = ChangeResult[Author]
        assert get_origin(parametrised) is ChangeResult
        assert get_args(parametrised) == (Author,)
