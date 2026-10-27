"""``seed_named_parameters`` - the parameters a seed or the call's seat fills, and those dispatch refuses."""

from __future__ import annotations

from django_service_specs.dispatch.utils import split_seed_named
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS, PoolSeeds
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource


def seed_named_parameters(
    spec: ServiceSpec | SelectorSpec | SpecSource, *, pool_seeds: PoolSeeds = DEFAULT_POOL_SEEDS
) -> tuple[frozenset[str], frozenset[str]]:
    """Of ``spec``'s parameters named like a seed ``pool_seeds`` registers or the call's own: those filled, and those refused.

    The answer ``dispatch`` gives before it reads a call's arguments, read
    alone, so a transport can give it when it registers the spec rather than
    on every call. A parameter shares a name when a seed ``pool_seeds``
    registers is named so, or it is ``request`` or ``view``, which dispatch
    hands every callable from the call's context. Of those names:

    - **the first set** is the ``reflected`` reads - a selector spec's, a
      target selector's or a service spec's - which the seed, or the call's
      own value, fills: no caller sends one, so a transport's schema leaves
      it out;
    - **the second set** is what dispatch refuses as ``ImproperlyConfigured``
      on every call: a read nobody marked, a shape, a ``many`` spec's list.
      A read or a shape named ``request`` or ``view`` nobody marked is
      refused when the spec is built, so of those two names only a ``many``
      spec's list ever reaches this set;
    - a top-level Validator field is the caller's, validated into ``data``,
      and in neither set.

    The same reader dispatch answers by
    (test_it_is_the_answer_dispatch_gives), so the two cannot drift.
    [`check_seeds`][django_service_specs.dispatch.check_seeds.check_seeds]
    refuses the second set, beside the other declarations no call can run.

    ``spec`` may be a declaration with ``as_kernel_spec()``, read as the spec
    it compiles to.
    """
    spec = kernel_spec(spec)
    return split_seed_named(spec, spec.parameters(), pool_seeds)
