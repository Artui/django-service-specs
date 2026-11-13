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
    """What ``spec``'s FormValidator's ``form_kwargs`` returns, for a transport building the form.

    A page shows the form before the call runs, so it builds the form itself,
    and a form whose ``__init__`` takes a keyword of its own needs what
    dispatch would hand it. This calls ``form_kwargs`` from the pool dispatch
    binds it from, through the same code
    [`FormValidator`][django_service_specs.adapters.forms.form_validator.FormValidator]
    calls it with, so the returned mapping is checked as there: one that is
    not a mapping, or that returns ``data``, ``files`` or ``instance``, which
    only the bind may set, is refused with ``ImproperlyConfigured``. Spread it
    beside those three: ``form_class(data=..., **form_keywords(...))``.

    The pool holds:

    - ``user``, the principal;
    - ``progress``, the no-op reporter, since no call is running;
    - the registered seeds of ``pool_seeds`` that ``form_kwargs`` would be
      handed, resolved once for the principal, and no other: the seeds it
      names, or every seed for one taking ``**kwargs``, as on dispatch;
    - ``call_context``, the dict handed here, or a fresh one; a page hands the
      dict it will hand dispatch, so what the two calls write is shared;
    - ``request`` and ``view``, read off that context, ``None`` for a key it
      lacks, as in every pool dispatch builds, unless ``pool_seeds`` registers
      the name, whose seed is the value then; and a seed's resolver may declare
      either;
    - ``target`` under the name dispatch hands it by: ``instance`` for a spec
      with an instance selector, ``collection`` for one with a collection
      selector, and nothing for a create.

    A deactivated principal resolves no seed, as on dispatch, which refuses one
    before any resolver runs: where a seed would be resolved for one, this raises
    ``PrincipalUnavailable`` first. A call that resolves none - no ``pool_seeds``,
    or a ``form_kwargs`` naming no registered seed - is asked as ever.

    A spec whose Validator is not a ``FormValidator`` is refused with
    ``TypeError``, as ``resolve_target`` refuses a spec it cannot answer for:
    a page wired to a spec it cannot build a form for is the caller's mistake,
    and an empty answer would hide it. A ``FormValidator`` with no
    ``form_kwargs`` returns ``{}``, resolving nothing.

    It neither authorizes nor resolves the target: a page admits the
    principal with
    [`authorize`][django_service_specs.dispatch.authorize.authorize] and
    finds the row with
    [`resolve_target`][django_service_specs.dispatch.resolve_target.resolve_target]
    first. It is sync, and ``form_kwargs`` may query, so an async caller hops
    once with ``sync_to_async``.
    """
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
