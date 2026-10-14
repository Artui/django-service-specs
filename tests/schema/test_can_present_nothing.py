"""``can_present_nothing``: whether a spec's dispatch may present ``None``, asked in one place."""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any

import pytest

from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.dispatch.present import present
from django_service_specs.output.output import Output
from django_service_specs.output.output_field import OutputField
from django_service_specs.output.presenter import Presenter
from django_service_specs.schema.can_present_nothing import can_present_nothing
from django_service_specs.schema.spec_output_schema import spec_output_schema
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import kernel_spec
from tests.dispatch.utils import OPEN, PK, make_user, note_by_pk
from tests.dispatch_app.models import Note
from tests.specs.utils import Foreign, Titled

LIST, RETRIEVE = SelectorKind.LIST, SelectorKind.RETRIEVE


class NoteTitle(Presenter):
    def output(self) -> Output:
        return Output((OutputField("title", "string"),))

    def present(self, value: Any) -> Any:
        return {"title": value.title}


def write(**_: Any) -> None:
    return None


def nothing(**_: Any) -> Any:
    return Note.objects.none()


def _selector(kind: SelectorKind, **kwargs: Any) -> SelectorSpec:
    if kind is RETRIEVE:
        kwargs.setdefault("reads", PK)
    return SelectorSpec(
        kind=kind,
        selector=note_by_pk if kind is RETRIEVE else nothing,
        permissions=OPEN,
        presenter=NoteTitle(),
        **kwargs,
    )


def _re_read(kind: SelectorKind) -> SelectorSpec:
    return SelectorSpec(kind=kind, selector=nothing, presenter=NoteTitle())


def _service(reread: SelectorSpec | None = None, **kwargs: Any) -> ServiceSpec:
    if kwargs.get("many"):
        kwargs.setdefault("validator", Titled())
    presenter = None if reread is not None else NoteTitle()
    return ServiceSpec(
        service=write,
        permissions=OPEN,
        presenter=presenter,
        output_selector_spec=reread,
        **kwargs,
    )


_TABLE = [
    pytest.param(_selector(LIST), False, id="selector-list"),
    pytest.param(_selector(LIST, allow_none=True), False, id="selector-list-allow-none"),
    pytest.param(_selector(RETRIEVE), False, id="selector-retrieve"),
    pytest.param(_selector(RETRIEVE, allow_none=True), True, id="selector-retrieve-allow-none"),
    pytest.param(_service(), False, id="service"),
    pytest.param(_service(allow_none=True), True, id="service-allow-none"),
    pytest.param(_service(many=True), False, id="service-many"),
    pytest.param(_service(many=True, allow_none=True), True, id="service-many-allow-none"),
    pytest.param(_service(_re_read(RETRIEVE)), True, id="service-retrieve-re-read"),
    pytest.param(
        _service(_re_read(RETRIEVE), allow_none=True),
        True,
        id="service-retrieve-re-read-allow-none",
    ),
    pytest.param(_service(_re_read(LIST)), False, id="service-list-re-read"),
    pytest.param(
        _service(_re_read(LIST), allow_none=True), False, id="service-list-re-read-allow-none"
    ),
    pytest.param(
        _service(_re_read(RETRIEVE), many=True), True, id="service-many-with-a-retrieve-re-read"
    ),
    pytest.param(_service(_re_read(LIST), many=True), False, id="service-many-with-a-list-re-read"),
]


@pytest.mark.parametrize(("spec", "expected"), _TABLE)
def test_the_truth_table(spec: Any, expected: bool) -> None:
    assert can_present_nothing(spec) is expected


@pytest.mark.parametrize(("spec", "expected"), _TABLE)
def test_the_output_schema_admits_null_exactly_where_it_answers_true(
    spec: Any, expected: bool
) -> None:
    """The extraction changed nothing: ``spec_output_schema`` asks this, and only this."""
    schema = spec_output_schema(spec)
    assert schema is not None
    admits_null = isinstance(schema["type"], list) and "null" in schema["type"]

    assert admits_null is expected


def test_a_list_selector_never_presents_nothing() -> None:
    # Holds the kind operand: without it a LIST under allow_none would answer True.
    assert can_present_nothing(_selector(LIST, allow_none=True)) is False


def test_a_retrieve_selector_presents_nothing_only_under_allow_none() -> None:
    # Holds the flag operand: without it every RETRIEVE would answer True.
    assert can_present_nothing(_selector(RETRIEVE)) is False
    assert can_present_nothing(_selector(RETRIEVE, allow_none=True)) is True


def test_many_is_not_read() -> None:
    """``many`` shapes the result as a list; ``allow_none`` alone decides whether it may be ``None``."""
    for allow_none in (False, True):
        assert can_present_nothing(_service(many=True, allow_none=allow_none)) is allow_none
        assert can_present_nothing(_service(allow_none=allow_none)) is allow_none


def _call(spec: Any) -> dict[str, Any]:
    if isinstance(spec, SelectorSpec):
        return {"pk": 0}
    if spec.many:
        return {"items": [{"title": "One"}]}
    return {}


@pytest.mark.django_db
@pytest.mark.parametrize(
    "spec", [pytest.param(row.values[0], id=row.id) for row in _TABLE if row.values[1]]
)
def test_every_true_row_really_presents_none(spec: Any) -> None:
    """A ``True`` is an observation of dispatch, not a guess about it."""
    result = dispatch(spec, principal=make_user("ada"), arguments=_call(spec))

    assert present(spec, result) is None


class _ForeignKind(enum.Enum):
    """A selector kind of another library's own, as djangorestframework-services declares."""

    RETRIEVE = "retrieve"
    LIST = "list"


@dataclass(frozen=True)
class _ForeignReRead:
    kind: _ForeignKind


@dataclass(frozen=True)
class _ForeignService(Foreign):
    """A foreign service spec carrying the attributes this function reads, under its own kinds.

    Shaped as djangorestframework-services' spec is: an ``output_selector_spec``
    whose ``kind`` is that library's enum and an ``allow_none`` of its own, so
    reading it uncompiled answers without raising, and answers wrong.
    """

    output_selector_spec: _ForeignReRead | None = None
    allow_none: bool = False


def test_a_source_answers_as_the_spec_it_compiles_to() -> None:
    # Uncompiled, the foreign RETRIEVE is not the kernel's RETRIEVE, so the
    # re-read reads as a LIST and the answer is a silent False.
    source = _ForeignService(
        _service(_re_read(RETRIEVE)), output_selector_spec=_ForeignReRead(_ForeignKind.RETRIEVE)
    )

    assert can_present_nothing(source) is True
    assert can_present_nothing(source) is can_present_nothing(kernel_spec(source))


def test_a_selector_source_answers_as_the_spec_it_compiles_to() -> None:
    source = Foreign(_selector(RETRIEVE, allow_none=True))

    assert can_present_nothing(source) is True
