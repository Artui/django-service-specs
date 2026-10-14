"""``SpecSource`` - a declaration of another library's that compiles to a spec of this one.

The entry points that dispatch, bind, authorize, present and describe a spec
take one of these too, as the registry page lists them, and read it through
[`kernel_spec`][django_service_specs.specs.kernel_spec.kernel_spec]:
the one place it is compiled, and cached, so every entry point reading one
object reads the same compiled spec.
"""

from __future__ import annotations

from typing import Protocol

from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec


class SpecSource(Protocol):
    """An object that compiles itself to a ``ServiceSpec`` or ``SelectorSpec``.

    The seam for a library that declares operations in its own vocabulary -
    djangorestframework-services' spec, compiled from a serializer and
    permission classes - so its declaration is handed to ``dispatch``, the
    registry, the schemas and the rest as it is, with no wrapper of this
    package's around it.

    ``ServiceSpec`` and ``SelectorSpec`` satisfy it too: each compiles to
    itself, which is how
    [`kernel_spec`][django_service_specs.specs.kernel_spec.kernel_spec] tells a
    spec from a declaration by that mark rather than by its class.

    ``as_kernel_spec()`` is called the first time any entry point reads the
    object, and the compiled spec it answers is the one every later call
    reads: the object is read as a declaration, and a change to it after that
    first read is not seen. Two first reads that overlap - concurrent, or a
    compile that reads its own object - may each compile, and both answer the
    spec published first. One compiled spec per object is also what lets a
    [`Grant`][django_service_specs.dispatch.grant.Grant], bound to a spec
    by identity, carry from ``resolve_target`` to ``dispatch`` when both are
    handed the same object.
    """

    def as_kernel_spec(self) -> ServiceSpec | SelectorSpec:
        """This declaration as a spec of this package's."""
        ...
