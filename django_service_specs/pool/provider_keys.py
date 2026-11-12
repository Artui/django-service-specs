from __future__ import annotations

import inspect
import sys
from collections.abc import Callable, Mapping
from types import SimpleNamespace, UnionType
from typing import Annotated, Any, TypeVar, Union, get_args, get_origin

from typing_extensions import Format, get_annotations, get_type_hints

from django_service_specs.types.provider_keys import ProviderKeys
from django_service_specs.types.unset import UnsetType

# The two runtime spellings of a union, ``Union[a, b]`` and ``a | b``: separate
# origins up to Python 3.13, one object from 3.14. A union's arguments are the
# alternatives to the value, so whether one of them is ``UnsetType`` is whether
# the value may be ``UNSET``.
_UNIONS: tuple[Any, ...] = (Union, UnionType)


def provider_keys(
    provider: Callable[..., Any] | None,
) -> ProviderKeys | None:
    """The names ``provider`` fills and those it may decline, or ``None`` if it does not say.

    The static half of the ``kwargs=`` provider contract, whose runtime half is
    how dispatch calls the provider. ``ServiceSpec.kwargs`` and
    ``SelectorSpec.kwargs`` return a mapping, and one annotated to return a
    ``TypedDict`` says, before it runs, which names it fills. A
    transport reads that here to build a schema that does not ask the caller
    for them, and to know which calls to refuse before dispatch, rather than
    keeping a copy of this reader.

    Returns a
    [`ProviderKeys`][django_service_specs.types.provider_keys.ProviderKeys],
    ``(filled, declinable)``: two disjoint sets that together are every key of
    the ``TypedDict``, the keys the provider always answers for and the keys
    whose value admits ``UnsetType``, which it may decline with ``UNSET``. It
    unpacks as a pair and names each set, so ``keys.filled`` reads as well as
    ``filled, declinable = keys``.

    ``ProviderKeys(frozenset(), frozenset())`` for ``provider=None``: a spec with
    no provider fills nothing. ``None`` when the provider says nothing about its
    keys -- no return annotation, a plain ``dict``, a lambda, or a return
    annotation that does not resolve -- so it may fill any name, and a transport
    requires none of them for lacking a default. Held by
    ``test_a_spec_without_a_provider_fills_nothing`` and
    ``test_a_provider_whose_return_says_nothing_is_untyped``.

    **Each annotation costs only what it says.** The return annotation is
    resolved on its own, in the globals of the function a decorator wrapped
    rather than the wrapper's (``decorated-elsewhere`` in
    ``test_a_generic_typed_dicts_arguments_decide_which_keys_may_be_declined``),
    so a parameter annotation naming a type imported only under
    ``TYPE_CHECKING`` leaves the keys readable
    (``test_a_parameter_type_imported_only_for_type_checking_leaves_the_keys_readable``).
    The keys are read off the ``TypedDict`` without hints, and each value is
    resolved on its own, so one that does not resolve makes only its own key
    declinable: whether the provider may decline it cannot be read, and
    declinable is the reading that neither hides the name from the caller nor
    requires it (``test_a_value_type_that_does_not_resolve_makes_only_its_key_declinable``).
    Python 3.14's lazily evaluated annotations are read the same way, in the
    format that leaves an unresolvable name as a forward reference rather than
    raising (``test_lazily_evaluated_annotations_are_read_one_at_a_time``).
    That format is why ``typing-extensions`` is floored at 4.14: on 3.14, 4.13
    hands the standard library's ``annotationlib`` a format number it reserves
    for internal use, which raises, and every typed provider would read as
    untyped.

    **A generic ``TypedDict`` is read with whatever binds its parameters.**
    ``Scope[str | UnsetType]`` does not relay ``__required_keys__``, so the keys
    come off ``Scope``, where a value annotated ``T`` is the bare type variable.
    What ``T`` stands for is substituted wherever it appears in a value, a union
    included, whether an alias's arguments bind it
    (``test_a_generic_typed_dicts_arguments_decide_which_keys_may_be_declined``)
    or a class statement does, as ``class Declining(Scope[str | UnsetType])``
    does, and a subclass handing its own parameter on to ``Scope``
    (``test_a_subclass_binding_decides_which_keys_may_be_declined``). An
    argument that does not admit ``UNSET`` still fills the key
    (``test_a_parameterised_typed_dict_is_read_off_its_origin``), and one
    wrapped in ``Annotated`` is read as what it wraps
    (``test_annotated_around_a_binding_is_read_as_what_it_annotates``). A PEP 695
    ``class Scope[T](TypedDict)`` is read the same way under postponed
    annotations, where the ``"T"`` a value leaves resolves only beside the
    class's ``__type_params__``
    (``test_a_pep_695_type_parameter_is_read_as_the_class_declares_it``).

    **Each key is read with the bindings of the class that declared it**, so
    one ``T`` reused at every level reads as each class binds it:
    ``class Shadow(Scope[list[T]], Generic[T])`` with ``extra: T``, returned
    as ``Shadow[str | UnsetType]``, fills ``tenant`` with a list and may
    decline ``extra``
    (``test_each_key_is_read_with_the_bindings_of_the_class_that_declared_it``).
    A key reached through two bases that bind it differently is filled if
    either reading fills it.

    **A type variable nothing binds counts as filled**, as in a bare
    ``-> Scope`` (``test_a_type_variable_nothing_binds_is_filled``). Whether it
    may be ``UNSET`` is written nowhere, and filled keeps the decision with the
    provider by hiding the key from the caller. Declinable would let a
    transport whose caller's value wins put that value in a key the provider
    was meant to decide, such as a tenant.

    Three readings stay as they are, each held by a test:

    - A PEP 696 default on a type variable is not consulted
      (``test_a_type_variables_default_is_not_consulted``).
    - A base that cannot be substituted makes the provider read as untyped
      (``test_a_base_that_cannot_be_substituted_leaves_the_provider_untyped``).
    - A key a subclass redeclares is read with its base's bindings, since no
      runtime record says which class wrote it
      (``test_a_key_a_subclass_redeclares_is_read_with_its_bases_bindings``).

    Duck-typed on the keys a ``TypedDict`` class carries rather than
    ``is_typeddict``, because the standard library's answers ``False`` for a
    ``typing_extensions.TypedDict`` on the older Pythons this package supports.
    """
    if provider is None:
        return ProviderKeys(frozenset(), frozenset())
    try:
        returned = _resolve(
            get_annotations(provider, format=Format.FORWARDREF).get("return"),
            getattr(inspect.unwrap(provider), "__globals__", {}),
        )
        declared: Any = get_origin(returned) or returned
        if getattr(declared, "__required_keys__", None) is None:
            return None
        values = get_annotations(declared, format=Format.FORWARDREF)
        declarations = _declarations(returned)
    except Exception:
        return None
    namespace = getattr(sys.modules.get(declared.__module__), "__dict__", {})
    readings = [
        (name, _may_decline(values.get(name), namespace, type_parameters, bindings))
        for keys, bindings, type_parameters in declarations
        for name in keys
    ]
    filled = frozenset(name for name, declines in readings if not declines)
    declinable = frozenset(name for name, declines in readings if declines) - filled
    return ProviderKeys(_keys(declared) - declinable, declinable)


