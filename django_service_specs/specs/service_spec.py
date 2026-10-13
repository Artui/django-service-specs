"""``ServiceSpec`` - a write, declared once for every transport."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.authorization.permission_check import PermissionCheck
from django_service_specs.output.output import Output
from django_service_specs.output.presenter import Presenter
from django_service_specs.parameters.parameter import Parameter
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.utils import (
    check_callable,
    check_metadata,
    check_permissions,
    check_preconditions,
    check_presenter,
    check_providers,
    check_reserved,
)
from django_service_specs.types.affordance import Affordance
from django_service_specs.types.utils import is_row_condition
from django_service_specs.validation.validator import Validator

# The default ``many_argument``, djangorestframework-services' own, so a spec
# moving between the two packages keeps the argument a caller sends.
_DEFAULT_MANY_ARGUMENT = "items"
# ASCII by the class rather than ``str.isidentifier``, which admits any
# Unicode letter a header, a form field or a shell may not carry.
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass(frozen=True, kw_only=True)
class ServiceSpec:
    """A write: what it takes, who may run it, what it acts on, what it returns.

    Dispatch runs it in a fixed order, once a deactivated principal has been
    refused: the shape check and the closed argument set, class-level
    authorization, target resolution, object-level authorization, validation
    with the target in the Validator's context, the ``affordances``, the
    ``preconditions``, the service, then the output selector.

    Attributes:
        service: The operation. Called with the keywords it declares: the
            principal (``user``), the validated values (``data``, and each one
            spread by name), the resolved target (``instance`` or
            ``collection``), and any registered pool seed. It may be
            ``async def``; the kernel bridges it into ``atomic`` either way.
        permissions: The checks a principal must pass. ``None`` means none were
            declared, which registration and dispatch both refuse; an open
            operation says ``[Unrestricted()]``.
        reads: The arguments the service, its providers and its preconditions
            read with no Validator in front of them - the ``project_pk`` a
            create's ``kwargs`` provider scopes by - as a selector spec's
            ``reads`` are. Part of ``parameters()``, after the target selector's
            and before the Validator's, so the schema, the closed argument set
            and the shape check cover them; never handed to the Validator. A
            name the target selector also reads is refused at construction,
            and one the Validator declares when ``parameters()`` is assembled.
        partial: Whether a call may leave out any of the Validator's
            parameters, as an HTTP ``PATCH`` does: the shape check does not
            refuse an absent one, at any depth, and the Validator is told
            through ``ValidationContext.partial``. The spec's ``reads`` and its
            target selector's stay required as declared, so a partial update
            still names its row. On a ``many`` spec it holds inside every row,
            and the list itself stays required.
        many: Whether the call carries a list of rows, each validated by the
            ``validator``, under the one argument ``many_argument`` names, for
            one run of the service over all of them. The service receives the
            validated rows as ``data``, a list, and the validated values as
            ``many_argument``, a list of their mappings; neither is spread by
            field. Every row is checked and validated before the service runs,
            and every failing row is refused in one ``InvalidArguments``,
            addressed by its ``int`` index under ``many_argument``. Declared
            with a ``validator``, since the rows are the arguments it validates,
            and with no target selector, since a list of rows resolves no
            target.
        many_argument: The argument a ``many`` spec's list travels under, an
            ASCII identifier. ``"items"`` by default. Beside it a ``many``
            spec takes its ``reads`` and nothing else, so an argument asked
            once for the whole call - a confirmation - is a read. Naming
            anything but the default on a spec that is not ``many`` is
            refused, since nothing would read it.
        validator: Validates the arguments its own ``parameters()`` declare. A
            [`Validator`][django_service_specs.validation.validator.Validator]
            instance; ``None`` for an operation that takes no arguments beyond
            its target.
        instance_selector_spec: A ``RETRIEVE`` resolving the one row the service
            acts on, from the arguments its ``reads`` declare. A missing row is
            not-found and the service never runs.
        collection_selector_spec: A ``LIST`` resolving the rows a bulk operation
            acts on. At most one of the two target selectors.
        output_selector_spec: Re-reads what the service produced, with its
            return value as ``result`` in the pool - the way to return a row
            with fresh annotations, or a list after a bulk write.
        presenter: Renders the dispatch value. When ``None``, the output
            selector's presenter is used; declaring both is refused.
        allow_none: Declares that a service with no output selector may
            present nothing: its return may be ``None``, and
            [`spec_output_schema`][django_service_specs.schema.spec_output_schema.spec_output_schema]
            then admits ``"null"``. Declaration-only, as on a selector spec's
            schema: dispatch presents a ``None`` the service returned whatever
            this says, because whether a service may return one is not
            otherwise in its declaration. Left ``False``, the item stays the
            strict object its presenter declares. Beside an output selector it
            changes nothing: a ``RETRIEVE`` re-read admits ``"null"`` already,
            and a ``LIST`` one presents its rows rather than the service's
            return.
        affordances: What must be true for this operation to be possible right
            now, as a sequence of ``Affordance`` declarations, kept as a tuple
            in declaration order. ``enforce_affordances`` answers them at the
            call: the first one not met refuses it with an
            ``ActionUnavailable`` carrying its ``code``, and the service does
            not run. Every condition on the row is answered by **one** query,
            however many are declared. A condition on the row needs a single
            resolved row, so it is refused beside a
            ``collection_selector_spec``. It is a check at the moment of the
            call, not a lock: the service still re-validates whatever it relies
            on. ``None`` declares nothing and costs nothing - no query, no call.
            Codes must be unique within a spec, because the code is how a
            reader tells the conditions apart.
        atomic: Run the service inside ``transaction.atomic()``.
        idempotent: Whether repeating the call with the same arguments leaves
            the same state as making it once. Declaration-only: nothing in this
            package reads it, because idempotency is a property of the service
            the author writes, not something a dispatcher can arrange. It is
            here so the fact is stated once, on the spec, and every transport
            reads the same answer - a retry policy, a queue's redelivery
            handling, an agent tool annotation. ``None`` means **undeclared**
            and is the default: a transport that turns the signal into a
            published annotation must be able to tell "nothing was said" from a
            declared ``False``, or every spec ever written starts claiming it is
            not idempotent. ``atomic`` is a different question: it says a single
            call is all-or-nothing, not that a second call is a no-op.
        preconditions: Raise-to-abort rules, a sequence of callables each called
            with the keywords it declares from the service's pool, after the
            ``affordances`` and before the service, outside its transaction. The
            return value is ignored. Kept as a tuple in declaration order.
        kwargs: A provider of extra pool entries: called with the keywords it
            declares from the call's pool, it returns a mapping merged into the
            pool the service is called from after the caller's arguments, so a
            key it answers is the author's value whatever the caller sent. A
            value of ``UNSET`` declines its key. Annotate its return as a
            ``TypedDict`` and ``provider_keys`` reads which keys it fills
            before it runs.
        input_data: A provider of server-owned input: called with the keywords
            it declares from the call's pool, the resolved target among them,
            it returns a mapping merged onto the caller's arguments before the
            Validator sees them, after the caller's, so its keys are the
            author's values. A value of ``UNSET`` declines its key.
        progress_reporter: A provider of a
            [`ProgressReporter`][django_service_specs.types.progress_reporter.ProgressReporter]
            sink the service reports to beside the transport's - a task record,
            an audit trail - called with the keywords it declares from the base
            pool. Resolved on first use, so a call refused before its run never
            calls it, and a provider returning ``None`` declines.
        metadata: A project's own per-operation facts, stored as given.
    """

    service: Callable[..., Any]
    permissions: Sequence[PermissionCheck] | None = None
    # ``SelectorSpec``'s word for the arguments a callable reads with no
    # Validator in front of it, so one word means one thing on both specs.
    reads: Parameters = field(default_factory=Parameters)
    # A bare bool rather than djangorestframework-services' ``bool | None``,
    # where ``None`` reads the HTTP method: this package has no method to read,
    # so the declaration is the answer.
    partial: bool = False
    # djangorestframework-services' names for the same declaration, so a spec
    # moving between the two packages keeps its field names. A plain ``str``
    # carrying its default rather than ``None`` meaning it, so every reader sees
    # the name in force and no transport restates the default.
    many: bool = False
    many_argument: str = _DEFAULT_MANY_ARGUMENT
    validator: Validator | None = None
    instance_selector_spec: SelectorSpec | None = None
    collection_selector_spec: SelectorSpec | None = None
    output_selector_spec: SelectorSpec | None = None
    presenter: Presenter | None = None
    # The name a ``SelectorSpec`` already uses for a value that may be ``None``,
    # so one word means one thing on both specs.
    allow_none: bool = False
    # Not ``availability``: that names the answer rather than the declaration,
    # and in Django reads as scheduling. Not ``conditions``: django-fsm's word
    # for the same idea on a transition, which would promise a state machine
    # this is not. ``affordances`` is the established name for the
    # state-dependent set of things a resource currently offers, and it names
    # the object's side of the question - which is also the key a list reports
    # it under.
    affordances: Sequence[Affordance] | None = None
    atomic: bool = True
    # A bare adjective, to sit with ``atomic``. Not ``idempotent_hint``: that is
    # one transport's spelling, and the fact is about the operation, not about
    # the annotation somebody derives from it. Not ``safe``: RFC 9110 reserves
    # that for "no side effects at all", which a write never is. ``bool | None``
    # rather than ``bool``, because silence must not read as a claim.
    idempotent: bool | None = None
    # djangorestframework-services' names for the same declarations, so a spec
    # moving between the two packages keeps its field names. Not ``guards``
    # for the first: the create and collection guard is a permission check's.
    # Typed open (``...``) because each is bound from the keyword pool, so its
    # signature is whichever subset of the pool it declares.
    preconditions: Sequence[Callable[..., None]] | None = None
    kwargs: Callable[..., Mapping[str, Any]] | None = None
    input_data: Callable[..., Mapping[str, Any]] | None = None
    progress_reporter: Callable[..., Any] | None = None
    metadata: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        label = "ServiceSpec"
        check_callable(self.service, label=f"{label}.service")
        object.__setattr__(self, "permissions", check_permissions(self.permissions, label=label))
        if self.validator is not None and not isinstance(self.validator, Validator):
            what = (
                f"the class {self.validator.__name__}"
                if isinstance(self.validator, type)
                else type(self.validator).__name__
            )
            raise ImproperlyConfigured(
                f"{label}.validator is {what}, which is not a Validator instance. "
                "Wrap the declaration in an adapter, such as DataclassValidator(...)."
            )
        _check_selector(self.instance_selector_spec, SelectorKind.RETRIEVE, "instance")
        _check_selector(self.collection_selector_spec, SelectorKind.LIST, "collection")
        if self.instance_selector_spec is not None and self.collection_selector_spec is not None:
            raise ImproperlyConfigured(
                f"{label} declares both an instance and a collection selector; an "
                "operation acts on one row or on a collection of them, not both."
            )
        if self.output_selector_spec is not None and not isinstance(
            self.output_selector_spec, SelectorSpec
        ):
            raise ImproperlyConfigured(f"{label}.output_selector_spec must be a SelectorSpec.")
        check_presenter(self.presenter, label=label)
        if (
            self.presenter is not None
            and self.output_selector_spec is not None
            and self.output_selector_spec.presenter is not None
        ):
            raise ImproperlyConfigured(
                f"{label} declares a presenter and so does its output selector. One "
                "value is presented once; keep the one that describes what is returned."
            )
        _check_many(self)
        object.__setattr__(self, "affordances", _check_affordances(self))
        _check_reads(self)
        _check_nested(self)
        check_providers(self, ("kwargs", "input_data", "progress_reporter"), label=label)
        object.__setattr__(
            self, "preconditions", check_preconditions(self.preconditions, label=label)
        )
        check_metadata(self.metadata, label=label)

    def target_selector_spec(self) -> SelectorSpec | None:
        """The selector resolving what the service acts on, if it declares one."""
        return self.instance_selector_spec or self.collection_selector_spec

    def parameters(self) -> Parameters:
        """Everything this spec takes: its target selector's reads, its own, then its Validator's.

        On a ``many`` spec the Validator's parameters are each row's, so the
        top level is the spec's ``reads`` and then the list itself: a
        required array under ``many_argument`` whose rows are the Validator's
        parameters. A row's field is no top-level argument, so it may share a
        read's name.

        Assembled on every call rather than at construction, because a
        Validator reading a model-backed declaration may need the app registry,
        and specs are commonly built at import time. A name two sources declare
        is refused here, as is one dispatch seeds itself; the two that need no
        Validator, the target's reads and the spec's, were refused at
        construction already.
        """
        own = self.validator.parameters() if self.validator is not None else Parameters()
        if self.many:
            own = Parameters.of(_the_list(self.many_argument, items=own))
        assembled = _beside_the_target(self) + own
        return check_reserved(assembled, label="ServiceSpec.validator")

    def presenter_for_output(self) -> Presenter | None:
        """The presenter the dispatch value is rendered with: this spec's or its output selector's."""
        if self.presenter is not None:
            return self.presenter
        out = self.output_selector_spec
        return out.presenter if out is not None else None

    def output(self) -> Output | None:
        """What this spec returns, as its presenter declares it, or ``None``."""
        presenter = self.presenter_for_output()
        return presenter.output() if presenter is not None else None


def _beside_the_target(spec: ServiceSpec) -> Parameters:
    """The target selector's reads, then the spec's own: the half known at construction."""
    target = spec.target_selector_spec()
    return (target.parameters() if target is not None else Parameters()) + spec.reads


def _the_list(name: str, *, items: Parameters | None = None) -> Parameter:
    """A ``many`` spec's list: required, each element a row of ``items``."""
    return Parameter(name, "array", required=True, items=items)


