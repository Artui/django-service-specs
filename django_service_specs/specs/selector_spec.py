"""``SelectorSpec`` - a read, declared once for every transport."""

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
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.pool.provider_keys import provider_keys
from django_service_specs.specs.utils import (
    check_call_seeds,
    check_callable,
    check_changes,
    check_metadata,
    check_permissions,
    check_preconditions,
    check_presenter,
    check_providers,
    check_reserved,
)
from django_service_specs.types.affordance_declarer import AffordanceDeclarer
from django_service_specs.types.selector_kind import SelectorKind
from django_service_specs.types.utils import affordance_alias


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
            spec is built, since no checks would pass everyone. **Not read when the spec is nested**:
            authorization belongs to the spec being dispatched.
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
            filter named like a read declared differently is refused here. Its
            ``data`` is the arguments the call was sent for those names. Needs
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
        kwargs: A provider of extra pool entries: called with the keywords it
            declares from the selector's pool, it returns a mapping merged into
            that pool after the caller's arguments, so a key it answers is the
            author's value whatever the caller sent - a tenant, a project scope.
            A value of ``UNSET`` declines its key and leaves the caller's in
            place, unless the key is one its ``TypedDict`` return annotation
            says it fills: the caller's value for that is dropped once
            checked, so declining or leaving it out leaves it absent. Annotate its return as a ``TypedDict`` and ``provider_keys``
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
    # Beside ``reads`` and named for what the arguments do, as ``reads`` is:
    # they shape the output, and the presenter is their one reader.
    shapes: Parameters = field(default_factory=Parameters)
    presenter: Presenter | None = None
    allow_none: bool = False
    select_related: Sequence[str] | None = None
    prefetch_related: Sequence[str | Prefetch] | None = None
    annotations: Mapping[str, Any] | None = None
    extend_queryset: Callable[..., QuerySet[Any]] | None = None
    # ``Any`` because the package never imports django-filter: a FilterSet is
    # read and applied by its attributes (``base_filters``, ``.qs``) rather than
    # by class, so the import stays behind the ``filter`` extra.
    filter_set: Any = None
    # The same word as ``ServiceSpec.affordances``, because it is the same
    # declaration read from the other side: there the conditions an operation
    # needs, here the answer for each row. Keyed by a name the caller chooses
    # rather than taken from a registry, since a ``ServiceSpec`` does not know
    # what it is called.
    affordances: Mapping[str, AffordanceDeclarer] | None = None
    # djangorestframework-services' names for the same three declarations, so a
    # spec moving between the two packages keeps its field names. Typed open
    # (``...``) because each is bound from the keyword pool, so its signature
    # is whichever subset of the pool it declares.
    kwargs: Callable[..., Mapping[str, Any]] | None = None
    preconditions: Sequence[Callable[..., None]] | None = None
    progress_reporter: Callable[..., Any] | None = None
    metadata: Mapping[str, Any] | None = None
    # The part of ``reads`` the constructor added from ``filter_set``, kept so a
    # copy made with ``dataclasses.replace`` - which hands the merged ``reads``
    # back with whatever ``filter_set`` the copy names - can take the previous
    # filters out before reading the new ones. An init field because
    # ``replace`` carries only those; private, because nothing but the
    # constructor writes it. TestFilterSet.test_a_copy_with_another_filter_set_reads_only_its_filters
    # fails without it.
    _filter_reads: Parameters = field(default_factory=Parameters, repr=False, compare=False)

    def __post_init__(self) -> None:
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
            # A filter_set declaring no filters is handed none of the caller's
            # data and never filters, whether its ``base_filters`` is missing,
            # empty or ``None``. A real FilterSet declaring none is still
            # legal, and narrows nothing, since django-filter builds that
            # class itself; anything else declaring none is refused. One
            # branch to coverage, so each condition is held by its own test:
            # TestFilterSet.test_a_duck_declaring_filters_is_accepted (the
            # filters declared) and
            # test_a_filterset_declaring_no_filters_is_accepted (a FilterSet,
            # whose own conditions ``_is_filter_set`` names). After the
            # callable check, so a value that is no callable is still refused
            # as one.
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
        # After the filters join, so a filter named ``user`` is refused as a
        # read named ``user`` is:
        # TestFilterSet.test_a_filter_named_after_a_reserved_seed_is_refused.
        check_reserved(self.reads, label=f"{label}.reads")
        check_call_seeds(self.reads, label=f"{label}.reads", reflected_seated=True)
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
        # After ``check_providers`` has proved it callable, so a value that is
        # no callable is still refused as one.
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

    def parameters(self) -> Parameters:
        """Everything this spec takes: its ``reads``, then its ``shapes``."""
        # The reads themselves where there are no shapes, so a spec declaring
        # none hands back the object it holds
        # (test_defaults_and_normalization), as it did before shapes existed.
        if not self.shapes:
            return self.reads
        return self.reads + self.shapes

    def output(self) -> Output | None:
        """What this spec returns, as its presenter declares it, or ``None``."""
        return self.presenter.output() if self.presenter is not None else None


