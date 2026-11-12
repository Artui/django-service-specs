from __future__ import annotations

import inspect

from django_service_specs.dispatch.utils import EVERY_POOL, seed_named_fields, target_entry
from django_service_specs.pool.call_seeds import CALL_SEEDS
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS, PoolSeeds
from django_service_specs.pool.provider_keys import provider_keys
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource


def unreceived_fields(
    spec: ServiceSpec | SelectorSpec | SpecSource, *, pool_seeds: PoolSeeds = DEFAULT_POOL_SEEDS
) -> frozenset[str]:
    """The Validator fields of ``spec`` its service takes neither by name, nor through ``data``, nor
    through ``**kwargs``.

    A value a caller sends for one is validated and then reaches the service
    by no route, on a mount registering ``pool_seeds``. A top-level field
    named like a registered seed or the call's ``request`` or ``view``
    reaches the service through ``data`` alone, since the name in the pool
    is the seed's, so a service taking it by name only never receives it. A
    ``many`` spec's rows reach the service as the list under
    ``many_argument``, or in ``data``, so its one field is that list. A
    service taking ``**kwargs`` is handed ``data`` with the rest, and so
    receives every field.

    **An answer, not a refusal**, because such a spec runs, and may be meant
    to: a Validator checking that ``password`` and ``confirm`` agree returns
    ``password`` alone, and its service never takes ``confirm`` on purpose.
    A transport decides what a non-empty answer means for it - refusing the
    spec where it registers it, warning, or advertising the field anyway.

    **What it cannot see, and so never answers.** A Validator may return a
    field under a name other than its parameter's - a pydantic field
    validated by its alias comes back under its own name - so a service
    taking a keyword nothing declared explains is answered for none of its
    fields
    (test_a_field_validated_under_its_alias_reaches_its_own_name_and_is_not).
    A ``kwargs`` provider whose return says nothing about its keys explains
    every keyword the same way. Nothing runs: no seed resolves and no
    provider is called.

    **Describe-time**: for a transport registering the spec, it reads the
    Validator's fields as it declares them to no call, handing one that
    declares ``call_context`` ``None``
    (test_describe_time_readers_hand_none), so a field declared only to a
    call is not answered.

    ``spec`` may be a declaration with ``as_kernel_spec()``, read as the spec
    it compiles to; a selector spec, and a service spec with no Validator,
    have no fields, and are answered with none.
    """
    spec = kernel_spec(spec)
    if not isinstance(spec, ServiceSpec) or spec.validator is None:
        return frozenset()
    params = inspect.signature(spec.service).parameters
    named = frozenset(
        name
        for name, param in params.items()
        if param.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    )
    fields = frozenset({spec.many_argument}) if spec.many else spec.validator.parameters().names()
    keys = provider_keys(spec.kwargs)
    if keys is None or named - (
        EVERY_POOL
        | pool_seeds.names
        | target_entry(spec, None).keys()
        | spec.reads.names()
        | fields
        | keys.filled
        | keys.declinable
    ):
        return frozenset()
    seed_named = seed_named_fields(spec, pool_seeds.names | CALL_SEEDS)
    takes_all = any(param.kind is inspect.Parameter.VAR_KEYWORD for param in params.values())
    if takes_all:
        return frozenset()
    return frozenset(name for name in fields if name in seed_named or name not in named)
