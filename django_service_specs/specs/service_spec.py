from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, fields, replace
from typing import Any, NamedTuple

from django.core.exceptions import ImproperlyConfigured
from typing_extensions import Self

from django_service_specs.authorization.permission_check import PermissionCheck
from django_service_specs.output.output import Output
from django_service_specs.output.presenter import Presenter
from django_service_specs.parameters.parameters import Parameter, Parameters
from django_service_specs.pool.provider_keys import provider_keys
from django_service_specs.specs.check_permissions import check_permissions
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.utils import (
    check_call_seeds,
    check_changes,
    check_metadata,
    check_preconditions,
    check_presenter,
    check_providers,
    check_reserved,
    describe,
)
from django_service_specs.types.affordance import Affordance
from django_service_specs.types.affordance_declarer import AffordanceDeclarer
from django_service_specs.types.selector_kind import SelectorKind
from django_service_specs.types.utils import callable_name, check_callable, is_row_condition
from django_service_specs.validation.validator import Validator
from django_service_specs.validation.validator_parameters import validator_parameters

# The default ``many_argument``, djangorestframework-services' own, so a spec
# moving between the two packages keeps the argument a caller sends.
_DEFAULT_MANY_ARGUMENT = "items"
# ASCII by the class rather than ``str.isidentifier``, which admits any
# Unicode letter a header, a form field or a shell may not carry.
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# The Validator methods dispatch calls: ``validated``, which calls ``validate``.
_VALIDATOR_METHODS = ("validate", "validated", "validated_many")


@dataclass(frozen=True, kw_only=True)
class ServiceSpec(AffordanceDeclarer):
    """A write: what it takes, who may run it, what it acts on, what it returns."""

    service: Callable[..., Any]
    permissions: Sequence[PermissionCheck] | None = None
    reads: Parameters = field(default_factory=Parameters)
    shapes: Parameters = field(default_factory=Parameters)
    partial: bool = False
    many: bool = False
    many_argument: str = _DEFAULT_MANY_ARGUMENT
    many_min_length: int | None = None
    many_max_length: int | None = None
    validator: Validator | None = None
    instance_selector_spec: SelectorSpec | None = None
    collection_selector_spec: SelectorSpec | None = None
    output_selector_spec: SelectorSpec | None = None
    presenter: Presenter | None = None
    allow_none: bool = False
    returns_many: bool = False
    affordances: Sequence[Affordance] | None = None
    atomic: bool = True
    idempotent: bool | None = None
    preconditions: Sequence[Callable[..., None]] | None = None
    kwargs: Callable[..., Mapping[str, Any]] | None = None
    input_data: Callable[..., Mapping[str, Any]] | None = None
    progress_reporter: Callable[..., Any] | None = None
    metadata: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        # Never awaited, so an ``async def`` one would hand dispatch a coroutine.
        label = "ServiceSpec"
        check_callable(self.service, label=f"{label}.service")
        object.__setattr__(self, "permissions", check_permissions(self.permissions, label=label))
        if self.validator is not None and not isinstance(self.validator, Validator):
            raise ImproperlyConfigured(
                f"{label}.validator is {describe(self.validator)}, which is not a Validator "
                "instance. Wrap the declaration in an adapter, such as DataclassValidator(...)."
            )
        if self.validator is not None:
            for method in _VALIDATOR_METHODS:
                check_callable(
                    getattr(self.validator, method), label=f"{label}.validator.{method}", sync=True
                )
        _check_partial(self)
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
        _check_returns_many(self)
        object.__setattr__(self, "affordances", _check_affordances(self))
        _check_reads(self)
        _check_shapes(self)
        _check_nested(self)
        check_providers(self, ("kwargs", "input_data", "progress_reporter"), label=label)
        if self.input_data is not None and self.validator is None:
            raise ImproperlyConfigured(
                f"{label}.input_data merges over the Validator's arguments, and this {label} "
                "has no validator, so it would reach nothing: the service is handed none of "
                "it. Declare a validator, or use kwargs for a value the service reads."
            )
        _check_reach(self, _read_seats(self))
        object.__setattr__(
            self, "preconditions", check_preconditions(self.preconditions, label=label)
        )
        check_metadata(self.metadata, label=label)

    def derive(self, **changes: object) -> Self:
        """A new spec of this class with the named fields replaced."""
        check_changes(fields(self), changes, label=type(self).__name__)
        return replace(self, **changes)

    def target_selector_spec(self) -> SelectorSpec | None:
        """The selector resolving what the service acts on, if it declares one."""
        return self.instance_selector_spec or self.collection_selector_spec

    def as_kernel_spec(self) -> Self:
        """This spec, as its own compiled form."""
        return self

    def parameters(self, *, call_context: dict[str, Any] | None = None) -> Parameters:
        """Everything this spec takes: its selector's reads, its shapes, and its Validator's."""
        own = (
            validator_parameters(self.validator, call_context=call_context)
            if self.validator is not None
            else Parameters()
        )
        _check_reach(
            self,
            [*_read_seats(self), _Seat("ServiceSpec.validator", own, "ServiceSpec.input_data")],
        )
        if self.many:
            own = Parameters.of(_the_list(self, items=own))
        assembled = _beside_the_target(self) + self.shapes + own
        return check_reserved(assembled, label="ServiceSpec.validator")

    def presenter_for_output(self) -> Presenter | None:
        """The presenter the dispatch value renders with: this spec's or its output selector's."""
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


