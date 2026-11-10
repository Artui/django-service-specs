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
    """``spec`` as a spec of this package's: itself, or what it compiles to."""
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
    if compiled is spec:
        return compiled
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
    return _COMPILED.setdefault(key, (source, compiled))[1]
