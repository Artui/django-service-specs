from __future__ import annotations

from typing import Any

from django_service_specs.pool.null_progress import null_progress
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS, PoolSeeds
from django_service_specs.pool.resolve_callable_kwargs import resolve_callable_kwargs
from django_service_specs.types.progress_reporter import ProgressReporter


def base_pool(
    *,
    user: Any,
    progress: ProgressReporter | None = None,
    seeds: PoolSeeds = DEFAULT_POOL_SEEDS,
    **extra: Any,
) -> dict[str, Any]:
    """The seeds a dispatched callable's kwargs pool carries, on every transport.

    Every pool ``dispatch`` and ``adispatch`` build routes through here, so a
    spec callable that declares a seed behaves the same whichever entry point
    resolved it.

    That is a property of the pools built here, not a rule the kernel can
    enforce on its callers: this is a builder, not a gate. A transport adapter
    that assembles a pool as a dict literal of its own carries exactly the keys
    it wrote there, because ``resolve_callable_kwargs`` forwards only keys the
    pool actually has. A callable declaring a seed the literal omitted then
    raises ``TypeError`` at call time rather than running - ``progress`` most
    often, since it is the seed with a default and so the one nobody remembers.

    There is no ``request`` entry here: this is the kernel, and off HTTP there
    is no request to seed. An HTTP adapter that wants one registers it as its
    own seed through ``PoolSeeds``, the same way any other ambient value is
    added.

    ``progress`` is the caller's reporter, and defaults to ``null_progress``
    rather than to ``None``, so a declared reporter is always callable - see
    ``ProgressReporter``. Only ``None`` is replaced: a reporter that happens to
    be falsy, such as a list-backed recorder that is empty until its first
    report, is seeded as it is, where djangorestframework-services' ``or``
    would swap it for ``null_progress`` and drop every report. A seed's
    resolver sees it like any other entry.

    **An adapter that dispatches callables through this package must build its
    pool from this function**, with its own entries spread in —
    ``base_pool(user=…, **own_entries)`` — rather than restating the seeds.
    Routing those entries through ``**extra`` is also what makes a name
    collision loud: an entry called ``user`` raises ``TypeError`` here, where in
    a dict literal it would quietly outrank the value the transport
    authenticated.

    ``seeds`` is the project's own registry
    ([`PoolSeeds`][django_service_specs.pool.pool_seeds.PoolSeeds]), resolved
    into every pool this builds. It is the **supported** way to add an entry,
    and the difference from spreading one through ``**extra`` is not
    convenience: a registered name is also reserved, so dispatch refuses a spec
    that declares an argument by that name rather than letting the two meet in
    one pool. An ``**extra`` entry has no such protection. Spread an entry that
    is genuinely per-call; register one that is ambient.
    """
    pool: dict[str, Any] = {
        "user": user,
        "progress": null_progress if progress is None else progress,
        **extra,
    }
    # Every resolver binds against the pool *before* any seed is written, so the
    # result does not depend on registration order and a reader does not have to
    # know it. A seed that needs another seed's value composes the two in its own
    # resolver, which keeps that dependency written down where it applies.
    bound = dict(pool)
    for name, resolver in seeds.resolvers().items():
        if name in bound:
            raise TypeError(
                f"base_pool() got a registered pool seed {name!r} that an entry already "
                f"occupies. A seed cannot silently outrank what the caller spread in."
            )
        pool[name] = resolver(**resolve_callable_kwargs(resolver, bound))
    return pool
