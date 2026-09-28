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
from django_service_specs.validation.validator import Validator


@dataclass(frozen=True, kw_only=True)
class ServiceSpec:
    """A write: what it takes, who may run it, what it acts on, what it returns.

    Dispatch runs it in a fixed order: the shape check and the closed argument
    set, class-level authorization, target resolution, object-level
    authorization, validation with the target in the Validator's context, the
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
        atomic: Run the service inside ``transaction.atomic()``.
        metadata: A project's own per-operation facts, stored as given.
    """

    service: Callable[..., Any]
    permissions: Sequence[PermissionCheck] | None = None
    validator: Validator | None = None
    instance_selector_spec: SelectorSpec | None = None
    collection_selector_spec: SelectorSpec | None = None
    output_selector_spec: SelectorSpec | None = None
    presenter: Presenter | None = None
    atomic: bool = True
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
