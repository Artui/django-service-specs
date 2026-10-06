"""Private selector-dispatch helpers, shared across ``selectors/``.

Not exported from ``selectors/__init__.py`` — ``shape_queryset`` is the
subpackage's public surface. These are used by it, and by the dispatch core.
``call_keywords`` binds the service as well as each selector, and lives here
because ``extend_queryset`` is bound by it too, inside ``apply_shaping``.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from typing import Any, Final

from asgiref.sync import async_to_sync
from django.core.exceptions import ImproperlyConfigured
from django.db.models import QuerySet
from django.db.models.manager import BaseManager
from django.utils.translation import gettext

from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.pool.resolve_callable_kwargs import resolve_callable_kwargs
from django_service_specs.services.is_async import is_async
from django_service_specs.specs.selector_spec import SelectorSpec

_NAMED: Final = (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
"""The parameter kinds a pool fills by name, and so the only ones it can leave unfilled."""


def is_queryset(obj: Any) -> bool:
    """True for Django ``QuerySet`` objects and ``Manager`` instances.

    The one definition of a queryset-shaping target: what the shaping fields
    may be applied to, and what a RETRIEVE selector materializes from. Tested
    by type rather than by ``hasattr(…, "first")``, which would also match a
    domain object that happens to expose ``first``. ``QuerySet`` subclasses all
    pass.
    """
    return isinstance(obj, (QuerySet, BaseManager))


def materialize_retrieve(result: Any) -> Any:
    """Collapse a RETRIEVE selector's return to the single instance, or ``None``.

    The one definition of what ``kind=RETRIEVE`` means once the selector has
    run: a queryset materializes through ``.first()`` — so an author can write
    ``selector=lambda *, pk: Model.objects.filter(pk=pk)`` and still get the
    spec's shaping applied first — and anything else passes through as the
    resolved object. What each caller does with a ``None`` differs; how the
    value is arrived at does not.
    """
    return result.first() if is_queryset(result) else result


def call_selector(fn: Callable[..., Any], kwargs: dict[str, Any]) -> Any:
    """Call a selector from sync code, transparently bridging an async one.

    A selector is the one callable a ``SelectorSpec`` may make ``async def``;
    every other concept in the spec is sync-only and runs in the executor. The
    bridge keeps the sync dispatch core from ever seeing an un-awaited
    coroutine.
    """
    if is_async(fn):
        return async_to_sync(fn)(**kwargs)
    return fn(**kwargs)


def call_keywords(
    fn: Callable[..., Any], pool: Mapping[str, Any], *, fillable: frozenset[str]
) -> dict[str, Any]:
    """The keywords ``fn`` is called with, refusing a parameter the caller left unfilled.

    ``resolve_callable_kwargs`` forwards only what the pool has, so a
    parameter with no default that the call left out - an optional read the
    caller did not send, a Validator parameter the caller left out - reached
    the callable as a ``TypeError``. It is refused before the call instead, as
    ``InvalidArguments`` keyed by the parameter, in the shape check's own
    wording for an argument left out.

    **Only where a caller could have filled it.** ``fillable`` is the names
    this call site lets a caller send: a selector's ``reads``, for the
    selector and its ``extend_queryset`` alike, or the service's Validator's
    parameters the caller left out, which are none without a Validator.
    ``shape_queryset`` passes none, because a transport shaping rows itself
    bound no arguments
    (test_a_read_the_pool_lacks_is_the_callable_s_own_error). The argument
    set is closed, so any other name can never arrive - REJECT refuses it as
    unknown, IGNORE drops it - and one the caller sent and the Validator did
    not hand back under that name has already arrived. Refusing either as
    missing would ask for a value the caller cannot send or already did,
    which a client reading ``InvalidArguments`` as its own mistake retries.
    It is the declaration's error, and is left to raise as the callable's
    own ``TypeError``. Decided at the call rather than when
    the spec is declared, because a registered seed may fill such a
    parameter, and the seeds are known only at dispatch.

    A parameter is refused only if it is filled by name, has no default, is
    not in the pool, and is one a caller could fill. No reserved name needs
    excluding, because none is ever fillable: a read or Validator parameter
    named after one of the dispatcher's own is refused as it is declared or
    assembled (``check_reserved``), and one named after a registered seed by
    ``open_call`` (test_a_spec_declaring_a_registered_seed_s_name_is_refused).

    One branch to coverage, so each condition is held by its own test:
    test_a_callable_taking_the_whole_pool_is_never_missing_anything,
    test_a_positional_only_parameter_is_not_reported and
    test_a_var_positional_parameter_is_never_missing (the kind: ``**kwargs``
    takes whatever arrives, a positional-only parameter is never passed by
    name, and ``*args`` needs nothing, so no caller value fills any of them),
    test_a_defaulted_parameter_is_never_missing (the default),
    test_an_optional_read_a_selector_requires_is_refused_when_not_sent (the
    pool: without it a sent read is refused too), and
    test_a_selector_parameter_no_read_declares_is_the_author_s_error with
    test_a_service_parameter_no_validator_declares_is_the_author_s_error (the
    caller's reach).
    """
    missing = [
        name
        for name, param in inspect.signature(fn).parameters.items()
        if param.kind in _NAMED
        and param.default is inspect.Parameter.empty
        and name not in pool
        and name in fillable
    ]
    if missing:
        # Translated where it is raised, spelled as Django spells it, as the
        # shape check does: ``check_arguments`` refuses an absent required
        # argument with the same message.
        raise InvalidArguments({name: [gettext("This field is required.")] for name in missing})
    return resolve_callable_kwargs(fn, dict(pool))


def apply_shaping(
    queryset: Any,
    spec: SelectorSpec,
    pool: Mapping[str, Any],
    *,
    annotations: Mapping[str, Any] | None,
    source_label: str,
    fillable: frozenset[str],
) -> Any:
    """``shape_queryset``, with the annotations it applies named by the caller.

    ``shape_queryset`` passes the spec's own. Dispatch passes them with every
    affordance answer the spec declares beside them, built against the model
    the selector returned, so each answer rides in the one ``.annotate()`` call
    and ``extend_queryset`` sees the answers as it sees a declared annotation.
    The public function cannot build them itself: a callable condition is
    answered against the call's registered seeds, which it is not handed.

    ``extend_queryset`` is bound through ``call_keywords`` with ``fillable``,
    the names the selector beside it was bound with, so a read the caller left
    out is the same refusal whichever of the two takes it:
    test_a_read_left_out_is_refused_alike_by_whichever_callable_takes_it.
    """
    if (
        spec.select_related is None
        and spec.prefetch_related is None
        and annotations is None
        and spec.extend_queryset is None
    ):
        return queryset
    if not is_queryset(queryset):
        raise ImproperlyConfigured(
            "select_related / prefetch_related / annotations / extend_queryset "
            f"are set on the spec but {source_label} returned "
            f"{type(queryset).__name__}, which is not a Django QuerySet. Drop "
            "the shaping fields or have the callable return a QuerySet."
        )
    if spec.select_related is not None:
        queryset = queryset.select_related(*spec.select_related)
    if spec.prefetch_related is not None:
        queryset = queryset.prefetch_related(*spec.prefetch_related)
    if annotations is not None:
        queryset = queryset.annotate(**annotations)
    if spec.extend_queryset is not None:
        extend_pool = {**pool, "queryset": queryset}
        queryset = spec.extend_queryset(
            **call_keywords(spec.extend_queryset, extend_pool, fillable=fillable)
        )
    return queryset
