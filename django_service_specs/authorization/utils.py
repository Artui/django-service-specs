"""Helpers shared by everything that decides whether a principal may act at all.

``asked_with`` is read by the three ``authorize`` functions, so the
class-level, object-level and scope-level checks cannot disagree about which
check is handed the call's arguments, its context or a seed.
``seeds_for_checks`` is read by them and by dispatch, so a transport handing
one ``pool_seeds`` resolves a check's seeds exactly as dispatch would, and
``refuse_deactivated`` by them, dispatch, ``form_keywords`` and
``bind_arguments`` handed ``pool_seeds``, so none of them
runs a resolver for a principal dispatch refuses."""

from __future__ import annotations

import inspect
import weakref
from collections.abc import Callable, Iterable, Mapping
from types import FunctionType, MappingProxyType
from typing import Any, Final

from django_service_specs.authorization.is_deactivated import is_deactivated
from django_service_specs.authorization.principal_unavailable import PrincipalUnavailable
from django_service_specs.pool.base_pool import base_pool
from django_service_specs.pool.pool_seeds import PoolSeeds
from django_service_specs.pool.utils import call_entries, only_seeds


def asked_with(
    check: Any,
    method: str,
    arguments: Mapping[str, Any] | None,
    *,
    positional: int = 2,
    offered: Mapping[str, Any] = MappingProxyType({}),
) -> dict[str, Any]:
    """The keywords to ask ``check``'s ``method`` with: those of ``arguments`` and ``offered`` it declares.

    The base ``PermissionCheck`` methods declare no keyword, so every check
    written without one keeps its signature and stays a valid override; a
    method that wants the call's arguments declares ``arguments``, one that
    wants the call's context ``call_context``, and one that wants a
    registered seed that seed's name. ``offered`` is what the call offers
    under a name - its context, and the seeds resolved for the checks - and
    only a method declaring one of its names is handed that entry.
    ``arguments`` is always the call's arguments, whatever ``offered`` holds.

    ``positional`` is how many parameters the call fills by position - two
    for ``has_permission``, three for the other two questions - and a
    parameter among them is never read as an opt-in, whatever its name: a
    check written DRF-style, ``has_permission(self, request, spec)``, under a
    transport registering ``request`` as a seed, is asked as before rather
    than handed its principal twice
    (test_a_positional_parameter_named_after_an_offered_name_is_handed_nothing).

    Read off ``getattr(check, method)``, the callable dispatch is about to
    call, so a callable set on the instance answers for itself
    (test_a_method_shadowed_on_the_instance_is_read_as_the_shadow), a mock
    patched over the method is asked as a check that never opted in
    (test_a_mock_patched_over_a_method_is_asked_as_before), a forwarding
    decorator as the method it wraps
    (test_a_forwarding_wrapper_answers_for_the_method_it_wraps), a method replaced
    after the class was defined is read as it now is
    (test_a_method_replaced_on_its_class_is_read_as_it_now_is), and an
    inherited one as its declaring class wrote it
    (test_a_subclass_inherits_the_declaration).
    """
    named = declared_keywords(check, method, positional=positional)
    asked = {name: value for name, value in offered.items() if name in named}
    if "arguments" in named:
        asked["arguments"] = arguments
    return asked


def offered_to_checks(
    call_context: dict[str, Any] | None, seeds: Mapping[str, Any] | None
) -> dict[str, Any]:
    """What a check may opt into by name besides ``arguments``: the call's context and its seeds.

    Read by the three ``authorize`` functions, so a transport calling one
    directly hands a check what dispatch would. With no ``call_context``, a
    fresh empty dict, as dispatch makes one for a call handed none: a check
    declaring it always receives a mapping it may write to
    (test_a_check_asked_with_no_call_context_gets_a_dict_of_its_own). A seed
    absent from ``seeds`` is not offered, so a check declaring it is asked
    without it. The call's ``request`` and ``view`` are offered too, read off
    the context as every callable dispatch binds reads them, ``None`` for a key it
    lacks (test_a_check_is_handed_the_context_s_request_and_none_for_an_absent_view);
    a seed registered under either name outranks them, as it does in the pools
    (test_a_seed_registered_under_the_name_outranks_the_context_s_value).
    """
    context = {} if call_context is None else call_context
    return {**call_entries(context), **(seeds or {}), "call_context": context}


# The three questions a check is asked, each with how many parameters the call
# fills by position, which no name among them can opt into.
CLASS_LEVEL: Final = ("has_permission", 2)
OBJECT_LEVEL: Final = ("has_object_permission", 3)
SCOPE_LEVEL: Final = ("has_scope_permission", 3)
QUESTIONS: Final = (CLASS_LEVEL, OBJECT_LEVEL, SCOPE_LEVEL)