def _check_many(spec: ServiceSpec) -> None:
    """Refuse a ``many_argument`` no caller could send, and a ``many`` spec nothing could run.

    At construction, as every check here: a spec reaches transports that
    dispatch it without ever asking. A ``many`` spec with no Validator would
    hand the service rows nobody declared or checked; one with a target
    selector would declare a lookup dispatch never runs, since a list of rows
    resolves no target.
    """
    name: Any = spec.many_argument
    # Two operands, each held by its own case of
    # test_a_name_that_is_not_an_ascii_identifier_is_refused: ``3`` the first,
    # since the pattern raises ``TypeError`` on a non-string, and ``"1st"`` the
    # second. ``fullmatch``, or a valid prefix passes (``"rows!"``).
    if not isinstance(name, str) or _IDENTIFIER.fullmatch(name) is None:
        raise ImproperlyConfigured(
            f"ServiceSpec.many_argument must be an ASCII identifier; got {name!r}. It is the "
            "name a caller sends a many spec's list of rows under."
        )
    if not spec.many:
        # Only a name other than the default: the field carries its default on
        # every spec, so writing it out declares nothing
        # (test_the_default_name_written_out_without_many_is_not_a_declaration).
        if name != _DEFAULT_MANY_ARGUMENT:
            raise ImproperlyConfigured(
                f"ServiceSpec declares many_argument={name!r} without many=True. It names "
                "the argument a list of rows travels under, and this spec takes no list; "
                "set many=True or remove it."
            )
        return
    if spec.validator is None:
        raise ImproperlyConfigured(
            "ServiceSpec declares many=True with no validator. Each row is validated by "
            "the spec's Validator, which also declares what a row is; declare one."
        )
    for role in ("instance", "collection"):
        if getattr(spec, f"{role}_selector_spec") is not None:
            raise ImproperlyConfigured(
                f"ServiceSpec declares a {role}_selector_spec with many=True. A list of rows "
                "resolves no target, so dispatch would never run the lookup; remove it, or "
                "drop many=True."
            )
    # The list beside the reads is two sources of one argument if a read shares
    # its name, which ``+`` refuses, and a seed's name is refused as any
    # parameter's is. Neither needs the Validator, so both are refused here.
    check_reserved(spec.reads + Parameters.of(_the_list(name)), label="ServiceSpec.many_argument")


