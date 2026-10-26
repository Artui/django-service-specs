"""``RESERVED_POOL_SEEDS`` - the keyword names dispatch owns."""

from __future__ import annotations

from typing import Final

RESERVED_POOL_SEEDS: Final[frozenset[str]] = frozenset(
    {
        "user",
        "data",
        "instance",
        "collection",
        "result",
        "queryset",
        "progress",
        "call_context",
        "shapes",
    }
)
"""The names dispatch seeds into a callable's keyword pool, which no argument may use.

``user`` is the principal, ``progress`` the caller's progress reporter,
``data`` the validated values, ``instance`` and ``collection`` the resolved
target, ``result`` the service's return (in an output selector's pool, where
``instance`` is that return too, as djangorestframework-services binds it) and
``queryset`` what ``extend_queryset`` shapes. ``call_context`` is the call's
context: the one plain ``dict`` the transport handed ``dispatch``, or a fresh
one per call when it handed none, which every callable dispatch resolves -
a ``kwargs`` or ``input_data`` provider, a selector and its
``extend_queryset``, an affordance condition,
a precondition, the service, the run's ``progress_reporter`` - receives as
the same object by naming it, and never through ``**kwargs``. Never a copy,
and the kernel writes nothing to it. Seed resolvers do not see it: a seed is resolved before anything the
call adds. ``shapes`` is what the caller sent for the spec's declared
``shapes``, keyed by shape name and read-only: the mapping
``PresentationContext.shapes`` holds, so a selector that eager-loads by the
query its presenter renders reads the value the presenter reads. It is in
the pools dispatch builds for a spec's callables: a selector and its
``extend_queryset``, a ``kwargs`` or ``input_data`` provider, a
precondition, the service, the run's ``progress_reporter``, and a service
spec's output selector. A service spec's target selector is handed an empty
mapping instead, on every route, because ``resolve_target`` checks only the
target's own parameters and the lookup must find the same row either way
(test_a_target_selector_is_handed_no_shapes_on_any_route). It is an empty
mapping on a spec declaring no shapes, and, like ``call_context``, it is handed only to a
callable naming it, never through ``**kwargs``. Unlike ``call_context`` it
is not in an affordance condition's pool, the Validator's (a
``FormValidator``'s ``form_kwargs`` included) or a mutation helper's nested
row services', and like it, not in a seed resolver's or a ``filter_set``'s
(test_form_kwargs_naming_the_shapes_is_handed_no_seed,
test_a_seed_resolver_naming_the_shapes_is_handed_none,
test_a_filter_naming_the_shapes_is_handed_none; a helper's row services
are handed its ``**kwargs``, which
test_a_catch_all_is_never_handed_the_shapes keeps free of the seed). The seven besides those two are the names
``djangorestframework-services`` seeds for the same values, so a callable
written for it runs under this kernel unchanged.

``progress`` is in every pool, and live only where there is work to report on:
a service's run, and a selector spec's own selector. In a target or output
selector's pool it is ``null_progress``, because a lookup has nothing to
report, and one reporting after the service finished would read to a watching
client as the work restarting.

A parameter declaring one of these names is refused, because a spread argument
must never be able to outrank the value dispatch seeded - a caller naming
itself ``user`` is the case that matters. ``request`` and ``view`` are not here:
they are an HTTP adapter's, and it registers them through ``PoolSeeds``, which
reserves them the same way.
"""
