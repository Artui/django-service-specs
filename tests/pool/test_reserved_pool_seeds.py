from __future__ import annotations

from typing import Any

import pytest
from django import forms
from django.core.exceptions import ImproperlyConfigured

from django_service_specs.adapters.forms.form_validator import FormValidator
from django_service_specs.authorization.unrestricted import Unrestricted
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.parameters.parameters import Parameter, Parameters
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS
from django_service_specs.pool.reserved_pool_seeds import RESERVED_POOL_SEEDS
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.selector_kind import SelectorKind

CALL_CONTEXT = Parameters.of(Parameter("call_context", "object"))


def test_the_call_s_context_is_a_name_dispatch_owns() -> None:
    assert "call_context" in RESERVED_POOL_SEEDS


@pytest.mark.parametrize(
    "declare",
    [
        lambda: ServiceSpec(service=print, reads=CALL_CONTEXT),
        lambda: SelectorSpec(kind=SelectorKind.LIST, selector=list, reads=CALL_CONTEXT),
    ],
    ids=["service-spec", "selector-spec"],
)
def test_a_parameter_named_call_context_is_refused(declare: object) -> None:
    """A caller's argument may never stand in for the transport's dict."""
    with pytest.raises(ImproperlyConfigured, match="call_context"):
        declare()  # ty: ignore[call-non-callable]


def test_a_seed_named_call_context_is_refused() -> None:
    with pytest.raises(ValueError, match="call_context"):
        DEFAULT_POOL_SEEDS.extend(call_context=dict)


SHAPES = Parameters.of(Parameter("shapes", "string"))


class _ShapesForm(forms.Form):
    shapes = forms.CharField()


class _TitleForm(forms.Form):
    title = forms.CharField()


@pytest.mark.parametrize(
    "declare",
    [
        lambda: ServiceSpec(service=print, reads=SHAPES),
        lambda: ServiceSpec(service=print, shapes=SHAPES),
        lambda: SelectorSpec(kind=SelectorKind.LIST, selector=list, reads=SHAPES),
        lambda: SelectorSpec(kind=SelectorKind.LIST, selector=list, shapes=SHAPES),
        lambda: ServiceSpec(
            service=print, many=True, many_argument="shapes", validator=FormValidator(_TitleForm)
        ),
        lambda: ServiceSpec(service=print, validator=FormValidator(_ShapesForm)).parameters(),
    ],
    ids=[
        "service-spec-read",
        "service-spec-shape",
        "selector-spec-read",
        "selector-spec-shape",
        "many-argument",
        "validator-field",
    ],
)
def test_a_parameter_named_shapes_is_refused_with_the_rename(declare: object) -> None:
    """The seed's name: an argument by it would meet the call's shape values in one pool."""
    with pytest.raises(ImproperlyConfigured, match="reserved for the seed") as refused:
        declare()  # ty: ignore[call-non-callable]
    assert "rename" in str(refused.value)
    assert "'shapes'" in str(refused.value)


def test_a_seed_named_shapes_is_refused_with_the_rename() -> None:
    with pytest.raises(ValueError, match="reserved for the seed") as refused:
        DEFAULT_POOL_SEEDS.extend(shapes=dict)
    assert "rename" in str(refused.value)


@pytest.mark.parametrize(
    ("provider", "extra"),
    [
        (lambda: {"shapes": "q"}, None),
        (None, {"shapes": "q"}),
    ],
    ids=["provider", "overlay"],
)
def test_a_provider_or_overlay_naming_shapes_is_refused(
    provider: Any, extra: dict[str, Any] | None, django_user_model: Any
) -> None:
    """Neither may stand in for the seed: the selector would read the author's value as the call's."""
    spec = SelectorSpec(
        kind=SelectorKind.LIST,
        selector=lambda: [],
        permissions=[Unrestricted()],
        kwargs=provider,
    )
    with pytest.raises(ImproperlyConfigured, match="shapes"):
        dispatch(spec, principal=django_user_model(), arguments={}, extra_kwargs=extra)


def test_a_parameter_named_call_context_is_refused_without_the_shapes_rename() -> None:
    """The rename is the one name's, so another refusal never points at ``shapes``."""
    with pytest.raises(ImproperlyConfigured) as declared:
        ServiceSpec(service=print, reads=CALL_CONTEXT)
    with pytest.raises(ValueError) as registered:
        DEFAULT_POOL_SEEDS.extend(call_context=dict)
    assert "reserved for the seed" not in str(declared.value)
    assert "reserved for the seed" not in str(registered.value)
