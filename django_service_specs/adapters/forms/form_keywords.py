from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from django_service_specs.adapters.forms.form_validator import FormValidator
from django_service_specs.adapters.forms.utils import extra_keywords
from django_service_specs.authorization.utils import refuse_deactivated, resolved_seeds
from django_service_specs.dispatch.utils import target_entry
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS, PoolSeeds
from django_service_specs.pool.resolve_callable_kwargs import resolve_callable_kwargs
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource
from django_service_specs.validation.validation_context import ValidationContext


def form_keywords(
    spec: ServiceSpec | SelectorSpec | SpecSource,
    principal: Any,
    *,
    pool_seeds: PoolSeeds | None = None,
    target: Any = None,
    call_context: dict[str, Any] | None = None,
) -> Mapping[str, Any]:
    """What ``spec``'s FormValidator's ``form_kwargs`` returns."""
    spec = kernel_spec(spec)
    if not (isinstance(spec, ServiceSpec) and isinstance(spec.validator, FormValidator)):
        found = getattr(spec, "validator", None)
        has = "no Validator" if found is None else f"a {type(found).__name__}"
        raise TypeError(
            "form_keywords() reads a ServiceSpec validated by a FormValidator; "
            f"this {type(spec).__name__} has {has}."
        )
    validator = spec.validator
    if validator.form_kwargs is None:
        return {}
    registry = DEFAULT_POOL_SEEDS if pool_seeds is None else pool_seeds
    named = frozenset(resolve_callable_kwargs(validator.form_kwargs, dict.fromkeys(registry.names)))
    if named:
        refuse_deactivated(principal)
    context = ValidationContext(
        principal,
        target,
        ambient=MappingProxyType(
            resolved_seeds(registry, named, user=principal, call_context=call_context)
        ),
        resolved=MappingProxyType(target_entry(spec, target)),
        call_context={} if call_context is None else call_context,
    )
    return extra_keywords(validator.form_class, validator.form_kwargs, context)