def _keys(declared: Any) -> frozenset[str]:
    """Every key ``declared`` carries, its bases' included; none if it is not a ``TypedDict``."""
    return frozenset(getattr(declared, "__required_keys__", ())) | frozenset(
        getattr(declared, "__optional_keys__", ())
    )


def _may_decline(
    annotation: Any,
    namespace: dict[str, Any],
    type_parameters: dict[str, Any],
    bindings: Mapping[Any, Any],
) -> bool:
    """Whether a key annotated ``annotation`` may come back ``UNSET``; ``True`` if unreadable."""
    try:
        value = _resolve(annotation, namespace, type_parameters)
    except Exception:
        return True
    return _admits_unset(value, bindings)


def _declarations(
    returned: Any,
) -> list[tuple[frozenset[str], dict[Any, Any], dict[str, Any]]]:
    """Each class ``returned`` is built from its declared keys, bindings and PEP 695 parameters."""
    declarations: list[tuple[frozenset[str], dict[Any, Any], dict[str, Any]]] = []
    pending = [(get_origin(returned) or returned, get_args(returned))]
    while pending:
        declared, arguments = pending.pop()
        parameters = getattr(declared, "__parameters__", ())
        bindings = dict(zip(parameters, arguments or parameters, strict=False))
        bases = [
            (get_origin(base) or base, tuple(_substitute(a, bindings) for a in get_args(base)))
            for base in getattr(declared, "__orig_bases__", ())
        ]
        inherited = {name for base, _ in bases for name in _keys(base)}
        type_parameters = {p.__name__: p for p in getattr(declared, "__type_params__", ())}
        declarations.append((_keys(declared) - inherited, bindings, type_parameters))
        pending.extend(bases)
    return declarations


def _substitute(argument: Any, bindings: Mapping[Any, Any]) -> Any:
    """``argument`` with each type variable in it replaced by what ``bindings`` binds it to."""
    if isinstance(argument, TypeVar):
        return bindings[argument]
    parameters = getattr(argument, "__parameters__", ())
    return argument[tuple(bindings[p] for p in parameters)] if parameters else argument


def _resolve(
    annotation: Any, namespace: dict[str, Any], local: dict[str, Any] | None = None
) -> Any:
    """``annotation`` evaluated in ``namespace`` the way ``get_type_hints`` evaluates one."""
    holder = SimpleNamespace(__annotations__={"value": annotation})
    return get_type_hints(holder, globalns=namespace, localns=local)["value"]


def _admits_unset(annotation: Any, bindings: Mapping[Any, Any]) -> bool:
    """Whether a value annotated ``annotation`` may be ``UNSET``."""
    if isinstance(annotation, TypeVar):
        return annotation in bindings and _admits_unset(bindings[annotation], {})
    if get_origin(annotation) is Annotated:
        return _admits_unset(get_args(annotation)[0], bindings)
    return annotation is UnsetType or (
        get_origin(annotation) in _UNIONS
        and any(_admits_unset(argument, bindings) for argument in get_args(annotation))
    )


__all__ = ["provider_keys"]
