from __future__ import annotations

import inspect
import weakref
from collections.abc import Callable, Iterable, Mapping
from types import FunctionType, MappingProxyType
from typing import Any, ClassVar, Final

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.authorization.is_deactivated import is_deactivated
from django_service_specs.authorization.permission_check import PermissionCheck
from django_service_specs.authorization.principal_unavailable import PrincipalUnavailable
from django_service_specs.authorization.sync_answer import sync_answer
from django_service_specs.authorization.unrestricted import Unrestricted
from django_service_specs.pool.pool_seeds import PoolSeeds
from django_service_specs.pool.seeded_pool import seeded_pool
from django_service_specs.pool.utils import call_entries, only_seeds
from django_service_specs.types.utils import check_callable


def asked_with(
    check: Any,
    method: str,
    arguments: Mapping[str, Any] | None,
    *,
    positional: int = 2,
    offered: Mapping[str, Any] = MappingProxyType({}),
) -> dict[str, Any]:
    """The keywords ``check``'s ``method`` is asked with, of ``arguments`` and ``offered``."""
    named = declared_keywords(check, method, positional=positional)
    asked = {name: value for name, value in offered.items() if name in named}
    if "arguments" in named:
        asked["arguments"] = arguments
    return asked


def offered_to_checks(
    call_context: dict[str, Any] | None, seeds: Mapping[str, Any] | None
) -> dict[str, Any]:
    """What a check may opt into by name besides ``arguments``: the call's context and its seeds."""
    context = {} if call_context is None else call_context
    return {**call_entries(context), **(seeds or {}), "call_context": context}


# The three questions a check is asked, each with how many parameters the call
# fills by position, which no name among them can opt into.
CLASS_LEVEL: Final = ("has_permission", 2)
OBJECT_LEVEL: Final = ("has_object_permission", 3)
SCOPE_LEVEL: Final = ("has_scope_permission", 3)
QUESTIONS: Final = (CLASS_LEVEL, OBJECT_LEVEL, SCOPE_LEVEL)


def refuse_unusable_check(check: Any, *, label: str, index: int) -> None:
    """Refuse ``check`` unless it is a ``PermissionCheck`` instance whose three methods are sync."""
    if isinstance(check, type):
        raise ImproperlyConfigured(
            f"{label} holds the class {check.__name__}; pass an instance, {check.__name__}()."
        )
    if not isinstance(check, PermissionCheck):
        raise ImproperlyConfigured(
            f"{label} holds {type(check).__name__}, which is not a "
            "PermissionCheck. Subclass PermissionCheck, or adapt it."
        )
    for method, _ in QUESTIONS:
        check_callable(getattr(check, method), label=f"{label}[{index}].{method}", sync=True)


class _Combinator(PermissionCheck):
    """The base ``AllOf``, ``AnyOf`` and ``NoneOf`` share: checks asked as one, refused when built
    if one cannot be."""

    _asks: ClassVar[Mapping[str, tuple[tuple[str, int], ...]]]

    def __init__(self, *checks: PermissionCheck, message: str | None = None) -> None:
        name = type(self).__name__
        if not checks:
            raise ImproperlyConfigured(
                f"{name}.checks is empty, which decides nothing about anyone: AllOf and NoneOf "
                "of no checks would let anyone run it. Pass the checks it combines."
            )
        for index, check in enumerate(checks):
            refuse_unusable_check(check, label=f"{name}.checks", index=index)
            if isinstance(check, Unrestricted):
                raise ImproperlyConfigured(
                    f"{name}.checks[{index}] is {type(check).__name__}, the explicit allow, which "
                    "is a decision a spec makes by name. Declare permissions=[Unrestricted()] "
                    "on the spec to mean that anyone may run it."
                )
        self.checks: tuple[PermissionCheck, ...] = checks
        self.message = message
        self._refuse_seeds_named_for_its_parameters()

    def _refuse_seeds_named_for_its_parameters(self) -> None:
        """Refuse a child opting into a name this combinator's own method takes at that question."""
        name = type(self).__name__
        for method, _ in QUESTIONS:
            own = frozenset(_function_keywords(getattr(type(self), method))[1])
            for index, child in enumerate(self.checks):
                for asked, filled in self._asks[method]:
                    taken = declared_keywords(child, asked, positional=filled) & own
                    if taken:
                        seed = min(taken)
                        raise ImproperlyConfigured(
                            f"{name}.checks[{index}] opts into a seed named {seed!r} at "
                            f"{asked}, and {name}.{method} takes {seed} itself, so a seed of "
                            f"that name cannot reach the child through it. Rename the keyword."
                        )

    def _passes(
        self,
        child: PermissionCheck,
        method: str,
        principal: Any,
        spec: Any,
        at: tuple[Any, ...],
        offered: Mapping[str, Any],
    ) -> bool:
        """Whether ``child`` passes each question ``method`` asks, stopping at the first failure."""
        for asked, positional in self._asks[method]:
            answer = getattr(child, asked)(
                principal,
                spec,
                *at[: positional - 2],
                **asked_with(
                    child, asked, offered.get("arguments"), positional=positional, offered=offered
                ),
            )
            if not sync_answer(answer, asked=f"{type(child).__qualname__}.{asked}"):
                return False
        return True


