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
    """The names ``provider`` fills and those it may decline, or ``None`` if it does not say."""
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