def refuse_deactivated(principal: Any) -> None:
    """Raise ``PrincipalUnavailable`` for a deactivated ``principal``, as dispatch does first of all.

    Dispatch refuses one before anything else, whether or not a grant came
    with it, so no seed resolver runs for a principal that may not act. A
    caller resolving seeds itself calls this before the first resolver, by the
    same rule (``is_deactivated``) and with the same error.
    """
    if is_deactivated(principal):
        raise PrincipalUnavailable()


def check_seed_arguments(
    principal: Any,
    *,
    seeds: Mapping[str, Any] | None,
    pool_seeds: PoolSeeds | None,
    asked: str,
) -> None:
    """Refuse what an ``authorize`` function cannot honour with the seeds it was handed.

    Called first by each of the three, ahead of every short cut - a covering
    grant, a grant that checked the target - so the refusals hold for a call
    whatever else answers it, as documented.

    ``seeds`` and ``pool_seeds`` together are refused with ``TypeError``
    rather than merged, as ``base_pool`` refuses a seed meeting an entry the
    caller spread in: one would silently outrank the other
    (test_both_kinds_are_refused_before_a_covering_grant_answers, and its
    sibling in each of the other two). The guard is one ``and``-chain, and each
    conjunct has a test that fails without it: dropping ``seeds is not None``
    fails test_the_seed_the_class_level_check_names_is_resolved_for_it, which
    hands ``pool_seeds`` alone, and dropping ``pool_seeds is not None`` fails
    test_a_check_is_offered_the_call_context_and_the_seeds_it_names, which
    hands ``seeds`` alone.

    A deactivated ``principal`` handed with ``pool_seeds`` is refused with
    ``PrincipalUnavailable``, since this is where a resolver would run for it
    (test_a_deactivated_principal_resolves_no_seed, in each of the three, and
    test_a_deactivated_principal_is_refused_though_a_grant_covers_it for the
    short cuts). Without ``pool_seeds`` nothing resolves, so a call is asked
    exactly as before the keyword existed - ``authorize(spec, principal)`` from a
    transport that refuses a deactivated principal itself included
    (test_a_deactivated_principal_without_pool_seeds_is_asked_as_before, which
    fails without the ``pool_seeds is not None`` conjunct). ``asked`` names the
    function in the first refusal.
    """
    if seeds is not None and pool_seeds is not None:
        raise TypeError(
            f"{asked}() takes seeds= or pool_seeds=, not both: seeds= are values already "
            "resolved and pool_seeds= resolves them, so one would silently outrank the other."
        )
    if pool_seeds is not None:
        refuse_deactivated(principal)


def offered_seeds(
    spec: Any,
    principal: Any,
    *,
    seeds: Mapping[str, Any] | None,
    pool_seeds: PoolSeeds | None,
    question: tuple[str, int],
    call_context: Mapping[str, Any] | None,
) -> Mapping[str, Any] | None:
    """The seeds one ``authorize`` function offers its checks: ``seeds`` as handed, or resolved.

    With ``pool_seeds``, the registered seeds ``question`` names on one of
    ``spec``'s checks, resolved now (``seeds_for_checks``), and no other: a
    seed only another question names, or one no check names, is not resolved
    (test_the_seed_the_class_level_check_names_is_resolved_for_it, and each
    sibling's test_the_seed_its_question_names_is_resolved_for_it). The
    caller asks after its own short cuts - a covering grant, a grant that
    checked the target - so a call they answer resolves nothing, and after
    ``check_seed_arguments``, which has refused both kinds together and a
    deactivated principal.
    """
    if pool_seeds is None:
        return seeds
    return seeds_for_checks(spec, principal, pool_seeds, (question,), call_context=call_context)


