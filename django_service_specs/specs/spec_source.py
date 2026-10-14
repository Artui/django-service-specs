"""``SpecSource`` - a declaration of another library's that compiles to a spec of this one.

Every entry point that takes a spec takes one of these too, and reads it
through ``kernel_spec``: the one place it is compiled, and cached, so a
declaration is compiled once per object however many entry points read it.
"""

from __future__ import annotations

import weakref
from typing import Any, Protocol

from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec

# id(source) -> (a weak reference to the source, its compiled spec). Keyed by
# identity rather than held in a ``WeakKeyDictionary``, which reads ``__hash__``
# and ``__eq__``: a frozen dataclass compares by its fields, so two equal
# declarations would share one compiled spec, and one holding a list has no
# hash at all. The weak reference's callback removes the entry when the source
# dies, before its id can name another object.
_COMPILED: dict[int, tuple[weakref.ref[Any], ServiceSpec | SelectorSpec]] = {}


class SpecSource(Protocol):
    """An object that compiles itself to a ``ServiceSpec`` or ``SelectorSpec``.

    The seam for a library that declares operations in its own vocabulary -
    djangorestframework-services' spec, compiled from a serializer and
    permission classes - so its declaration is handed to ``dispatch``, the
    registry, the schemas and the rest as it is, with no wrapper of this
    package's around it.

    ``as_kernel_spec()`` is called once per object, the first time any entry
    point reads it, and its answer is used for every later call: the object
    is read as a declaration, and a change to it after that first read is not
    seen. One compiled spec per object is also what lets a
    [`Grant`][django_service_specs.authorization.grant.Grant], bound to a spec
    by identity, carry from ``resolve_target`` to ``dispatch`` when both are
    handed the same object.
    """

    def as_kernel_spec(self) -> ServiceSpec | SelectorSpec:
        """This declaration as a spec of this package's."""
        ...


def kernel_spec(spec: ServiceSpec | SelectorSpec | SpecSource) -> ServiceSpec | SelectorSpec:
    """``spec`` as a spec of this package's: itself, or what it compiles to.

    A ``ServiceSpec`` or ``SelectorSpec`` is returned as it is. Anything else
    must be a [`SpecSource`][django_service_specs.specs.spec_source.SpecSource],
    and the compiled spec is cached per object, by identity: the same object
    answers the same compiled spec on every call, and two objects that compare
    equal are two declarations, each compiled on its own. The cache holds the
    object weakly and its compiled spec for as long as the object lives, so a
    compiled spec that refers back to its object keeps both for the life of
    the process, as a declaration at module level is kept anyway.

    Raises:
        TypeError: ``spec`` is neither a spec nor an object with
            ``as_kernel_spec()``; it cannot be weakly referenced, so its
            compiled spec could not be kept per object without keeping the
            object forever; or ``as_kernel_spec()`` answered something that
            is not a ``ServiceSpec`` or ``SelectorSpec``.
    """
    if isinstance(spec, ServiceSpec | SelectorSpec):
        return spec
    compile_spec = getattr(spec, "as_kernel_spec", None)
    if not callable(compile_spec):
        raise TypeError(
            "expected a ServiceSpec or SelectorSpec, or an object with as_kernel_spec(); got "
            f"{type(spec).__name__}."
        )
    key = id(spec)
    cached = _COMPILED.get(key)
    if cached is not None:
        return cached[1]
    try:
        source = weakref.ref(spec, lambda _dead: _COMPILED.pop(key, None))
    except TypeError:
        raise TypeError(
            f"{type(spec).__name__} cannot be weakly referenced, so its compiled spec cannot be "
            "kept once per object. Add '__weakref__' to its __slots__."
        ) from None
    compiled = compile_spec()
    if not isinstance(compiled, ServiceSpec | SelectorSpec):
        raise TypeError(
            f"{type(spec).__name__}.as_kernel_spec() must return a ServiceSpec or SelectorSpec; "
            f"got {type(compiled).__name__}."
        )
    # The first compiled spec published wins, so two calls racing the first
    # compile answer the same object
    # (test_a_compile_that_reads_itself_answers_the_spec_published_first).
    return _COMPILED.setdefault(key, (source, compiled))[1]
