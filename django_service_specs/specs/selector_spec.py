from __future__ import annotations

import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, fields, replace
from typing import Any

from django.core.exceptions import ImproperlyConfigured
from django.db.models import Prefetch, QuerySet
from typing_extensions import Self

from django_service_specs.adapters.filters.filter_set_parameters import filter_set_parameters
from django_service_specs.authorization.permission_check import PermissionCheck
from django_service_specs.output.output import Output
from django_service_specs.output.presenter import Presenter
from django_service_specs.parameters.parameters import Parameter, Parameters
from django_service_specs.pool.provider_keys import provider_keys
from django_service_specs.specs.check_permissions import check_permissions
from django_service_specs.specs.utils import (
    check_changes,
    check_metadata,
    check_preconditions,
    check_presenter,
    check_providers,
    check_reserved,
)
from django_service_specs.types.affordance_declarer import AffordanceDeclarer
from django_service_specs.types.selector_kind import SelectorKind
from django_service_specs.types.utils import affordance_alias, check_callable


@dataclass(frozen=True, kw_only=True)
class SelectorSpec:
    """A read: what it takes, who may run it, how its rows are shaped, what it returns."""

    kind: SelectorKind
    selector: Callable[..., Any]
    permissions: Sequence[PermissionCheck] | None = None
    reads: Parameters = field(default_factory=Parameters)
    shapes: Parameters = field(default_factory=Parameters)
    presenter: Presenter | None = None
    allow_none: bool = False
    select_related: Sequence[str] | None = None
    prefetch_related: Sequence[str | Prefetch] | None = None
    annotations: Mapping[str, Any] | None = None
    extend_queryset: Callable[..., QuerySet[Any]] | None = None
    filter_set: Any = None
    affordances: Mapping[str, AffordanceDeclarer] | None = None
    kwargs: Callable[..., Mapping[str, Any]] | None = None
    preconditions: Sequence[Callable[..., None]] | None = None
    progress_reporter: Callable[..., Any] | None = None
    metadata: Mapping[str, Any] | None = None
    _filter_reads: Parameters = field(default_factory=Parameters, repr=False, compare=False)

    def __post_init__(self) -> None:
        # A filter_set declaring no filters is handed no caller data and never filters.
        label = "SelectorSpec"
        try:
            kind = SelectorKind(self.kind)
        except ValueError:
            raise ImproperlyConfigured(
                f"{label}.kind is {self.kind!r}; use SelectorKind.LIST or SelectorKind.RETRIEVE."
            ) from None
        object.__setattr__(self, "kind", kind)
        check_callable(self.selector, label=f"{label}.selector")
        object.__setattr__(self, "permissions", check_permissions(self.permissions, label=label))
        if not isinstance(self.reads, Parameters):
            raise ImproperlyConfigured(f"{label}.reads must be Parameters.")
        if self.filter_set is not None:
            check_callable(self.filter_set, label=f"{label}.filter_set", sync=True)
            if not getattr(self.filter_set, "base_filters", None) and not _is_filter_set(
                self.filter_set
            ):
                named = getattr(self.filter_set, "__name__", type(self.filter_set).__name__)
                raise ImproperlyConfigured(
                    f"{label}.filter_set is {named}, which declares no filters in "
                    "base_filters. A filter_set must be a django-filter FilterSet: its "
                    "filters are declared as the selector's arguments, and an object that "
                    "declares none is handed none of the caller's data and never filters. "
                    "A step narrowing the queryset by no argument belongs in extend_queryset."
                )
        _read_filters(self)
        check_reserved(self.reads, label=f"{label}.reads")
        _check_shapes(self)
        check_presenter(self.presenter, label=label)
        for name in ("select_related", "prefetch_related"):
            value = getattr(self, name)
            if value is not None:
                if isinstance(value, str):
                    raise ImproperlyConfigured(
                        f"{label}.{name} is a string; pass a sequence, [{value!r}]."
                    )
                object.__setattr__(self, name, tuple(value))
        if self.extend_queryset is not None:
            check_callable(self.extend_queryset, label=f"{label}.extend_queryset", sync=True)
        _check_affordances(self)
        check_providers(self, ("kwargs", "progress_reporter"), label=label)
        _check_shapes_unfilled(self)
        object.__setattr__(
            self, "preconditions", check_preconditions(self.preconditions, label=label)
        )
        check_metadata(self.metadata, label=label)

    def derive(self, **changes: object) -> Self:
        """A new spec of this class with the named fields replaced."""
        check_changes(fields(self), changes, label=type(self).__name__)
        return replace(self, **changes)

    def as_kernel_spec(self) -> Self:
        """This spec, as its own compiled form."""
        return self

    def parameters(self, *, call_context: dict[str, Any] | None = None) -> Parameters:
        """Everything this spec takes: its ``reads``, then its ``shapes``."""
        if not self.shapes:
            return self.reads
        return self.reads + self.shapes

    def output(self) -> Output | None:
        """What this spec returns, as its presenter declares it, or ``None``."""
        return self.presenter.output() if self.presenter is not None else None


