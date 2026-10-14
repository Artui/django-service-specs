"""``check_call`` - whether ``dispatch`` would let a call start, without starting it."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django_service_specs.authorization.grant import Grant
from django_service_specs.dispatch.utils import open_call
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS, PoolSeeds
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource, kernel_spec
from django_service_specs.validation.unknown_arguments import UnknownArguments


def check_call(
    spec: ServiceSpec | SelectorSpec | SpecSource,
    *,
    principal: Any,
    arguments: Mapping[str, Any],
    grant: Grant | None = None,
    pool_seeds: PoolSeeds = DEFAULT_POOL_SEEDS,
    unknown_arguments: UnknownArguments = UnknownArguments.REJECT,
) -> tuple[dict[str, Any], Grant]:
    """``dispatch``'s prelude, run alone: the checked arguments and the grant, or its refusal.

    For a transport that answers a call before it runs - a task queue
    refusing at enqueue what the worker's ``dispatch`` would refuse, rather
    than accepting a job that can only fail. The steps are
    [`dispatch`][django_service_specs.dispatch.dispatch.dispatch]'s own, in
    its order, and the same function runs them for both, so the two cannot
    drift apart:

    1. A deactivated principal is refused as ``PrincipalUnavailable``, with
       or without a ``grant``.
    2. A parameter a registered seed in ``pool_seeds`` occupies is refused as
       ``ImproperlyConfigured``.
    3. [`check_arguments`][django_service_specs.parameters.check_arguments.check_arguments]
       under ``unknown_arguments``, relaxed exactly as dispatch relaxes it: a
       parameter a typed provider fills, and a Validator field under
       ``partial``.
    4. [`authorize`][django_service_specs.authorization.authorize.authorize],
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
    )
