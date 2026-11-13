from __future__ import annotations

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.affordances.utils import rendered_affordances
from django_service_specs.output.file_presenter import FilePresenter
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource
from django_service_specs.types.selector_kind import SelectorKind


def file_output(spec: ServiceSpec | SelectorSpec | SpecSource) -> FilePresenter | None:
    """The [`FilePresenter`][django_service_specs.output.file_presenter.FilePresenter]
    ``spec`` presents its result through, or ``None`` when its result is not a file.

    What a transport asks when it registers a spec, so it serves a file, or
    refuses to, before the first call. The presenter is a selector spec's own,
    or a service spec's ``presenter_for_output()``: its own, or its output
    selector's.

    ``allow_none`` is allowed: a ``None`` is answered as the transport answers
    nothing for any other spec.

    Raises:
        django.core.exceptions.ImproperlyConfigured: The file would be one of
            many: presented by a ``LIST`` selector spec, or by a service spec
            whose output selector is a ``LIST``, or declared ``many`` or
            ``returns_many``. A list of files has no answer on any transport.
            Also a file presented through rendered ``affordances`` (a selector
            spec's own, or a service spec's output selector's), which are keys
            on an object. A service spec's own ``affordances`` check the call
            and are never presented, so they are allowed.
    """
    compiled = kernel_spec(spec)
    if isinstance(compiled, SelectorSpec):
        presenter = compiled.presenter
        selector = compiled
    else:
        presenter = compiled.presenter_for_output()
        selector = compiled.output_selector_spec
    if not isinstance(presenter, FilePresenter):
        return None
    if selector is not None and selector.kind is SelectorKind.LIST:
        _refuse(compiled, "presents a list of rows")
    if isinstance(compiled, ServiceSpec) and compiled.many:
        _refuse(compiled, "is declared many")
    if isinstance(compiled, ServiceSpec) and compiled.returns_many:
        _refuse(compiled, "is declared returns_many")
    if rendered_affordances(compiled) is not None:
        _refuse(compiled, "presents affordances, which are keys on an object")
    return presenter


def _refuse(spec: ServiceSpec | SelectorSpec, why: str) -> None:
    raise ImproperlyConfigured(
        f"{type(spec).__name__} presents a file through FilePresenter and {why}. A file is "
        "one result: present it from a single-row spec."
    )
