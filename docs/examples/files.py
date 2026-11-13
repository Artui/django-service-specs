from __future__ import annotations

import csv
import io
from typing import Any

from django_service_specs import (
    FilePresenter,
    FileResult,
    FileTooLarge,
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    dispatch,
    file_output,
    present,
)
from docs.examples.declaring import IsSignedIn
from tests.adapter_app.models import Book


# --8<-- [start:service]
def export_books(*, user: Any) -> FileResult:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["title", "price"])
    for book in Book.objects.order_by("title"):
        writer.writerow([book.title, book.price])
    return FileResult(out.getvalue().encode(), filename="books.csv")


export = ServiceSpec(
    service=export_books,
    permissions=[IsSignedIn()],
    presenter=FilePresenter("text/csv"),
)
# --8<-- [end:service]


# --8<-- [start:selector]
def render_label(book: Book) -> bytes:
    return f"{book.title}\n{book.price}\n".encode()


label = SelectorSpec(
    kind=SelectorKind.RETRIEVE,
    selector=lambda *, pk: Book.objects.filter(pk=pk),
    reads=Parameters.of(Parameter("pk", "integer", required=True)),
    permissions=[IsSignedIn()],
    presenter=FilePresenter(
        "text/plain",
        filename=lambda book: f"label-{book.pk}.txt",
        render=render_label,
    ),
)
# --8<-- [end:selector]


# --8<-- [start:transport]
def serve(spec: ServiceSpec | SelectorSpec, principal: Any, **arguments: Any) -> dict[str, Any]:
    declared = file_output(spec)
    if declared is None:
        raise ValueError("Not a file spec; serve it as JSON.")
    result = dispatch(spec, principal=principal, arguments=arguments)
    file: FileResult = present(spec, result)
    try:
        body = file.read(max_bytes=1_000_000)
    except FileTooLarge as refused:
        return {"error": f"over {refused.max_bytes} bytes"}
    return {"name": file.filename, "type": file.content_type, "body": body}


# --8<-- [end:transport]