def _check_reads(spec: ServiceSpec) -> None:
    """Refuse ``reads`` that are not Parameters, name a seed, or repeat the target's.

    At construction, because none of it needs the Validator: a read the
    target selector also declares is two sources of one argument, which ``+``
    refuses, and refusing it here rather than on the first call keeps the
    error beside the declaration.
    """
    if not isinstance(spec.reads, Parameters):
        raise ImproperlyConfigured("ServiceSpec.reads must be Parameters.")
    check_reserved(spec.reads, label="ServiceSpec.reads")
    _beside_the_target(spec)


def _check_nested(spec: ServiceSpec) -> None:
    """Refuse a nested selector declaring what dispatch never runs for it.

    A nested selector is a step of this spec's run, not a run of its own, so
    its ``preconditions`` and ``progress_reporter`` would be skipped in
    silence, and a guard skipped in silence is the failure a construction
    check exists to prevent. A target selector's ``kwargs`` scope its lookup
    and run; an output selector re-reads what the service produced, with no
    caller's arguments for a provider to stand beside, so its ``kwargs`` are
    refused too.
    """
    for role in ("instance", "collection", "output"):
        nested: SelectorSpec | None = getattr(spec, f"{role}_selector_spec")
        if nested is None:
            continue
        label = f"ServiceSpec.{role}_selector_spec"
        if nested.preconditions is not None:
            raise ImproperlyConfigured(
                f"{label} declares preconditions, which are never run on a nested selector. "
                "Declare them on this ServiceSpec, whose pool carries the resolved target."
            )
        if nested.progress_reporter is not None:
            raise ImproperlyConfigured(
                f"{label} declares a progress_reporter, which is never run on a nested "
                "selector. Declare it on this ServiceSpec, whose service is the run."
            )
        # Two conjuncts, each held by its own test in tests/specs/test_service_spec.py:
        # TestEngineFields.test_a_target_selector_s_kwargs_provider_is_its_own_to_run
        # fails without the first, and
        # test_the_output_is_the_spec_presenters_or_else_the_output_selectors
        # without the second.
        if role == "output" and nested.kwargs is not None:
            raise ImproperlyConfigured(
                f"{label} declares kwargs, which an output selector never runs: it re-reads "
                "the service's result. Read what it needs from ``result`` or a pool seed."
            )


