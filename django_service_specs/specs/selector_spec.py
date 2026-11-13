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
    """A read: what it takes, who may run it, how its rows are shaped, what it returns.

    Dispatched on its own, it is a list or a retrieve. Nested in a
    [`ServiceSpec`][django_service_specs.specs.service_spec.ServiceSpec], it is how
    that service resolves its target, its collection or its output.

    Attributes:
        kind: ``LIST`` or ``RETRIEVE``; see
            [`SelectorKind`][django_service_specs.types.selector_kind.SelectorKind].
        selector: The read itself. Called with the keywords it declares, from
            the principal (``user``), any registered pool seed, and the arguments
            ``reads`` declares. It may be ``async def``: the selector is this
            spec's run, and the run is the one callable allowed to be.
        permissions: The checks a principal must pass. ``None`` means none were
            declared, which registration and dispatch both refuse; an open read
            says ``[Unrestricted()]``. An empty sequence is refused when the
            spec is built, since no checks would pass everyone. **Refused when the spec is
            nested** in a ``ServiceSpec``, whatever it holds: authorization belongs to
            the spec being dispatched, so nest ``spec.derive(permissions=None)``.
        reads: The arguments the selector reads with no Validator in front of
            it - its filters, its ordering, the key of the row it retrieves.
            With ``shapes`` they are the spec's whole Parameters, so the closed
            argument set and the shape check both apply to them.
        shapes: The arguments that shape what the presenter renders rather
            than which rows are read - which fields, a query over each row -
            as a Parameters group of their own. Part of ``parameters()``,
            after the ``reads``, so the schema, the closed argument set and
            the shape check cover them as any argument; never in the
            selector's pool, so the selector, its ``extend_queryset`` and its
            ``filter_set`` never see them. What the caller sent for them
            reaches the presenter alone, on
            [`PresentationContext.shapes`][django_service_specs.output.presentation_context.PresentationContext].
            A name a read or a filter also declares is refused, as is one
            dispatch seeds and one the ``kwargs`` provider is annotated to
            fill, since no provider's values reach them. Refused on a nested
            selector, whose presenter presents no call of its own.
        presenter: Renders the rows. Not read on an instance or collection
            selector, whose rows the service consumes rather than returns.
        allow_none: On a ``RETRIEVE``, a missing row is the value ``None``
            rather than not-found - the shape of an optional singleton, or of an
            upsert's target. On a ``LIST``, a selector returning ``None`` has
            returned the empty list: the shaping is skipped, since there is
            nothing to shape, and the result is ``[]`` wherever the selector
            runs, so a selector spec's own scope check and ``preconditions``
            see the empty set, as they see an empty queryset, and its output
            schema stays an array. Without it, a ``LIST`` selector's ``None``
            is passed on as it came, and presenting it fails as the author's
            error.
        select_related, prefetch_related, annotations: Applied to the queryset
            the selector returns, in that order. Declaring any of them when the
            selector returns something else is refused at dispatch.
        extend_queryset: Applied last, called with the keywords it declares from
            the same pool plus ``queryset``, the shaped queryset so far. It
            returns the queryset to use. Sync-only, like ``filter_set``: either
            one declared ``async def`` is refused at construction.
        filter_set: Applied after ``extend_queryset``: a django-filter
            ``FilterSet`` class, called as ``filter_set(data=..., queryset=...)``
            and answering ``.qs``. One that declares no filters - its
            ``base_filters`` missing, empty or ``None`` - is refused at
            construction unless it is a django-filter ``FilterSet`` class,
            because it declares no Parameters and so would be handed none of
            the caller's data: a duck-typed stand-in must declare its filters
            in ``base_filters``, and a step narrowing the queryset by no
            argument belongs in ``extend_queryset``. A real ``FilterSet``
            declaring none is accepted and narrows nothing. Its filters are
            reads: read as Parameters by
            [`filter_set_parameters`][django_service_specs.adapters.filters.filter_set_parameters.filter_set_parameters]
            and added to ``reads`` after the author's own, so the schema, the
            closed argument set and the shape check all cover them, and a
            filter named like a read declared differently is refused here,
            where a difference in labels alone is no difference and the read
            as the author wrote it stands. Its ``data`` is the arguments the call was sent for those
            names. Needs
            the ``[filter]`` extra to read a real FilterSet.
        affordances: What can be done to each row right now. A mapping from a
            name the caller chooses to the
            [`ServiceSpec`][django_service_specs.specs.service_spec.ServiceSpec]
            whose ``affordances`` are being asked about - the spec objects, not
            registry names, so the read path takes no registry dependency and
            the declaration stays the one the operation enforces. Each answer is
            named ``affordance__<name>__<code>``; a collision with a key of
            ``annotations``, or between two entries, is refused at
            construction, because a generated answer silently replacing a
            project's own annotation is the worst way for this to fail.
        row_object: How to find the model instance in a row that wraps one - a
            tree node, a dataclass row, a table cell builder - so its
            ``affordances`` can be answered: an attribute name, read with
            ``getattr``, or a sync callable taking the row and returning the
            instance. ``None``, the default, answers model and mapping rows as
            they are. Set, it applies to every row, model and mapping rows
            included: the answers are set as attributes on the instance it
            finds, one query per model for the whole list as for model rows,
            and the row itself comes back unchanged, so a frozen wrapper works.
            It must find a saved model instance, or ``None`` for a row with no
            object, which is answered as a row the answers query did not find;
            anything else is refused at dispatch. A ``QuerySet`` result is
            refused beside it, since its rows are answered in SQL as the model
            itself. Anything but a non-empty string or a callable is refused at
            construction, and so is an async callable.
        kwargs: A provider of extra pool entries: called with the keywords it
            declares from the selector's pool, it returns a mapping merged into
            that pool after the caller's arguments, so a key it answers is the
            author's value whatever the caller sent - a tenant, a project scope.
            A value of ``UNSET`` declines its key and leaves the caller's in
            place, unless the key is one its ``TypedDict`` return annotation
            says it fills: the caller's value for that is dropped once
            checked, so declining or leaving it out leaves it absent. Annotate its return as a
            ``TypedDict`` and ``provider_keys``
            reads which keys it fills before it runs, and a read it fills is
            not demanded of the caller. On a target selector it scopes the
            lookup, and a filled key that the service spec's ``reads`` or its
            Validator declares is refused, since its values reach only the
            lookup; an output selector's is refused, since nothing would run
            it.
        preconditions: Raise-to-abort rules, a sequence of callables each called
            with the keywords it declares from the same pool once the selector
            has resolved, the row as ``instance`` or the rows as
            ``collection``. The return value is ignored, unless it is still to
            be awaited, which refuses the call with ``ImproperlyConfigured``.
            Kept as a tuple in declaration order. Refused on a nested selector, whose run is the
            enclosing service spec's.
        progress_reporter: A provider of a
            [`ProgressReporter`][django_service_specs.types.progress_reporter.ProgressReporter]
            sink the run reports to beside the transport's - a task record, an
            audit trail - called with the keywords it declares from the base
            pool. The run is the selector, and the provider is called only for
            a selector that takes ``progress``, once its keywords are bound:
            a sync selector calls it on its first report, and an ``async
            def`` one before the await. So a call refused before the run,
            a read the caller left out included, never calls it, and a
            provider returning ``None`` declines. The object-level and scope
            checks and the ``preconditions`` answer after the selector, so a
            call they refuse may already have called it. Nothing but the
            selector reports to it: ``extend_queryset``, the
            ``preconditions`` and the affordance conditions answered for the
            rows read ``progress`` from the pool, which is the transport's
            reporter. Refused on a nested selector.
        metadata: A project's own per-operation facts, stored as given and read
            back by its own checks or audit hooks.
    """

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
    row_object: str | Callable[[Any], Any] | None = None
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
        _check_row_object(self)
        check_providers(self, ("kwargs", "progress_reporter"), label=label)
        _check_shapes_unfilled(self)
        object.__setattr__(
            self, "preconditions", check_preconditions(self.preconditions, label=label)
        )
        check_metadata(self.metadata, label=label)

    def derive(self, **changes: object) -> Self:
        """A new spec of this class with the named fields replaced, and every other one this spec's.

        Built through the constructor, so every check a fresh declaration
        passes runs again on the result, the combinations included: a change
        that is valid alone and refused beside the fields it keeps is refused
        here. The spec it is called on is never changed. The fields not named
        are equal to its own, and the same objects except where the
        constructor rebuilds one: a spec with a ``filter_set`` has its
        ``reads`` assembled afresh, author's own and then the filters'.

        A field is replaced, never extended: ``reads=`` is the new spec's whole
        ``reads``, and a ``filter_set``'s filters join after it as they join
        after a declared one. Name the base's value to keep it and add to it,
        ``reads=base.reads + Parameters.of(...)``.

        The result is another spec, by identity: a
        [`Grant`][django_service_specs.dispatch.grant.Grant] minted for this
        one does not cover it.

        Raises:
            TypeError: a name in ``changes`` is not one of the spec's own
                fields, such as a method's name or a private field's.
            ImproperlyConfigured: the result is refused as a fresh declaration
                with the same fields would be.
        """
        check_changes(fields(self), changes, label=type(self).__name__)
        return replace(self, **changes)

    def as_kernel_spec(self) -> Self:
        """This spec, as its own compiled form.

        What makes a spec a
        [`SpecSource`][django_service_specs.specs.spec_source.SpecSource] like
        any declaration of another library's, and how
        [`kernel_spec`][django_service_specs.specs.kernel_spec.kernel_spec]
        tells the two apart: a spec compiles to itself, and is never cached.
        """
        return self

    def parameters(self, *, call_context: dict[str, Any] | None = None) -> Parameters:
        """Everything this spec takes: its ``reads``, then its ``shapes``.

        ``call_context`` is taken and ignored, so a reader asking a
        ``ServiceSpec`` or a ``SelectorSpec`` asks both alike: a selector spec
        has no Validator to hand it to.
        """
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


def _check_row_object(spec: SelectorSpec) -> None:
    """Refuse a ``row_object`` that is neither an attribute name nor a sync callable."""
    row_object: Any = spec.row_object
    if row_object is None or (isinstance(row_object, str) and row_object):
        return
    if not callable(row_object):
        raise ImproperlyConfigured(
            "SelectorSpec.row_object must be an attribute name or a callable taking the row "
            f"and returning its model instance; got {row_object!r}."
        )
    check_callable(row_object, label="SelectorSpec.row_object", sync=True)


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
