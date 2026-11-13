from __future__ import annotations

from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_service_specs.output.file_presenter import FilePresenter
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.file_result import FileResult
from tests.dispatch.utils import OPEN

CSV = "text/csv"


class Invoice:
    pk = 7


def test_a_file_result_with_no_type_takes_the_presenter_s() -> None:
    result = FileResult(b"a", filename="a.csv")

    presented = FilePresenter(CSV).present(result)

    assert (presented.content, presented.filename, presented.content_type) == (b"a", "a.csv", CSV)


def test_a_file_result_with_a_type_passes_through_untouched() -> None:
    result = FileResult(b"a", filename="a.txt", content_type="text/plain")

    assert FilePresenter(CSV).present(result) is result


def test_a_rendered_value_is_wrapped_under_a_named_file() -> None:
    presenter = FilePresenter("application/pdf", filename="out.pdf", render=lambda _: b"%PDF")

    presented = presenter.present(Invoice())

    assert (presented.content, presented.filename, presented.content_type, presented.size) == (
        b"%PDF",
        "out.pdf",
        "application/pdf",
        4,
    )


def test_a_callable_filename_reads_the_value() -> None:
    presenter = FilePresenter(
        "application/pdf",
        filename=lambda invoice: f"invoice-{invoice.pk}.pdf",
        render=lambda _: b"%PDF",
    )

    assert presenter.present(Invoice()).filename == "invoice-7.pdf"


def test_without_render_the_value_is_the_content() -> None:
    assert FilePresenter(CSV, filename="a.csv").present(b"x,y").content == b"x,y"


def test_a_render_answering_a_file_result_is_handed_on() -> None:
    presenter = FilePresenter(CSV, render=lambda value: FileResult(value, filename="r.csv"))

    presented = presenter.present(b"a")

    assert (presented.filename, presented.content_type) == ("r.csv", CSV)


def test_a_value_with_no_name_to_give_it_is_refused() -> None:
    with pytest.raises(ImproperlyConfigured, match="handed a bytes with no filename"):
        FilePresenter(CSV).present(b"a")


def test_a_rendered_name_is_checked_as_any_other() -> None:
    with pytest.raises(ValueError, match="holds '/'"):
        FilePresenter(CSV, filename=lambda _: "../a.csv").present(b"a")


def test_an_async_render_is_refused() -> None:
    async def render(_: Any) -> bytes:
        return b""

    with pytest.raises(ImproperlyConfigured, match="render is async"):
        FilePresenter(CSV, render=render)


def test_a_file_declares_no_output() -> None:
    presenter = FilePresenter(CSV)

    assert presenter.output() is None
    assert ServiceSpec(service=print, permissions=OPEN, presenter=presenter).output() is None
