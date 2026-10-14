"""``can_present_nothing`` - whether a spec's dispatch can present ``None``."""

from __future__ import annotations

from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource


def can_present_nothing(spec: ServiceSpec | SelectorSpec | SpecSource) -> bool:
    """Whether a successful dispatch of ``spec`` may present ``None`` as its result.

    The question an output schema answers before it admits ``"null"``, asked in
    one place so that
    [`spec_output_schema`][django_service_specs.schema.spec_output_schema.spec_output_schema]
    and every transport advertising an output schema of its own give the same
    answer:

    - **A ``SelectorSpec``**: a ``RETRIEVE`` declaring ``allow_none``, which
      presents ``None`` for a missing row. Without ``allow_none`` a missing row
      is not-found, which a transport answers in its own terms and never
      presents. A ``LIST`` presents its rows, ``[]`` for none, and never
      ``None``, whatever ``allow_none`` says.
    - **A ``ServiceSpec`` with an ``output_selector_spec``**: a ``RETRIEVE``
      re-read, whatever ``allow_none`` says, because once the service has run
      a re-read that finds nothing is ``None`` rather than not-found, and
      reporting not-found would tell the caller a committed write did not
      happen. A ``LIST`` re-read presents rows and never ``None``.
    - **Any other ``ServiceSpec``** presents the service's own return, and
      answers its own ``allow_none``. That is a declaration rather than an
      observation: an undeclared ``None`` is still presented, against a schema
      that does not admit it.

    ``many`` is not read. It decides whether the result is a list of what the
    service wrote, not whether it may be ``None``: a ``many`` service's
    ``None`` return is presented as ``None`` too, so its ``allow_none`` answers
    as any other service's, and a re-read answers by its kind as above.

    It answers whether ``None`` *may* come back, not whether a schema exists: a
    spec with no presenter has no output schema to widen, whatever this says.

    A [`SpecSource`][django_service_specs.specs.spec_source.SpecSource] answers
    as the spec it compiles to, never by attributes of its own that share these
    names: its kinds are another library's, and none of them is this one's
    ``RETRIEVE``.
    """
    spec = kernel_spec(spec)
    if isinstance(spec, SelectorSpec):
        # One arc to coverage, so each operand is named:
        # test_a_list_selector_never_presents_nothing holds the kind, and
        # test_a_retrieve_selector_presents_nothing_only_under_allow_none the flag.
        return spec.kind is SelectorKind.RETRIEVE and spec.allow_none
    reread = spec.output_selector_spec
    if reread is not None:
        return reread.kind is SelectorKind.RETRIEVE
    return spec.allow_none