def _the_list(spec: ServiceSpec, *, items: Parameters | None = None) -> Parameter:
    """A ``many`` spec's list: required, bounded as declared, each element a row of ``items``."""
    return Parameter(
        spec.many_argument,
        "array",
        required=True,
        items=items,
        min_length=spec.many_min_length,
        max_length=spec.many_max_length,
    )


def _check_many(spec: ServiceSpec) -> None:
    """Refuse a ``many_argument`` no caller could send, and a ``many`` spec nothing could run."""
    name: Any = spec.many_argument
    if not isinstance(name, str) or _IDENTIFIER.fullmatch(name) is None:
        raise ImproperlyConfigured(
            f"ServiceSpec.many_argument must be an ASCII identifier; got {name!r}. It is the "
            "name a caller sends a many spec's list of rows under."
        )
    if not spec.many:
        if name != _DEFAULT_MANY_ARGUMENT:
            raise ImproperlyConfigured(
                f"ServiceSpec declares many_argument={name!r} without many=True. It names "
                "the argument a list of rows travels under, and this spec takes no list; "
                "set many=True or remove it."
            )
        for field_name in ("many_min_length", "many_max_length"):
            length = getattr(spec, field_name)
            if length is not None:
                raise ImproperlyConfigured(
                    f"ServiceSpec declares {field_name}={length!r} without many=True. It bounds "
                    "the list of rows a many call carries, and this spec takes no list; set "
                    "many=True or remove it."
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
    try:
        the_list = _the_list(spec)
    except ImproperlyConfigured as refused:
        raise ImproperlyConfigured(
            "ServiceSpec.many_min_length and many_max_length bound the list under "
            f"ServiceSpec.many_argument, which takes no such bound: {refused}"
        ) from refused
    check_reserved(spec.reads + Parameters.of(the_list), label="ServiceSpec.many_argument")


def _check_returns_many(spec: ServiceSpec) -> None:
    """Refuse ``returns_many`` beside a declaration that already decides what is presented."""
    if spec.returns_many and spec.output_selector_spec is not None:
        instead = (
            "remove returns_many; without the output selector, many presents the service's "
            "own return as a list already."
            if spec.many
            else "remove returns_many, or remove the output selector to present the "
            "service's own return as a list."
        )
        raise ImproperlyConfigured(
            "ServiceSpec declares returns_many=True beside an output_selector_spec. The "
            "output selector's kind decides what is presented, and a LIST re-read presents "
            f"rows already; {instead}"
        )
    if spec.returns_many and spec.many:
        raise ImproperlyConfigured(
            "ServiceSpec declares returns_many=True with many=True. A many spec with no "
            "output selector already presents what its service returns as a list; remove "
            "returns_many."
        )


def _check_partial(spec: ServiceSpec) -> None:
    """Refuse ``partial`` with no Validator, or one that builds every field."""
    if not spec.partial:
        return
    validator = spec.validator
    service = callable_name(spec.service)
    if validator is None:
        raise ImproperlyConfigured(
            f"ServiceSpec for {service} declares partial=True with no validator. partial "
            "lets a call leave out the Validator's parameters, and with no Validator there "
            "are none, so it would change nothing: declare a validator, or drop partial."
        )
    if not validator.supports_partial:
        raise ImproperlyConfigured(
            f"ServiceSpec for {service} declares partial=True with a "
            f"{type(validator).__qualname__}, which cannot validate a partial call: it "
            "builds every field, and a partial call may leave any out. A partial call needs "
            "a Validator that can bind only what was sent, such as FormValidator, or a "
            "custom one; drop partial, or change the validator."
        )


def _check_reads(spec: ServiceSpec) -> None:
    """Refuse ``reads`` that are not Parameters, name a seed, or repeat the target's."""
    if not isinstance(spec.reads, Parameters):
        raise ImproperlyConfigured("ServiceSpec.reads must be Parameters.")
    check_reserved(spec.reads, label="ServiceSpec.reads")
    check_call_seeds(spec.reads, label="ServiceSpec.reads", reflected_seated=True)
    target = spec.target_selector_spec()
    if target is not None:
        check_call_seeds(target.reads, label=f"{_target_label(spec)}.reads", reflected_seated=True)
    _beside_the_target(spec)


def _check_shapes(spec: ServiceSpec) -> None:
    """Refuse ``shapes`` that are not Parameters, name a seed, or repeat a read or the list."""
    if not isinstance(spec.shapes, Parameters):
        raise ImproperlyConfigured("ServiceSpec.shapes must be Parameters.")
    check_reserved(spec.shapes, label="ServiceSpec.shapes")
    check_call_seeds(spec.shapes, label="ServiceSpec.shapes", reflected_seated=False)
    beside = _beside_the_target(spec) + spec.shapes
    if spec.many:
        beside + Parameters.of(_the_list(spec))


class _Seat(NamedTuple):
    """Where parameters are declared, what declares them, and the one provider whose values reach
    them, if any."""

    where: str
    declared: Parameters
    reaching: str | None
    callers_list: bool = False


def _read_seats(spec: ServiceSpec) -> list[_Seat]:
    """The seats known at construction: reads, the target selector's, and shapes."""
    seats: list[_Seat] = [
        _Seat("ServiceSpec.reads", spec.reads, "ServiceSpec.kwargs"),
        _Seat("ServiceSpec.shapes", spec.shapes, None),
    ]
    if spec.many:
        seats.append(
            _Seat(
                "ServiceSpec.many_argument",
                Parameters.of(_the_list(spec)),
                None,
                callers_list=True,
            )
        )
    target = spec.target_selector_spec()
    if target is not None:
        label = _target_label(spec)
        seats.append(_Seat(f"{label}.reads", target.reads, f"{label}.kwargs"))
    return seats


def _target_label(spec: ServiceSpec) -> str:
    role = "instance" if spec.instance_selector_spec is not None else "collection"
    return f"ServiceSpec.{role}_selector_spec"


def _check_reach(spec: ServiceSpec, seats: list[_Seat]) -> None:
    """Refuse a typed provider annotated to fill a parameter its values never reach."""
    target = spec.target_selector_spec()
    providers: list[tuple[str, Callable[..., Any] | None]] = [
        ("ServiceSpec.kwargs", spec.kwargs),
        ("ServiceSpec.input_data", spec.input_data),
    ]
    if target is not None:
        providers.append((f"{_target_label(spec)}.kwargs", target.kwargs))
    for name, provider in providers:
        keys = provider_keys(provider)
        if keys is None:
            continue
        for where, declared, reaching, callers_list in seats:
            held = keys.filled | keys.declinable if callers_list else keys.filled
            stray = sorted(held & declared.names())
            if stray and name != reaching:
                if reaching is not None:
                    remedy = f"Only {reaching} fills {where}; fill the key there, or rename it."
                elif callers_list:
                    remedy = (
                        f"No provider fills {where}, which is the caller's list; rename the "
                        "key or the many_argument."
                    )
                else:
                    remedy = (
                        f"No provider fills {where}, whose values reach only the presenter; "
                        "rename the key."
                    )
                raise ImproperlyConfigured(
                    f"{name} is annotated to fill {stray}, which {where} declares, and its "
                    f"values never reach {where}, so dispatch would still demand {stray} of "
                    f"the caller. {remedy}"
                )


def _check_nested(spec: ServiceSpec) -> None:
    """Refuse a nested selector declaring what dispatch never runs for it."""
    for role in ("instance", "collection", "output"):
        nested: SelectorSpec | None = getattr(spec, f"{role}_selector_spec")
        if nested is None:
            continue
        label = f"ServiceSpec.{role}_selector_spec"
        if nested.permissions is not None:
            raise ImproperlyConfigured(
                f"{label} declares permissions, which a nested selector never asks: the spec "
                "being dispatched is what authorizes. Declare them on this ServiceSpec, and drop "
                "them from the nested selector, or nest spec.derive(permissions=None) to reuse "
                "a selector spec that is also registered or dispatched on its own."
            )
        if nested.preconditions is not None:
            raise ImproperlyConfigured(
                f"{label} declares preconditions, which are never run on a nested selector. "
                "Declare them on this ServiceSpec, whose pool carries the resolved target."
            )
        if nested.shapes:
            raise ImproperlyConfigured(
                f"{label} declares shapes, which a nested selector's call never carries: this "
                "ServiceSpec's call is the one presented. Declare them on this ServiceSpec, "
                "whose presenter is handed them, its output selector's included, and nest "
                "spec.derive(shapes=Parameters()) to reuse a selector spec declaring its own."
            )
        if nested.progress_reporter is not None:
            raise ImproperlyConfigured(
                f"{label} declares a progress_reporter, which is never run on a nested "
                "selector. Declare it on this ServiceSpec, whose service is the run."
            )
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
    """Refuse an ``affordances`` declaration that could never be honoured, and normalize it."""
    affordances: Any = spec.affordances
    if affordances is None:
        return None
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
