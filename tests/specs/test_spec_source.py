from __future__ import annotations

import gc
from typing import Any

import pytest

from django_service_specs.specs import spec_source
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.spec_source import kernel_spec
from tests.dispatch.utils import OPEN, notes_of
from tests.specs.utils import Foreign

LISTING = SelectorSpec(kind=SelectorKind.LIST, selector=notes_of, permissions=OPEN)


def test_a_kernel_spec_is_its_own_kernel_spec_and_is_not_cached() -> None:
    before = dict(spec_source._COMPILED)
    assert kernel_spec(LISTING) is LISTING
    assert before == spec_source._COMPILED


def test_a_source_is_compiled_once_and_answers_the_same_spec_every_time() -> None:
    source = Foreign(LISTING)
    assert kernel_spec(source) is LISTING
    assert kernel_spec(source) is LISTING
    assert source.compiles == [1]


def test_the_stand_in_has_no_hash_and_compares_by_its_fields() -> None:
    # The shape the cache must survive: a WeakKeyDictionary would raise on the
    # first, and would share one compile between the two below.
    with pytest.raises(TypeError, match="unhashable"):
        hash(Foreign(LISTING))
    assert Foreign(LISTING) == Foreign(LISTING)


def test_two_equal_sources_are_two_declarations_each_compiled_on_its_own() -> None:
    first = SelectorSpec(kind=SelectorKind.LIST, selector=notes_of, permissions=OPEN)
    second = SelectorSpec(kind=SelectorKind.LIST, selector=notes_of, permissions=OPEN)
    one, other = Foreign(first), Foreign(first)
    assert one == other
    kernel_spec(one)
    kernel_spec(other)
    assert (one.compiles, other.compiles) == ([1], [1])
    # Each keeps its own answer, whatever it compiles to.
    assert kernel_spec(Foreign(second)) is second


def test_the_entry_goes_when_the_source_does() -> None:
    source = Foreign(LISTING)
    key = id(source)
    kernel_spec(source)
    assert key in spec_source._COMPILED
    del source
    gc.collect()
    assert key not in spec_source._COMPILED


class _ReadsItself:
    """Compiles by asking ``kernel_spec`` for itself once, as a racing second call would."""

    def __init__(self) -> None:
        self.answers = [
            SelectorSpec(kind=SelectorKind.LIST, selector=notes_of, permissions=OPEN),
            SelectorSpec(kind=SelectorKind.LIST, selector=notes_of, permissions=OPEN),
        ]
        self.inner: Any = None
        self.reading = False

    def as_kernel_spec(self) -> SelectorSpec:
        answer = self.answers.pop(0)
        if not self.reading:
            self.reading = True
            self.inner = kernel_spec(self)
        return answer


def test_a_compile_that_reads_itself_answers_the_spec_published_first() -> None:
    source = _ReadsItself()
    first, second = list(source.answers)
    # The inner call compiles to the second answer and publishes it; the
    # outer call, finishing later, answers what was published rather than its own.
    assert kernel_spec(source) is second
    assert source.inner is second
    assert kernel_spec(source) is second
    assert first is not second


class _Slotted:
    __slots__ = ()

    def as_kernel_spec(self) -> SelectorSpec:
        return LISTING


def test_a_source_that_cannot_be_weakly_referenced_is_refused_naming_the_fix() -> None:
    with pytest.raises(TypeError, match=r"_Slotted cannot be weakly referenced.*__weakref__"):
        kernel_spec(_Slotted())


@pytest.mark.parametrize("value", [object(), "a spec", None])
def test_an_object_with_no_compile_is_refused(value: Any) -> None:
    with pytest.raises(TypeError, match=r"SelectorSpec, or an object with as_kernel_spec\(\); got"):
        kernel_spec(value)


def test_a_compile_attribute_that_is_not_callable_is_refused() -> None:
    class Attribute:
        as_kernel_spec = LISTING

    with pytest.raises(
        TypeError, match=r"SelectorSpec, or an object with as_kernel_spec\(\); got Attribute"
    ):
        kernel_spec(Attribute())


def test_a_compile_answering_something_else_is_refused_and_nothing_is_cached() -> None:
    class Wrong:
        def as_kernel_spec(self) -> Any:
            return Foreign(LISTING)

    source = Wrong()
    with pytest.raises(TypeError, match=r"Wrong.as_kernel_spec\(\) must return .*; got Foreign"):
        kernel_spec(source)
    assert id(source) not in spec_source._COMPILED
