"""``SelectorSpec`` - a read, declared once for every transport."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ImproperlyConfigured
from django.db.models import Prefetch, QuerySet

from django_service_specs.authorization.permission_check import PermissionCheck
from django_service_specs.filters.filter_set_parameters import filter_set_parameters
from django_service_specs.output.output import Output
from django_service_specs.output.presenter import Presenter
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.utils import (
    check_callable,
    check_metadata,
    check_permissions,
    check_preconditions,
    check_presenter,
    check_providers,
    check_reserved,
)
from django_service_specs.types.utils import affordance_alias

if TYPE_CHECKING:
    # For the ``affordances`` annotation only; see ``_check_affordances`` for
    # why the runtime import cannot sit up here.
    from django_service_specs.specs.service_spec import ServiceSpec


@dataclass(frozen=True, kw_only=True)
class SelectorSpec:
    """A read: what it takes, who may run it, how its rows are shaped, what it returns.

    Dispatched on its own, it is a list or a retrieve. Nested in a
    [`ServiceSpec`][django_service_specs.specs.service_spec.ServiceSpec], it is how
    that service resolves its target, its collection or its output.

    Attributes:
        kind: ``LIST`` or ``RETRIEVE``; see
            [`SelectorKind`][django_service_specs.specs.selector_kind.SelectorKind].
        selector: The read itself. Called with the keywords it declares, from
            the principal (``user``), any registered pool seed, and the arguments
            ``reads`` declares. It may be ``async def``: the selector is this
            spec's run, and the run is the one callable allowed to be.
        permissions: The checks a principal must pass. ``None`` means none were
            declared, which registration and dispatch both refuse; an open read
            says ``[Unrestricted()]``. **Not read when the spec is nested**:
            authorization belongs to the spec being dispatched.
        reads: The arguments the selector reads with no Validator in front of
            it - its filters, its ordering, the key of the row it retrieves.
            They are the spec's whole Parameters, so the closed argument set and
            the shape check both apply to them.
        presenter: Renders the rows. Not read on an instance or collection
            selector, whose rows the service consumes rather than returns.
        allow_none: ``RETRIEVE`` only. A missing row is the value ``None``
            rather than not-found - the shape of an optional singleton, or of an
            upsert's target.
        select_related, prefetch_related, annotations: Applied to the queryset
            the selector returns, in that order. Declaring any of them when the
            selector returns something else is refused at dispatch.
        extend_queryset: Applied last, called with the keywords it declares from
            the same pool plus ``queryset``, the shaped queryset so far. It
            returns the queryset to use.
        filter_set: Applied after ``extend_queryset``: a django-filter
            ``FilterSet`` class, or anything called as
            ``filter_set(data=..., queryset=...)`` that answers ``.qs``. Its
            filters are reads: read as Parameters by
            [`filter_set_parameters`][django_service_specs.filters.filter_set_parameters.filter_set_parameters]
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
            place. Annotate its return as a ``TypedDict`` and ``provider_keys``
            reads which keys it fills before it runs. On a target selector it
            scopes the lookup; an output selector's is refused, since nothing
            would run it.
        preconditions: Raise-to-abort rules, a sequence of callables each called
            with the keywords it declares from the same pool once the selector
            has resolved, the row as ``instance`` or the rows as
            ``collection``. The return value is ignored. Kept as a tuple in
            declaration order. Refused on a nested selector, whose run is the
            enclosing service spec's.
        progress_reporter: A provider of a
            [`ProgressReporter`][django_service_specs.types.progress_reporter.ProgressReporter]
            sink the run reports to beside the transport's - a task record, an
            audit trail - called with the keywords it declares from the base
            pool. Resolved on first use, so a call refused before its run never
            calls it, and a provider returning ``None`` declines. Refused on a
            nested selector.
        metadata: A project's own per-operation facts, stored as given and read
            back by its own checks or audit hooks.
    """

    kind: SelectorKind
    selector: Callable[..., Any]
    permissions: Sequence[PermissionCheck] | None = None
    reads: Parameters = field(default_factory=Parameters)
    presenter: Presenter | None = None
    allow_none: bool = False
    select_related: Sequence[str] | None = None
    prefetch_related: Sequence[str | Prefetch] | None = None
    annotations: Mapping[str, Any] | None = None
    extend_queryset: Callable[..., QuerySet[Any]] | None = None
    # ``Any`` because the package never imports django-filter: a FilterSet is
    # read and applied by duck typing, so a stand-in answering ``.qs`` is one.
    filter_set: Any = None
    # The same word as ``ServiceSpec.affordances``, because it is the same
    # declaration read from the other side: there the conditions an operation
    # needs, here the answer for each row. Keyed by a name the caller chooses
    # rather than taken from a registry, since a ``ServiceSpec`` does not know
    # what it is called.
    affordances: Mapping[str, ServiceSpec] | None = None
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
            check_callable(self.filter_set, label=f"{label}.filter_set")
        _read_filters(self)
        # After the filters join, so a filter named ``user`` is refused as a
        # read named ``user`` is:
        # TestFilterSet.test_a_filter_named_after_a_reserved_seed_is_refused.
        check_reserved(self.reads, label=f"{label}.reads")
        check_presenter(self.presenter, label=label)
        if self.allow_none and kind is not SelectorKind.RETRIEVE:
            raise ImproperlyConfigured(
                f"{label}.allow_none describes a missing row, which only a RETRIEVE has."
            )
        for name in ("select_related", "prefetch_related"):
            value = getattr(self, name)
            if value is not None:
                if isinstance(value, str):
                    raise ImproperlyConfigured(
                        f"{label}.{name} is a string; pass a sequence, [{value!r}]."
                    )
                object.__setattr__(self, name, tuple(value))
        if self.extend_queryset is not None:
            check_callable(self.extend_queryset, label=f"{label}.extend_queryset")
        _check_affordances(self)
        check_providers(self, ("kwargs", "progress_reporter"), label=label)
        object.__setattr__(
            self, "preconditions", check_preconditions(self.preconditions, label=label)
        )
        check_metadata(self.metadata, label=label)

    def parameters(self) -> Parameters:
        """Everything this spec takes: its ``reads``."""
        return self.reads

    def output(self) -> Output | None:
        """What this spec returns, as its presenter declares it, or ``None``."""
        return self.presenter.output() if self.presenter is not None else None


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


def _check_affordances(spec: SelectorSpec) -> None:
    """Refuse an ``affordances`` mapping whose answers could not be told apart.

    At construction, like ``ServiceSpec``'s own check: a selector reaches
    transports that never ask before they present its rows.
    """
    # A proven cycle, and the one function-local import here. ``service_spec``
    # imports this module at its top for ``SelectorSpec``, so a top-level import
    # of ``ServiceSpec`` here fails whichever of the two loads first. By the
    # time any ``SelectorSpec`` is constructed both modules have finished
    # loading, so this resolves from ``sys.modules`` and runs nothing.
    from django_service_specs.specs.service_spec import ServiceSpec

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
        if not isinstance(service_spec, ServiceSpec):
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
