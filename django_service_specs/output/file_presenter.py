from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.output.presenter import Presenter
from django_service_specs.types.file_result import FileResult
from django_service_specs.types.is_async import is_async


class FilePresenter(Presenter):
    """Declares that an operation's result is a file of ``content_type``, and presents it.

    ``present(value)`` hands a
    [`FileResult`][django_service_specs.types.file_result.FileResult] on
    as it is, with its ``content_type`` filled from this presenter's when it
    has none. Any other value goes through ``render(value)``, or is the content
    itself when there is no ``render``, and is wrapped in a ``FileResult``
    named by ``filename``: a ``str``, or a callable of the value such as
    ``lambda invoice: f"invoice-{invoice.pk}.pdf"``. A ``render`` that answers
    with a ``FileResult`` is handed on the same way.

    ``output()`` is ``None``: a file has no JSON shape, so
    [`spec_output_schema`][django_service_specs.schema.spec_output_schema.spec_output_schema]
    describes none. A transport reads the declaration through
    [`file_output`][django_service_specs.schema.file_output.file_output] when it
    registers the spec.
    """

    def __init__(
        self,
        content_type: str,
        *,
        filename: str | Callable[[Any], str] | None = None,
        render: Callable[[Any], Any] | None = None,
    ) -> None:
        if render is not None and is_async(render):
            raise ImproperlyConfigured(
                "FilePresenter.render is async. A presenter runs synchronously; render the "
                "file in a plain function."
            )
        self.content_type = content_type
        self.filename = filename
        self.render = render

    def output(self) -> None:
        """``None``: a file declares no JSON shape."""
        return None

    def present(self, value: Any) -> FileResult:
        """``value`` as a ``FileResult`` of this presenter's content type."""
        content = self.render(value) if self.render is not None else value
        if isinstance(content, FileResult):
            if content.content_type is not None:
                return content
            return replace(content, content_type=self.content_type)
        if self.filename is None:
            raise ImproperlyConfigured(
                f"FilePresenter({self.content_type!r}) was handed a "
                f"{type(content).__name__} with no filename to give it. Declare filename, "
                "or return a FileResult that carries its own."
            )
        name = self.filename if isinstance(self.filename, str) else self.filename(value)
        return FileResult(content, filename=name, content_type=self.content_type)
