"""``ServiceSpec`` - a write, declared once for every transport."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.authorization.permission_check import PermissionCheck
from django_service_specs.output.output import Output
from django_service_specs.output.presenter import Presenter
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.utils import (
    check_callable,
    check_metadata,
    check_permissions,
    check_presenter,
    check_reserved,
)
from django_service_specs.types.affordance import Affordance
from django_service_specs.types.utils import is_row_condition
from django_service_specs.validation.validator import Validator


@dataclass(frozen=True, kw_only=True)
class ServiceSpec:
    """A write: what it takes, who may run it, what it acts on, what it returns.

    Dispatch runs it in a fixed order, once a deactivated principal has been
    refused: the shape check and the closed argument set, class-level
    authorization, target resolution, object-level authorization, validation
    with the target in the Validator's context, the ``affordances``, the
    service, then the output selector.

    Attributes:
        service: The operation. Called with the keywords it declares: the
            principal (``user``), the validated values (``data``, and each one
            spread by name), the resolved target (``instance`` or
            ``collection``), and any registered pool seed. It may be
            ``async def``; the kernel bridges it into ``atomic`` either way.
        permissions: The checks a principal must pass. ``None`` means none were
            declared, which registration and dispatch both refuse; an open
            operation says ``[Unrestricted()]``.
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
        metadata: A project's own per-operation facts, stored as given.
    """

    service: Callable[..., Any]
    permissions: Sequence[PermissionCheck] | None = None
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
        object.__setattr__(self, "affordances", _check_affordances(self))
        check_metadata(self.metadata, label=label)

    def target_selector_spec(self) -> SelectorSpec | None:
        """The selector resolving what the service acts on, if it declares one."""
        return self.instance_selector_spec or self.collection_selector_spec

    def parameters(self) -> Parameters:
        """Everything this spec takes: its target selector's reads, then its Validator's.

        Assembled on every call rather than at construction, because a
        Validator reading a model-backed declaration may need the app registry,
        and specs are commonly built at import time. A name both sources declare
        is refused here, as is one dispatch seeds itself.
        """
        target = self.target_selector_spec()
        own = self.validator.parameters() if self.validator is not None else Parameters()
        assembled = (target.parameters() if target is not None else Parameters()) + own
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
        # Two conjuncts, each held by its own test in tests/specs/test_service_spec.py:
        # ``test_a_callable_condition_on_a_collection_operation_is_fine`` fails
        # without the first, ``test_a_row_condition_on_a_one_row_operation_is_fine``
        # without the second.
        if is_row_condition(affordance.when) and spec.collection_selector_spec is not None:
            raise ImproperlyConfigured(
                f"ServiceSpec.affordances[{index}] ({affordance.code!r}) is a condition on "
                "the row, and this spec operates on a collection (a "
                "collection_selector_spec) with no single row to evaluate it against. "
                "Declare it on the per-row operation, or express a rule about the "
                "collection in the service."
            )
    return declared
