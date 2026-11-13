from __future__ import annotations

from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_service_specs.output.file_presenter import FilePresenter
from django_service_specs.schema.file_output import file_output
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.selector_kind import SelectorKind
from tests.dispatch.utils import BOOKS_OPEN, EDIT, OPEN, PK, note_by_pk, notes_of
from tests.schema.utils import NoteTitle, nothing, write
from tests.specs.utils import Titled

PDF = FilePresenter("application/pdf", filename="a.pdf")


def retrieve(**kwargs: Any) -> SelectorSpec:
    kwargs.setdefault("presenter", PDF)
    return SelectorSpec(
        kind=SelectorKind.RETRIEVE, selector=note_by_pk, reads=PK, permissions=OPEN, **kwargs
    )


def re_read(kind: SelectorKind, **kwargs: Any) -> SelectorSpec:
    return SelectorSpec(kind=kind, selector=nothing, presenter=PDF, **kwargs)


def service(**kwargs: Any) -> ServiceSpec:
    return ServiceSpec(service=write, permissions=OPEN, **kwargs)


@pytest.mark.parametrize(
    "spec",
    [
        pytest.param(retrieve(presenter=None), id="a-selector-with-no-presenter"),
        pytest.param(retrieve(presenter=NoteTitle()), id="a-selector-with-a-json-presenter"),
        pytest.param(service(), id="a-service-with-no-presenter"),
        pytest.param(service(presenter=NoteTitle()), id="a-service-with-a-json-presenter"),
    ],
)
def test_a_spec_presenting_no_file_answers_none(spec: Any) -> None:
    assert file_output(spec) is None


@pytest.mark.parametrize(
    "spec",
    [
        pytest.param(retrieve(), id="a-retrieve-selector"),
        pytest.param(retrieve(allow_none=True), id="a-retrieve-selector-allowing-none"),
        pytest.param(service(presenter=PDF), id="a-service"),
        pytest.param(service(presenter=PDF, allow_none=True), id="a-service-allowing-none"),
        pytest.param(
            service(output_selector_spec=re_read(SelectorKind.RETRIEVE)),
            id="a-service-through-its-retrieve-re-read",
        ),
        # A service spec's own affordances check the call and are never presented.
        pytest.param(service(presenter=PDF, affordances=[BOOKS_OPEN]), id="a-guarded-service"),
    ],
)
def test_a_file_spec_answers_its_presenter(spec: Any) -> None:
    assert file_output(spec) is PDF


def test_a_file_under_a_list_selector_is_refused() -> None:
    spec = SelectorSpec(kind=SelectorKind.LIST, selector=notes_of, permissions=OPEN, presenter=PDF)

    with pytest.raises(ImproperlyConfigured, match="SelectorSpec .* presents a list of rows"):
        file_output(spec)


def test_a_file_under_a_list_re_read_is_refused() -> None:
    spec = service(output_selector_spec=re_read(SelectorKind.LIST))

    with pytest.raises(ImproperlyConfigured, match="ServiceSpec .* presents a list of rows"):
        file_output(spec)


def test_a_many_file_service_is_refused() -> None:
    spec = service(presenter=PDF, many=True, validator=Titled())

    with pytest.raises(ImproperlyConfigured, match="is declared many"):
        file_output(spec)


def test_a_returns_many_file_service_is_refused() -> None:
    with pytest.raises(ImproperlyConfigured, match="is declared returns_many"):
        file_output(service(presenter=PDF, returns_many=True))


def test_a_file_selector_with_affordances_is_refused() -> None:
    with pytest.raises(ImproperlyConfigured, match="presents affordances"):
        file_output(retrieve(affordances={"edit": EDIT}))


def test_a_file_re_read_with_affordances_is_refused() -> None:
    reread = re_read(SelectorKind.RETRIEVE, affordances={"edit": EDIT})

    with pytest.raises(ImproperlyConfigured, match="presents affordances"):
        file_output(service(output_selector_spec=reread))
