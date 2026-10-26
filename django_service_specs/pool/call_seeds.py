"""``CALL_SEEDS`` - the call's ``request`` and ``view``, for every callable dispatch binds."""

from __future__ import annotations

from typing import Final

CALL_SEEDS: Final[frozenset[str]] = frozenset({"request", "view"})
"""The names dispatch reads off the call's context for every callable naming one.

``request`` is the Django ``HttpRequest`` the call arrived on and ``view`` the
view serving it, each the very object the transport put in ``call_context``
under that key, and ``None`` where it put none: off HTTP there is no request,
and code reading one learns that from the ``None``
(test_with_neither_key_in_the_context_every_stage_is_handed_none). A spec
callable written for HTTP declares both, so a spec serves unchanged from every
transport only if every stage can be handed them.

**Handed by name only.** Every stage dispatch resolves - a seed's resolver,
the selectors, the target selector on every route included, the providers, a
``FormValidator``'s ``form_kwargs``, the affordance conditions, the
preconditions, the run's ``progress_reporter``, the service and the output
selector - is handed either name it declares, and so is every permission
check that declares one. A ``**kwargs`` catch-all is handed neither, and
neither is a pool entry, so the Validator's ``ambient`` holds neither, as the
call's context itself is handled (test_a_catch_all_is_handed_neither,
test_the_validator_s_ambient_holds_neither).

**Outside** ``RESERVED_POOL_SEEDS``, so ``PoolSeeds.extend`` and the
constructor both accept a registration under either name, as the transports
released before the kernel supplied them make one. Such a mount keeps its own:
the registered seed is a pool entry, the value at every stage and every check,
and reaches a catch-all as any seed does
(test_the_registered_seed_supplies_the_name,
test_a_registered_view_still_reaches_a_catch_all).

**Outside** ``PoolSeeds.reserved`` as well, which keeps its published answer
for the transports that read it. Dispatch refuses a spec parameter of either
name on every mount all the same (test_a_parameter_named_either_is_refused),
and a ``kwargs`` provider's or an ``extra_kwargs`` key of either name
(test_a_provider_returning_request_is_refused,
test_an_overlay_key_named_either_is_refused). Two are not refused. A read
reflected off a selector's signature is filled with the call's value, as one
named like a registered seed is filled with the seed's
(test_a_reflected_read_named_either_is_the_call_s). A top-level Validator
field of either name is the caller's: it validates into ``data`` and never
reaches the service under the name, as a field named like a registered seed
(test_a_validator_field_named_request_takes_the_seat). A value of either name
that a Validator returns without declaring it, or binds for the call, is
refused, as a provider's is, since it would outrank the context's
(test_a_validator_returning_either_is_refused,
test_a_validator_binding_either_is_refused). A transport refusing a
caller's argument by these names reads this set.
"""