def _check_selector(spec: SelectorSpec | None, kind: SelectorKind, role: str) -> None:
    if spec is None:
        return
    if not isinstance(spec, SelectorSpec):
        raise ImproperlyConfigured(f"ServiceSpec.{role}_selector_spec must be a SelectorSpec.")
    if spec.kind is not kind:
        raise ImproperlyConfigured(
            f"ServiceSpec.{role}_selector_spec is a {spec.kind.name}; it must be a {kind.name}."
        )


def _check_affordances(spec: ServiceSpec) -> tuple[Affordance, ...] | None:
    """Refuse an ``affordances`` declaration that could never be honoured, and normalize it.

    At construction, like every other check here: a spec reaches transports
    that dispatch it without ever asking, and each of these would otherwise
    surface on the first call through exactly those.
    """
    affordances: Any = spec.affordances
    if affordances is None:
        return None
    # ``Sequence`` alone refuses a single ``Affordance`` too - a dataclass is not
    # one - as well as a set, whose order would decide which refusal a caller
    # sees, and a generator, which the first call would exhaust.
    if not isinstance(affordances, Sequence):
        raise ImproperlyConfigured(
            "ServiceSpec.affordances takes a sequence of Affordance declarations; got "
            f"{type(affordances).__name__}. Wrap a single one in a list: affordances=[...]."
        )
    declared = tuple(affordances)
    codes: set[str] = set()
    for index, affordance in enumerate(declared):
        if not isinstance(affordance, Affordance):
            raise ImproperlyConfigured(
                f"ServiceSpec.affordances[{index}] must be an Affordance; got "
                f"{type(affordance).__name__}."
            )
        if affordance.code in codes:
            raise ImproperlyConfigured(
                f"ServiceSpec.affordances declares the code {affordance.code!r} twice. A "
                "code is how a client tells one refusal from another, so each must be "
                "unique within a spec."
            )
        codes.add(affordance.code)
        # Three operands, each held by its own test in tests/specs/test_service_spec.py:
        # ``test_a_callable_condition_on_a_collection_operation_is_fine`` fails
        # without the first,
        # ``test_a_row_condition_on_a_collection_operation_is_refused`` without the
        # second, ``test_a_row_condition_on_a_many_spec_is_refused`` without the
        # third, and ``test_a_row_condition_on_a_one_row_operation_is_fine`` if the
        # last two are dropped together.
        if is_row_condition(affordance.when) and (
            spec.collection_selector_spec is not None or spec.many
        ):
            what = (
                "a list of rows (many=True)"
                if spec.many
                else "a collection (a collection_selector_spec)"
            )
            raise ImproperlyConfigured(
                f"ServiceSpec.affordances[{index}] ({affordance.code!r}) is a condition on "
                f"the row, and this spec operates on {what} with no single row to evaluate "
                "it against. Declare it on the per-row operation, or express a rule about "
                "the rows in the service."
            )
    return declared