def resolved_seeds(
    pool_seeds: PoolSeeds,
    names: frozenset[str],
    *,
    user: Any,
    call_context: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """The seeds of ``pool_seeds`` that ``names`` names, resolved for ``user``, and no other.

    What resolves a seed ahead of a call's pools, for whatever named it: a
    permission check before the class-level check (``seeds_for_checks``), and
    a form's keywords outside dispatch (``form_keywords``). A name the
    registry does not hold is skipped, so the caller passes every name its
    callable declares and only the registered ones resolve
    (test_only_the_named_seeds_resolve_and_an_unregistered_name_is_skipped). From a
    base pool with no live reporter, so a resolver reading ``progress`` sees
    the no-op one; a resolver that raises ends the call here. The pool carries
    ``call_context``, so a resolver declaring ``request`` or ``view`` reads
    the context's, as in every pool dispatch builds for its resolvers
    (test_a_seed_resolved_early_for_a_check_reads_the_request); only the
    seeds leave it.
    """
    named = names & pool_seeds.names
    resolved = base_pool(
        user=user,
        seeds=only_seeds(pool_seeds, named),
        call_context={} if call_context is None else call_context,
    )
    return {name: resolved[name] for name in named}


def seeds_for_checks(
    spec: Any,
    principal: Any,
    pool_seeds: PoolSeeds,
    questions: Iterable[tuple[str, int]],
    *,
    call_context: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """The registered seeds a check of ``spec`` names at one of ``questions``, resolved, by name.

    Resolved from a base pool with ``principal`` as ``user`` and no live
    reporter, so a resolver reads what it would at the class-level check of a
    dispatch. Dispatch asks with all three questions, before its class-level
    check; an ``authorize`` function handed ``pool_seeds`` asks with its own
    one (``offered_seeds``). A resolver that raises ends the call there, as it
    does in dispatch
    (test_a_seed_raising_principal_unavailable_ends_the_call_before_its_check).
    The call's ``request`` and ``view`` are read off ``call_context`` into that
    pool, so a resolver declaring one reads what it would in any other
    (test_a_seed_resolved_for_a_check_reads_the_context_s_request).
    """
    return resolved_seeds(
        pool_seeds,
        _named_seeds(spec, pool_seeds.names, questions),
        user=principal,
        call_context=call_context,
    )


def _named_seeds(
    spec: Any, names: frozenset[str], questions: Iterable[tuple[str, int]]
) -> frozenset[str]:
    """The registered seeds ``names`` that one of ``questions``, on one of ``spec``'s checks, names.

    Read off the same declaration ``asked_with`` hands from, so a check is
    resolved seeds exactly when it would be handed one
    (test_a_spec_whose_checks_name_a_seed_resolves_it_before_the_class_level_check),
    and a parameter filled by position is no opt-in
    (test_a_positional_parameter_named_after_a_seed_is_not_an_opt_in).
    ``arguments`` is never among them: a check naming it is handed the
    call's arguments, which outrank a seed of that name, so such a seed
    resolves as an unnamed one does
    (test_a_seed_registered_as_arguments_resolves_as_it_would_unnamed).
    """
    named = frozenset().union(
        *(
            declared_keywords(check, method, positional=positional) & names
            for check in spec.permissions or ()
            for method, positional in questions
        )
    )
    return named - {"arguments"}


def declared_keywords(check: Any, method: str, *, positional: int) -> frozenset[str]:
    """The names ``check``'s ``method`` takes by keyword, less the ``positional`` it is called with.

    What ``asked_with`` hands from, and what dispatch reads to decide whether
    a spec's checks opt into its seeds at all, so the two cannot disagree
    about which check declared one.
    """
    reached, filled = _keywords(getattr(check, method))
    return reached - frozenset(filled[:positional])


def _keywords(asked: Callable[..., Any]) -> tuple[frozenset[str], tuple[str, ...]]:
    """What ``asked`` takes by keyword, and its parameters a positional call fills, in order.

    Cached only where that is safe. A method the class defines is cached
    under the function it binds, never under the bound method, which is made
    afresh on every lookup and would hold its check for the cache's life
    (test_a_check_is_not_kept_once_asked). Any other callable is read
    uncached: one set on an instance or patched in as a mock is as
    short-lived as its check
    (test_a_callable_set_on_the_instance_is_not_kept_once_asked), and a
    callable object with ``eq`` and no hash could not be a key at all
    (test_a_callable_the_class_holds_unhashed_is_read_by_its_own_signature).
    So the test is that ``__func__`` is a plain function, not merely present:
    ``MethodType`` binds any callable, and one binding such an object would
    reach the cache with no hash
    (test_a_method_binding_a_callable_object_is_read_uncached).
    """
    function = getattr(asked, "__func__", None)
    if isinstance(function, FunctionType):
        return _function_keywords(function)
    return _reached_names(asked), _filled_by_position(asked)


# Keyed weakly on the function, so the entry goes with it: a check class a
# factory builds per call is freed with its last instance, and the cache does
# not grow with every class ever asked
# (test_a_class_built_at_runtime_is_not_kept_once_asked).
_DECLARES: Final[
    weakref.WeakKeyDictionary[FunctionType, tuple[frozenset[str], tuple[str, ...]]]
] = weakref.WeakKeyDictionary()


def _function_keywords(function: FunctionType) -> tuple[frozenset[str], tuple[str, ...]]:
    """``_keywords`` of a function a class defines, inspected once.

    A call asks each check up to three times, and checks share a class, so
    the signature is read once per function
    (test_a_class_defined_function_s_signature_is_inspected_once); it does not
    change while its function lives, and replacing the method on the class
    binds a different function, which is read afresh
    (test_a_method_replaced_on_its_class_is_read_as_it_now_is). Its first
    positional parameter is the instance the method binds, which the call
    never fills, so it is dropped from the positional ones.
    """
    keywords = _DECLARES.get(function)
    if keywords is None:
        keywords = _DECLARES[function] = (
            _reached_names(function),
            _filled_by_position(function)[1:],
        )
    return keywords


def _filled_by_position(asked: Callable[..., Any]) -> tuple[str, ...]:
    """The parameters a positional call of ``asked`` fills, in order, as Python reports them.

    The signature ``inspect`` reports, which follows the ``__wrapped__`` chain
    to the method a forwarding decorator wraps, so a wrapper spreading
    ``*args`` reports the names its positionals land in
    (test_a_forwarding_wrapper_s_positional_parameters_are_the_method_s). Up
    to the first that is not positional, since nothing after a ``*args`` or
    a keyword-only parameter is filled by position. None where there is no
    signature to read, or a ``__wrapped__`` chain that loops: nothing is
    then held back, which is how such a callable was read before.
    """
    try:
        parameters = inspect.signature(asked).parameters.values()
    except (ValueError, TypeError):
        return ()
    filled: list[str] = []
    for parameter in parameters:
        if parameter.kind not in _POSITIONAL:
            break
        filled.append(parameter.name)
    return tuple(filled)


_POSITIONAL: Final = (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)


def _reached_names(asked: Callable[..., Any]) -> frozenset[str]:
    """The names a keyword reaches in ``asked``, itself or by forwarding it.

    A walk down the ``__wrapped__`` chain ``functools.wraps`` leaves, one
    layer at a time, each read by its own signature - every layer is called
    in turn, so each must take a keyword or pass it on:

    - a name a layer takes by keyword is reached
      (test_a_forwarding_wrapper_is_handed_them_where_the_method_it_wraps_declares_them,
      test_forwarding_layers_over_an_opted_in_method_are_handed_them);
    - a layer with no ``**kwargs`` would refuse any other, so the walk ends
      there, whatever lies beneath: a wrapper narrower than what it wraps
      (test_a_wrapper_narrower_than_the_method_it_wraps_is_read_as_the_wrapper),
      or one met lower down
      (test_a_forwarding_wrapper_over_a_narrower_one_is_handed_nothing);
    - a layer spreading ``**kwargs`` passes the rest on, so the walk steps to
      what it wraps; with nothing beneath, nothing that asked would receive
      them (test_a_method_taking_only_keywords_is_handed_nothing,
      test_a_forwarding_wrapper_over_a_method_naming_none_is_handed_nothing).

    A layer with no signature to read ends it (``_own_parameters``). A layer
    met twice ends the walk, since a chain that loops names nothing new
    (test_a_wrapped_chain_that_loops_is_handed_nothing; without that conjunct
    the test never finishes). The other conjunct stops the walk at the bottom
    of the chain: without it,
    test_a_decorator_without_wraps_answers_for_its_own_spread_alone fails.
    """
    layer: Any = asked
    walked: list[Any] = []
    reached: set[str] = set()
    while layer is not None and not any(layer is seen for seen in walked):
        walked.append(layer)
        parameters = _own_parameters(layer)
        if parameters is None:
            break
        reached.update(
            name for name, parameter in parameters.items() if _reached_by_keyword(parameter)
        )
        if not any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()
        ):
            break
        layer = getattr(layer, "__wrapped__", None)
    return frozenset(reached)


def _own_parameters(layer: Any) -> Mapping[str, inspect.Parameter] | None:
    """``layer``'s own parameters, or ``None`` where it has no signature to read.

    A builtin, or a partial over one, has none (``ValueError``:
    test_a_callable_with_no_signature_is_handed_nothing,
    test_a_callable_with_no_signature_is_asked_as_before), nor has a
    ``__wrapped__`` that cannot be called (``TypeError``:
    test_a_wrapped_layer_that_is_not_callable_is_handed_nothing). Such a
    layer never declared ``arguments``, so it is read as not having opted
    in, and a check that never did is asked without them.
    """
    try:
        return inspect.signature(layer, follow_wrapped=False).parameters
    except (ValueError, TypeError):
        return None


def _reached_by_keyword(parameter: inspect.Parameter) -> bool:
    """Whether ``parameter`` is one a keyword reaches as the value itself.

    ``test_a_parameter_named_arguments_that_no_keyword_reaches_is_handed_nothing``
    fails without it (as does
    ``test_a_forwarding_wrapper_over_a_positional_only_arguments_is_handed_nothing``
    beneath a forwarding layer): a parameter of that name that is
    positional-only or variadic is not reached.
    """
    return parameter.kind in (
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        inspect.Parameter.KEYWORD_ONLY,
    )
