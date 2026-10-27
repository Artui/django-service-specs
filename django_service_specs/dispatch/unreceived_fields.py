"""``unreceived_fields`` - the Validator fields a service is never handed, as an answer."""

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
    """The Validator fields of ``spec`` its service takes neither by name, nor through ``data``, nor through ``**kwargs``.

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
    # A keyword nothing declared explains may be a field returned under a name
    # of its own, so then no field is answered; an untyped provider explains
    # every keyword. ``data`` is never among the sources subtracted, so a
    # service taking it, which is handed every field and a ``many`` spec's
    # every row, is never answered for one (the ``through-data`` case of
    # test_a_field_the_service_receives_is_not). One arc:
    # test_a_field_validated_under_its_alias_reaches_its_own_name_and_is_not
    # holds the difference, and
    # test_an_untyped_provider_may_fill_any_keyword_so_no_field_is_answered
    # the provider; each source the difference subtracts is held by its own
    # case of test_a_keyword_a_declared_source_explains_leaves_the_fields_answered,
    # and the fields by test_a_field_the_service_never_takes_is_answered.
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
    # A catch-all is handed ``data``, so it receives every field, a seed-named
    # one included, and is answered for none. Each part held by its own test:
    # ``takes_all`` by test_a_field_the_service_receives_is_not[through-kwargs],
    # and over ``seed_named`` by TestAFieldNamedLikeASeed's
    # test_a_service_handed_data_is_not[through-kwargs]; ``seed_named`` by
    # its test_a_service_taking_it_by_name_only_is_answered; ``named`` by
    # test_a_field_the_service_never_takes_is_answered.
    if takes_all:
        return frozenset()
    return frozenset(name for name in fields if name in seed_named or name not in named)