def _is_filter_set(filter_set: Any) -> bool:
    """Whether ``filter_set`` is a django-filter ``FilterSet`` class."""
    module = sys.modules.get("django_filters")
    return (
        isinstance(filter_set, type)
        and module is not None
        and issubclass(filter_set, module.FilterSet)
    )


def _read_filters(spec: SelectorSpec) -> None:
    """Set ``reads`` to the author's own, then each filter's Parameter after them, once."""
    previous = spec._filter_reads.items
    if not previous and spec.filter_set is None:
        return
    own = Parameters(tuple(p for p in spec.reads.items if not any(p is q for q in previous)))
    filters = filter_set_parameters(spec.filter_set) if spec.filter_set is not None else ()
    declared = tuple(_unlabelled(p) for p in own.items)
    added = Parameters(tuple(p for p in filters if _unlabelled(p) not in declared))
    object.__setattr__(spec, "reads", own + added)
    object.__setattr__(spec, "_filter_reads", added)


def _unlabelled(parameter: Parameter) -> Parameter:
    """``parameter`` as a read is compared with a filter: everything but its labels."""
    return replace(parameter, choice_labels=None)


def _check_shapes(spec: SelectorSpec) -> None:
    """Refuse ``shapes`` that are not Parameters, name a seed, or repeat a read."""
    if not isinstance(spec.shapes, Parameters):
        raise ImproperlyConfigured("SelectorSpec.shapes must be Parameters.")
    check_reserved(spec.shapes, label="SelectorSpec.shapes")
    spec.reads + spec.shapes


def _check_shapes_unfilled(spec: SelectorSpec) -> None:
    """Refuse a ``kwargs`` provider annotated to fill a shape."""
    keys = provider_keys(spec.kwargs)
    if keys is None:
        return
    stray = sorted(keys.filled & spec.shapes.names())
    if stray:
        raise ImproperlyConfigured(
            f"SelectorSpec.kwargs is annotated to fill {stray}, which SelectorSpec.shapes "
            f"declares, and its values never reach SelectorSpec.shapes, so dispatch would still "
            f"demand {stray} of the caller. No provider fills SelectorSpec.shapes, whose values "
            "reach only the presenter; rename the key."
        )


def _check_affordances(spec: SelectorSpec) -> None:
    """Refuse an ``affordances`` mapping whose answers could not be told apart."""
    affordances: Any = spec.affordances
    if affordances is None:
        return
    if not isinstance(affordances, Mapping):
        raise ImproperlyConfigured(
            "SelectorSpec.affordances must be a mapping of name -> ServiceSpec; got "
            f"{type(affordances).__name__}."
        )
    own: frozenset[str] = frozenset(spec.annotations or ())
    owners: dict[str, str] = {}
    for name, service_spec in affordances.items():
        if not isinstance(name, str) or not name:
            raise ImproperlyConfigured(
                f"SelectorSpec.affordances keys must be non-empty strings; got {name!r}."
            )
        if not isinstance(service_spec, AffordanceDeclarer):
            raise ImproperlyConfigured(
                f"SelectorSpec.affordances[{name!r}] must be a ServiceSpec; got "
                f"{type(service_spec).__name__}. The mapping holds the spec whose "
                "affordances are being asked about, not its registry name."
            )
        for affordance in service_spec.affordances or ():
            alias = affordance_alias(name, affordance.code)
            if alias in own:
                raise ImproperlyConfigured(
                    f"SelectorSpec.affordances[{name!r}] generates the annotation "
                    f"{alias!r}, which `annotations` already declares. Rename one: the "
                    "generated value would silently replace the declared one."
                )
            if alias in owners:
                raise ImproperlyConfigured(
                    f"SelectorSpec.affordances[{name!r}] and [{owners[alias]!r}] both "
                    f"generate the annotation {alias!r}. Rename an entry so each answer "
                    "has its own."
                )
            owners[alias] = name