def _is_filter_set(filter_set: Any) -> bool:
    """Whether ``filter_set`` is a django-filter ``FilterSet`` class.

    Read off the loaded module rather than by importing it: a ``FilterSet``
    cannot exist unless django-filter has been imported, so a module not
    loaded answers ``False`` without importing anything, and an environment
    without the ``filter`` extra refuses a duck in the same words as one
    with it. One branch to coverage, so each condition is held by its own
    test, in ``TestFilterSet``:
    test_a_callable_object_declaring_no_filters_is_refused_as_one (a class:
    ``issubclass`` raises on anything else),
    test_without_django_filter_loaded_a_duck_declaring_nothing_is_refused
    (the module loaded) and
    test_one_declaring_no_filters_is_refused_unless_it_is_a_filterset (the
    subclass).
    """
    module = sys.modules.get("django_filters")
    return (
        isinstance(filter_set, type)
        and module is not None
        and issubclass(filter_set, module.FilterSet)
    )


def _read_filters(spec: SelectorSpec) -> None:
    """Set ``reads`` to the author's own, then each filter's Parameter after them, once.

    The author's own are ``reads`` less what a previous construction added
    from a filter set, so a copy naming another filter set, or none, reads only
    its own (TestFilterSet.test_a_copy_with_another_filter_set_reads_only_its_filters,
    TestFilterSet.test_a_copy_without_a_filter_set_reads_the_author_s_own_alone).
    A filter equal to a read the author declared is not added, and so not
    recorded as added: it stays the author's when the filter set goes
    (TestFilterSet.test_a_read_the_author_declared_as_the_filter_does_survives_a_copy).
    One declared differently reaches ``+`` and is refused as two sources of one
    name (TestFilterSet.test_a_read_the_filter_declares_differently_is_refused).
    """
    previous = spec._filter_reads.items
    # Nothing added before and nothing to add: ``reads`` stays the object the
    # author passed (test_output_is_the_presenters holds the identity). Two
    # conjuncts, each held by its own test:
    # TestFilterSet.test_a_copy_without_a_filter_set_reads_the_author_s_own_alone
    # fails without the first, TestFilterSet.test_its_filters_join_the_reads_after_the_author_s_own
    # without the second.
    if not previous and spec.filter_set is None:
        return
    own = Parameters(tuple(p for p in spec.reads.items if p not in previous))
    filters = filter_set_parameters(spec.filter_set) if spec.filter_set is not None else ()
    added = Parameters(tuple(p for p in filters if p not in own.items))
    object.__setattr__(spec, "reads", own + added)
    object.__setattr__(spec, "_filter_reads", added)


def _check_shapes(spec: SelectorSpec) -> None:
    """Refuse ``shapes`` that are not Parameters, name a seed, or repeat a read.

    After the filters join the reads, so a filter is compared as a read is
    (TestShapes.test_a_shape_a_filter_also_declares_is_refused). A shape
    never reaches a pool today, and a seed's name is refused anyway: the
    names a selector's pool may one day carry stay free of the seeds, as
    every parameter's are.
    """
    if not isinstance(spec.shapes, Parameters):
        raise ImproperlyConfigured("SelectorSpec.shapes must be Parameters.")
    check_reserved(spec.shapes, label="SelectorSpec.shapes")
    check_call_seeds(spec.shapes, label="SelectorSpec.shapes", reflected_seated=False)
    # ``+`` refuses a name both declare (TestShapes.test_a_shape_a_read_also_declares_is_refused).
    spec.reads + spec.shapes


def _check_shapes_unfilled(spec: SelectorSpec) -> None:
    """Refuse a ``kwargs`` provider annotated to fill a shape.

    Its values are merged into the selector's pool, and a shape never is, so
    a key it fills would be reported by ``server_owned_keys`` as the
    server's while dispatch still demanded it of the caller. Only a
    ``filled`` key of a provider whose return names its keys, as for the
    service spec's seats
    (TestShapes.test_a_kwargs_provider_filling_other_keys_is_accepted).
    """
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
    """Refuse an ``affordances`` mapping whose answers could not be told apart.

    At construction, like ``ServiceSpec``'s own check: a selector reaches
    transports that never ask before they present its rows.
    """
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
        # Two disjuncts, one case each in
        # ``tests/specs/test_selector_spec.py::TestAffordances::test_a_key_must_be_a_non_empty_string``.
        if not isinstance(name, str) or not name:
            raise ImproperlyConfigured(
                f"SelectorSpec.affordances keys must be non-empty strings; got {name!r}."
            )
        # A base only ``ServiceSpec`` inherits, so a ``SelectorSpec``, which has
        # an ``affordances`` of its own, is refused too
        # (test_a_value_must_be_a_service_spec[selector-spec]).
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
