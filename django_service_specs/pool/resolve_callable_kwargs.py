"""``resolve_callable_kwargs`` — the declare-to-receive binder."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any


def resolve_callable_kwargs(
    fn: Callable[..., Any],
    pool: dict[str, Any],
) -> dict[str, Any]:
    """Pick the subset of ``pool`` matching ``fn``'s declared parameters.

    Every pool-resolved callable in the kernel — a seed's resolver, a spec's
    ``selector``, ``extend_queryset``, a service — binds through this one rule,
    so a callable written for one entry point runs unchanged on another: it
    names what it wants and gets exactly that, or takes ``**kwargs`` for the
    whole pool.

    If ``fn`` declares ``**kwargs``, the entire pool is passed.
    Otherwise only parameters present in the signature are forwarded.
    """
    signature: inspect.Signature = inspect.signature(fn)
    params: dict[str, inspect.Parameter] = dict(signature.parameters)

    accepts_var_keyword: bool = any(
        param.kind == inspect.Parameter.VAR_KEYWORD for param in params.values()
    )
    if accepts_var_keyword:
        return dict(pool)

    declared_names: set[str] = {
        name
        for name, param in params.items()
        if param.kind
        in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        )
    }
    return {name: pool[name] for name in declared_names if name in pool}
