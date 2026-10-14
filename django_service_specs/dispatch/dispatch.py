"""``dispatch`` - run one operation, from sync code, on any transport."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django_service_specs.dispatch.dispatch_result import DispatchResult
from django_service_specs.dispatch.grant import Grant
from django_service_specs.dispatch.utils import (
    SELECTOR_SOURCE,
    conclude_selector,
    finish_service,
    lookup,
    open_call,
    overlay_for,
    prepare_service,
    refuse_target,
    selector_pool,
)
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS, PoolSeeds
from django_service_specs.services.run_service import run_service
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource
from django_service_specs.types.progress_reporter import ProgressReporter
from django_service_specs.types.unknown_arguments import UnknownArguments
from django_service_specs.types.unset import UNSET


def dispatch(
    spec: ServiceSpec | SelectorSpec | SpecSource,
    *,
    principal: Any,
    arguments: Mapping[str, Any],
    grant: Grant | None = None,
    pool_seeds: PoolSeeds = DEFAULT_POOL_SEEDS,
    unknown_arguments: UnknownArguments = UnknownArguments.REJECT,
    progress: ProgressReporter | None = None,
    target: Any = UNSET,
    extra_kwargs: Mapping[str, Any] | None = None,
    extra_input_data: Mapping[str, Any] | None = None,
) -> DispatchResult:
    """Run ``spec`` for ``principal`` with ``arguments``, in a fixed order.

    First, a deactivated principal is refused as ``PrincipalUnavailable``: an
    authenticated one whose ``is_active`` is false, with or without a
    ``grant``. One with no ``is_active`` reads as active, and anonymous goes on
    to the permission check, which decides whether anonymous may act. It is
    the rule ``resolve_principal`` and the HTTP entry points apply, so a
    principal is refused alike whichever way it reached dispatch.

    Then the same seven steps for both kinds of spec, and for ``adispatch``:

    1. [`check_arguments`][django_service_specs.parameters.check_arguments.check_arguments]
       over ``spec.parameters()`` under ``unknown_arguments``: the closed
       argument set and the shape check. It refuses no absent Validator field
       under a service spec's ``partial``, at any depth, while a ``reads``
       argument and the target's read stay required; nor a parameter a
       typed provider is annotated to fill - a read the ``kwargs`` of the
       spec declaring it fills, a Validator field ``input_data`` fills -
       which is still refused, where it is read, if the provider declines
       it. Such a parameter is the server's: a value the caller sends for it
       is checked, then dropped, so it never stands in for the provider's. A parameter a registered seed in
       ``pool_seeds`` occupies is refused before that, as a configuration error.
    2. [`authorize`][django_service_specs.dispatch.authorize.authorize],
       honouring ``grant`` if it covers this spec and principal. Before anything
       is resolved, so a refused principal learns nothing about which rows exist.
    3. Resolution: a selector spec's own selector, or a service spec's instance
       or collection selector, called with the base pool plus the arguments its
       ``reads`` declare and what its ``kwargs`` provider returns, then shaped,
       and a RETRIEVE collapsed to its row. A
       missing row is ``DispatchResult(kind="not_found")``, returned rather than
       raised, unless the selector says ``allow_none``.
    4. [`authorize_target`][django_service_specs.dispatch.authorize_target.authorize_target]
       on a retrieved row, and
       [`authorize_scope`][django_service_specs.dispatch.authorize_scope.authorize_scope]
       where no row is: on a list, a collection target's set, empty or not,
       a create's ``None``, and the ``None`` a service spec's instance
       selector lets through under its ``allow_none``. A selector spec's own ``None`` under ``allow_none`` is
       asked of neither.
    5. A service spec's Validator, on only the arguments it declares, with
       its ``input_data`` provider's values merged over the caller's, and the
       resolved target and ``partial`` in its context. Its
       [`validated()`][django_service_specs.validation.validator.Validator.validated]
       result is the call's: the values, ``data``, and what it binds.
    6. A service spec's ``affordances``, through
       [`enforce_affordances`][django_service_specs.affordances.enforce_affordances.enforce_affordances]:
       the first one not met refuses the call as ``ActionUnavailable`` carrying
       its ``code``. After the object-level check, so a principal who may not
       see the row is never told what state it is in, and before the run's
       transaction opens, so a refusal never opens one. Then its
       ``preconditions``, in declaration order, from the same pool: the
       first to raise aborts the call, and what it raises reaches the caller
       as it is.
    7. The run: the service, called with the principal, ``data`` (the
       Validator's ``data``), ``instance`` or ``collection``, each validated
       value by name, what the Validator binds, the spec's ``reads``, what its
       ``kwargs`` provider returns, ``progress`` and every registered seed, through
       [`run_service`][django_service_specs.services.run_service.run_service] so
       ``spec.atomic`` holds and an ``async def`` service is bridged. Then the
       output selector, if declared, with the service's return as ``result``.

    A selector spec stops after step four and its ``preconditions``: its
    selector is its run, and they run on what it found, never on a missing
    row. Its ``affordances`` are answers about each row, for a list to
    report, and nothing about reading is refused by them.

    **A** ``many`` **service spec takes a list of rows** under its
    ``many_argument``, beside its ``reads`` and nothing else, and runs the
    service once for all of them, inside one transaction under ``atomic``. Its
    steps differ in three places:

    - Step one checks the top level - the list, and the ``reads`` - and each
      row, but raises only the top level's refusal there. A row's refusal is
      raised in step five, beside the Validator's refusals of the other rows,
      so a principal refused in step two learns nothing about the rows it sent.
    - Steps three and four resolve nothing: the scope check is asked of
      ``None``, as for a create, never of the caller's rows.
    - Step five runs the Validator once per row, each with the
      ``input_data`` provider's values merged over it; the provider is called
      once for the call. Every row is checked and validated before the service
      runs, and every failing row is refused in one ``InvalidArguments``,
      addressed by the row's ``int`` index under ``many_argument``: a field as
      ``{"items": {2: {"title": [...]}}}``, a message about the row itself
      under ``non_field_errors`` inside the row, and the list's own refusal
      as ``{"items": [...]}``. The service receives the rows' ``data`` as a
      list under ``data``, and their values as a list under
      ``many_argument``; neither is spread by field. The ``affordances`` -
      conditions on no row, since one on the row is refused when the spec is
      declared - and the ``preconditions`` are answered once.

    ``kind`` is ``"list"`` for it, unless an output selector says otherwise
    or the service returned ``None``, which is presented as ``None``.

    ``progress`` is the transport's own progress reporter, seeded under the
    reserved name ``progress`` into the pool of whatever is this call's run -
    the service, or a selector spec's own selector - and into that spec's
    callable affordance conditions'. With none, the pool carries
    ``null_progress``, so a callable that declares the parameter runs on every
    transport. A target or output selector, and its affordance conditions,
    always get ``null_progress``: a lookup has nothing to
    report, and one reporting after the service finished would read as the
    work restarting. The run alone also reports to the spec's
    ``progress_reporter``, and only a run that takes ``progress``: called on
    the run's first report, or before an ``async def`` run once nothing before
    the run can refuse the call; either way a call refused before its run
    never calls it. A selector spec's run is its selector, and its step four
    and ``preconditions`` answer after it, so a selector spec refused there
    may already have called it: by the selector's first report, or, for an
    ``async def`` selector, before the await.

    ``target`` is a service spec's target resolved by the caller - the row
    an HTTP view's ``get_object()`` found, or what ``resolve_target``
    returned - and stands in for step three: no lookup runs, and the call's
    ``instance`` or ``collection`` is ``target``. Step four still runs on it,
    unless ``grant`` says ``target_checked``, so with that grant
    ``has_object_permission`` is asked once across both. Without ``target``
    step four runs whatever the grant says: the grant vouches for the target
    the caller found, not for what the arguments make the lookup find. So a
    selector spec, which takes no ``target``, runs it on the row or the list
    its selector found, whatever the grant says. ``None`` is a missing
    row, not-found unless the instance selector says ``allow_none``; a create
    takes ``None`` and refuses anything else. **Dispatch trusts it**: the
    target's ``reads`` are still checked as declared, and keeping them and
    ``target`` in agreement is the caller's. A selector spec refuses it.

    ``extra_kwargs`` and ``extra_input_data`` are the transport's per-call
    overlays for the spec's ``kwargs`` and ``input_data`` providers - what an
    HTTP view's per-request hooks add - merged **beneath** them, so the spec's
    own provider wins on a clash and the overlay wins over the caller's
    arguments. Each is treated as its provider's own return is: an ``UNSET``
    entry is dropped, a key the spec's provider is annotated to fill is the
    server's and the overlay's value for it is dropped too, so an overlay
    never fills a key its provider declined to. ``extra_kwargs`` naming a
    registered seed is refused, as a provider's is. ``extra_kwargs`` reaches
    a selector spec's own selector and a service spec's service, never a
    target or output selector; ``extra_input_data`` reaches the Validator,
    under every row of a ``many`` call, and a selector spec refuses it. An
    overlay relaxes nothing in step one: a parameter only it supplies is
    still the caller's to send.

    ``kind`` is ``"list"`` for a LIST selector spec, a service whose output
    selector is a LIST, or a ``many`` service with no output selector that
    returned something, and ``"instance"`` otherwise. Nothing is presented here;
    [`present`][django_service_specs.dispatch.present.present] does that, so a
    transport that hands the object to a template never pays for rendering it.

    Raises:
        PrincipalUnavailable: a deactivated principal, before step one.
        InvalidArguments: step one, or the Validator, or a parameter of a
            selector, its ``extend_queryset`` or the service that has no
            default, that a caller could have filled and that nothing in the
            call's pool did - a read declared optional and not sent, a
            Validator parameter a call that is not ``partial`` left out -
            keyed by that parameter, and the same for a precondition's. One no caller can fill, or one the caller sent and the
            Validator did not hand back under that name, raises the
            callable's own ``TypeError``.
        NotPermitted: step two or step four.
        TypeError: ``target`` on a selector spec or a ``many`` spec, or
            anything but ``None`` on a service spec that declares no target
            selector; ``extra_input_data`` on a selector spec.
        ActionUnavailable: step six, an affordance not met.
        ServiceNotFound: step six, a condition on the row reached after the row
            was deleted.
        ImproperlyConfigured: a spec that declares no permissions, a parameter,
            a validated, bound or provided value named after a seed, a bound
            value named after a validated one, any value bound for a row of a
            ``many`` call, shaping declared on a
            selector that returned something other than a queryset, a
            condition on the row with no row to answer it for, or a
            precondition answering with a coroutine or an async generator.
    """
    spec = kernel_spec(spec)
    refuse_target(spec, target)
    overlay = overlay_for(spec, extra_kwargs, extra_input_data)
    if isinstance(spec, SelectorSpec):
        checked, granted = open_call(
            spec,
            principal,
            arguments,
            grant=grant,
            pool_seeds=pool_seeds,
            unknown_arguments=unknown_arguments,
        )
        pool = selector_pool(
            spec,
            checked,
            principal=principal,
            pool_seeds=pool_seeds,
            progress=progress,
            extra_kwargs=overlay.kwargs,
        )
        value = lookup(
            spec,
            pool,
            source=SELECTOR_SOURCE,
            reserved=pool_seeds.reserved,
            run=True,
            transport=progress,
        )
        return conclude_selector(
            spec,
            value,
            principal=principal,
            grant=granted,
            pool=pool,
            reserved=pool_seeds.reserved,
            checked=checked,
        )
    prepared = prepare_service(
        spec,
        principal,
        arguments,
        grant=grant,
        pool_seeds=pool_seeds,
        unknown_arguments=unknown_arguments,
        progress=progress,
        target=target,
        overlay=overlay,
    )
    if isinstance(prepared, DispatchResult):
        return prepared
    result = run_service(spec.service, prepared.kwargs, atomic=spec.atomic)
    return finish_service(spec, prepared, result, pool_seeds=pool_seeds)