def refuse_deactivated(principal: Any) -> None:
    """Raise ``PrincipalUnavailable`` for a deactivated ``principal``, first of all."""
    if is_deactivated(principal):
        raise PrincipalUnavailable()


def check_seed_arguments(
    principal: Any,
    *,
    seeds: Mapping[str, Any] | None,
    pool_seeds: PoolSeeds | None,
    asked: str,
) -> None:
    """Refuse what an ``authorize`` function cannot honour with the seeds it was handed."""
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
    """The seeds one ``authorize`` function offers its checks: ``seeds`` as handed, or resolved."""
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
    """The seeds of ``pool_seeds`` that ``names`` names, resolved for ``user``, and no other."""
    named = names & pool_seeds.names
    resolved = seeded_pool(
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
    """The registered seeds a check of ``spec`` names at one of ``questions``, resolved, by name."""
    return resolved_seeds(
        pool_seeds,
        _named_seeds(spec, pool_seeds.names, questions),
        user=principal,
        call_context=call_context,
    )


def _named_seeds(
    spec: Any, names: frozenset[str], questions: Iterable[tuple[str, int]]
) -> frozenset[str]:
    """The registered seeds that one of ``questions`` names on ``spec``'s checks."""
    named = frozenset().union(
        *(
            declared_keywords(check, method, positional=positional) & names
            for check in spec.permissions or ()
            for method, positional in questions
        )
    )
    return named - {"arguments"}


def declared_keywords(check: Any, method: str, *, positional: int) -> frozenset[str]:
    """The keyword names ``check``'s ``method`` takes, less the ``positional`` ones."""
    if isinstance(check, _Combinator):
        return frozenset().union(
            *(
                declared_keywords(child, asked, positional=filled)
                for child in check.checks
                for asked, filled in check._asks[method]
            )
        )
    reached, filled = _keywords(getattr(check, method))
    return reached - frozenset(filled[:positional])


def _keywords(asked: Callable[..., Any]) -> tuple[frozenset[str], tuple[str, ...]]:
    """What ``asked`` takes by keyword, and its parameters a positional call fills, in order."""
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
    """``_keywords`` of a function a class defines, inspected once."""
    keywords = _DECLARES.get(function)
    if keywords is None:
        keywords = _DECLARES[function] = (
            _reached_names(function),
            _filled_by_position(function)[1:],
        )
    return keywords


def _filled_by_position(asked: Callable[..., Any]) -> tuple[str, ...]:
    """The parameters a positional call of ``asked`` fills, in order, as Python reports them."""
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
    """The names a keyword reaches in ``asked``, itself or by forwarding it."""
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
    """``layer``'s own parameters, or ``None`` where it has no signature to read."""
    try:
        return inspect.signature(layer, follow_wrapped=False).parameters
    except (ValueError, TypeError):
        return None


def _reached_by_keyword(parameter: inspect.Parameter) -> bool:
    """Whether ``parameter`` is one a keyword reaches as the value itself."""
    return parameter.kind in (
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        inspect.Parameter.KEYWORD_ONLY,
    )
