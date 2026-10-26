"""``check_call`` - whether ``dispatch`` would let a call start, without starting it."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django_service_specs.dispatch.grant import Grant
from django_service_specs.dispatch.utils import CheckKeywords, open_call
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS, PoolSeeds
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource
from django_service_specs.types.unknown_arguments import UnknownArguments


def check_call(
    spec: ServiceSpec | SelectorSpec | SpecSource,
    *,
    principal: Any,
    arguments: Mapping[str, Any],
    grant: Grant | None = None,
    pool_seeds: PoolSeeds = DEFAULT_POOL_SEEDS,
    unknown_arguments: UnknownArguments = UnknownArguments.REJECT,
    call_context: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], Grant]:
    """``dispatch``'s prelude, run alone: the checked arguments and the grant, or its refusal.

    For a transport that answers a call before it runs - a task queue
    refusing at enqueue what the worker's ``dispatch`` would refuse before it
    resolves anything. Only that: no lookup runs, so no object or scope
    check, no Validator, no affordance and no precondition, and a call this
    passes may still be refused by ``dispatch`` at any of those
    (test_a_scope_check_is_left_to_dispatch). The steps are
    [`dispatch`][django_service_specs.dispatch.dispatch.dispatch]'s own, in
    its order, and the same function runs them for both, so the two cannot
    drift apart:

    1. A deactivated principal is refused as ``PrincipalUnavailable``, with
       or without a ``grant``.
    2. A parameter a registered seed in ``pool_seeds`` is named like, or
       one named ``request`` or ``view`` on any mount, is answered as
       dispatch answers it: a ``reflected`` read leaves the argument set, a
       top-level Validator field stays in it, and anything else is refused
       as ``ImproperlyConfigured``.
    3. [`check_arguments`][django_service_specs.parameters.check_arguments.check_arguments]
       under ``unknown_arguments``, relaxed exactly as dispatch relaxes it: a
       parameter a provider fills or may fill - a typed provider's filled and
       declinable keys, and every parameter an untyped provider's values
       reach - and a Validator field under ``partial``. No provider runs
       here, so a call this passes without such a value may still be refused
       by ``dispatch`` where the provider's answer is merged
       (test_check_call_relaxes_a_may_fill_read).
    4. [`authorize`][django_service_specs.dispatch.authorize.authorize],
       honouring ``grant`` if it covers this spec and principal.

    The keywords are ``dispatch``'s, less what only a run reads. The kernel's
    own steps run no query; a project's ``PermissionCheck`` may.

    It returns the checked arguments and the grant the call ran under, which
    ``dispatch`` honours for the same spec and principal, so the
    class-level check is not asked twice. **A** ``many`` **spec's rows** come
    back as a list of checked rows under ``many_argument``, and a refused row
    is raised here, after step four, in the tree ``dispatch`` raises it in -
    though ``dispatch`` reports it beside the Validator's refusals of the
    other rows, and this runs no Validator.

    It is the complement of
    [`bind_arguments`][django_service_specs.dispatch.bind_arguments.bind_arguments]:
    this authorizes and does not validate, and ``bind_arguments`` validates
    and does not authorize. Neither resolves a target; for a service spec
    that acts on a row,
    [`resolve_target`][django_service_specs.dispatch.resolve_target.resolve_target]
    finds and checks it.

    ``spec`` may be a declaration with ``as_kernel_spec()``, read as the spec
    it compiles to, and the grant is for that compiled spec, which the same
    object answers on every later call.

    ``call_context`` is offered to the checks as ``dispatch`` offers it, the
    very dict passed, or a fresh one; a check naming a registered seed is
    handed it, resolved as dispatch resolves it before the class-level check.

    Raises:
        PrincipalUnavailable: step one.
        ImproperlyConfigured: step two, or a spec that declares no
            permissions.
        InvalidArguments: step three, or a refused row of a ``many`` call.
        NotPermitted: step four.
        ValueError: ``unknown_arguments`` is no policy, ``PASSTHROUGH``
            included.
    """
    return open_call(
        kernel_spec(spec),
        principal,
        arguments,
        grant=grant,
        pool_seeds=pool_seeds,
        unknown_arguments=unknown_arguments,
        settle_rows=True,
        keywords=CheckKeywords({} if call_context is None else call_context),
    )
