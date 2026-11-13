from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import IO, Any

from django_service_specs.types.file_too_large import FileTooLarge

_CHUNK = 64 * 1024


@dataclass(frozen=True)
class FileResult:
    """A file an operation produced: its content, its name, its type and its size.

    ``content`` is ``bytes``, a binary file object (a Django ``File``, an open
    ``IO[bytes]``) or an iterable of ``bytes``. A ``str`` is refused, since it
    is text rather than a file, and so is an async iterable, which no
    transport streams yet.

    ``filename`` is shown to a caller and quoted into a header, never joined to
    a path, so it is refused when it is empty, ``.`` or ``..``, or holds a
    path separator (``/`` or ``\\``), a NUL or any other control character.

    ``content_type`` is the media type, or ``None`` for a
    [`FilePresenter`][django_service_specs.output.file_presenter.FilePresenter]
    to fill. ``size`` is the length in bytes, read from ``bytes`` or from any
    object with an ``int`` ``size`` (a Django ``File``) when it is not given,
    and ``None`` when it cannot be known without reading.

    The content is read once: a file object or a generator is consumed by
    ``read()``, and both ``read()`` and ``close()`` close it.
    """

    content: bytes | IO[bytes] | Iterable[bytes]
    filename: str
    content_type: str | None = None
    size: int | None = field(default=None)

    def __post_init__(self) -> None:
        _check_content(self.content)
        _check_filename(self.filename)
        if self.size is None:
            object.__setattr__(self, "size", _known_size(self.content))

    def read(self, max_bytes: int | None = None) -> bytes:
        """The whole content, closing it; past ``max_bytes``, closes it and raises ``FileTooLarge``.

        Raises:
            FileTooLarge: The content is longer than ``max_bytes``, by its
                declared ``size`` or once that many bytes and one more have
                been read. A file object is never asked for more than the
                ceiling plus one byte in all; an iterable's chunks are taken
                whole, and reading stops at the first chunk past the ceiling.
            TypeError: An iterable yielded something other than ``bytes``.
        """
        try:
            if max_bytes is not None and self.size is not None and self.size > max_bytes:
                raise FileTooLarge(max_bytes)
            data = bytearray()
            for chunk in _chunks(self.content, max_bytes):
                data += chunk
                if max_bytes is not None and len(data) > max_bytes:
                    raise FileTooLarge(max_bytes)
            return bytes(data)
        finally:
            self.close()

    def close(self) -> None:
        """Close the content when it can be closed: a file object, or a generator."""
        if isinstance(self.content, bytes):
            return
        close = getattr(self.content, "close", None)
        if callable(close):
            close()


def _check_content(content: Any) -> None:
    if isinstance(content, bytes):
        return
    if isinstance(content, str | bytearray | memoryview):
        raise TypeError(
            f"FileResult.content is a {type(content).__name__}. Pass bytes, a binary file "
            "object, or an iterable of bytes."
        )
    if hasattr(content, "__aiter__"):
        raise TypeError(
            "FileResult.content is an async iterable, which no transport streams. Pass "
            "bytes, a binary file object, or an iterable of bytes."
        )
    if not (hasattr(content, "read") or isinstance(content, Iterable)):
        raise TypeError(
            f"FileResult.content is a {type(content).__name__}. Pass bytes, a binary file "
            "object, or an iterable of bytes."
        )


def _check_filename(filename: Any) -> None:
    if not isinstance(filename, str) or filename in ("", ".", ".."):
        raise ValueError(
            f"FileResult.filename {filename!r} is not a file name. Pass a non-empty name "
            "other than '.' or '..'."
        )
    for char in filename:
        if char in "/\\" or unicodedata.category(char) == "Cc":
            raise ValueError(
                f"FileResult.filename {filename!r} holds {char!r}. A name is shown and "
                "quoted, never joined to a path: leave out path separators and control "
                "characters."
            )


def _known_size(content: Any) -> int | None:
    if isinstance(content, bytes):
        return len(content)
    size = getattr(content, "size", None)
    return size if isinstance(size, int) else None


def _chunks(content: Any, max_bytes: int | None) -> Iterator[bytes]:
    if isinstance(content, bytes):
        yield content
        return
    if hasattr(content, "read"):
        reader: Any = content
        taken = 0
        while chunk := reader.read(
            _CHUNK if max_bytes is None else min(_CHUNK, max_bytes + 1 - taken)
        ):
            taken += len(chunk)
            yield _bytes(chunk)
        return
    for chunk in content:
        yield _bytes(chunk)


def _bytes(chunk: Any) -> bytes:
    if not isinstance(chunk, bytes):
        raise TypeError(
            f"FileResult.content gave a {type(chunk).__name__} where bytes are expected."
        )
    return chunk
