"""``resolve_callable_kwargs`` — the declare-to-receive binder."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from django_service_specs.types.utils import BY_NAME_ONLY_POOL_NAMES


def resolve_callable_kwargs(
    fn: Callable[..., Any],
    pool: dict[str, Any],
) -> dict[str, Any]:
    """Pick the subset of ``pool`` matching ``fn``'s declared parameters.

    Every pool-resolved callable in the kernel — a seed's resolver, a spec's
    ``selector``, ``extend_queryset``, a service — binds through this one rule,
    so a callable written for one entry point runs unchanged on another: it
    names what it wants and gets exactly that, or takes ``**kwargs`` for the
    rest of the pool, which is every entry but the call's context.

    If ``fn`` declares ``**kwargs``, the entire pool is passed, except a name
    handed by name only (``BY_NAME_ONLY_POOL_NAMES``, the call's context),
    which reaches a catch-all only where it also names it. Otherwise only
    parameters present in the signature are forwarded.
    """
    params = inspect.signature(fn).parameters.values()
    named = [
        param.name
        for param in params
        if param.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    ]
    if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in params):
        # Two disjuncts, each held in tests/pool/test_resolve_callable_kwargs.py:
        # test_a_catch_all_is_never_handed_it fails without the first, and
        # test_a_catch_all_naming_it_is_handed_the_very_dict without the second.
        return {
            name: value
            for name, value in pool.items()
            if name not in BY_NAME_ONLY_POOL_NAMES or name in named
        }
    return {name: pool[name] for name in named if name in pool}
