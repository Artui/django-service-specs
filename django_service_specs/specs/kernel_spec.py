"""``kernel_spec`` - a spec, or what a declaration of another library's compiles to."""

from __future__ import annotations

import weakref
from typing import Any

# Imported for the annotations. The body never asks a spec its class: a spec is
# told apart by compiling to itself, so a declaration of another library's is
# read by the same rule as a spec of this package's.
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource

# id(source) -> (a weak reference to the source, its compiled spec). Keyed by
# identity rather than held in a ``WeakKeyDictionary``, which reads ``__hash__``
# and ``__eq__``: a frozen dataclass compares by its fields, so two equal
# declarations would share one compiled spec, and one holding a list has no
# hash at all. The weak reference's callback removes the entry when the source
# dies, before its id can name another object.
_COMPILED: dict[int, tuple[weakref.ref[Any], ServiceSpec | SelectorSpec]] = {}


def kernel_spec(spec: ServiceSpec | SelectorSpec | SpecSource) -> ServiceSpec | SelectorSpec:
    """``spec`` as a spec of this package's: itself, or what it compiles to.

    Everything it takes is a
    [`SpecSource`][django_service_specs.specs.spec_source.SpecSource], and
    ``as_kernel_spec()`` is what it asks. A ``ServiceSpec`` or ``SelectorSpec``
    compiles to itself, and is returned as it is. Anything else compiles to a
    spec - an object that in turn compiles to itself - and the compiled spec
    is cached per object, by identity: the same object
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
            does not compile to itself, which no ``ServiceSpec`` or
            ``SelectorSpec`` fails to do.
    """
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
    compiled: ServiceSpec | SelectorSpec = compile_spec()
    # A spec compiles to itself, and is returned as it is, never cached
    # (test_a_kernel_spec_is_its_own_kernel_spec_and_is_not_cached, for both
    # kinds).
    if compiled is spec:
        return compiled
    # What a source compiles to must be a spec, told by the same mark: it
    # compiles to itself. One arc to coverage, so each operand is named by a
    # case of test_a_compile_answering_something_else_is_refused_and_nothing_is_cached:
    # ``no-compile`` holds the first, ``not-a-fixed-point`` the second.
    recompile = getattr(compiled, "as_kernel_spec", None)
    if not callable(recompile) or recompile() is not compiled:
        raise TypeError(
            f"{type(spec).__name__}.as_kernel_spec() must return a ServiceSpec or SelectorSpec; "
            f"got {type(compiled).__name__}."
        )
    try:
        source = weakref.ref(spec, lambda _dead: _COMPILED.pop(key, None))
    except TypeError:
        raise TypeError(
            f"{type(spec).__name__} cannot be weakly referenced, so its compiled spec cannot be "
            "kept once per object. Add '__weakref__' to its __slots__."
        ) from None
    # The first compiled spec published wins, so two calls racing the first
    # compile answer the same object
    # (test_a_compile_that_reads_itself_answers_the_spec_published_first).
    return _COMPILED.setdefault(key, (source, compiled))[1]
