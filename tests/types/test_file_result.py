from __future__ import annotations

import io
from collections.abc import AsyncIterator, Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from django.core.files.base import ContentFile, File

from django_service_specs.types.file_result import FileResult
from django_service_specs.types.file_too_large import FileTooLarge


class Recording(io.BytesIO):
    def __init__(self, data: bytes) -> None:
        super().__init__(data)
        self.asked: list[int] = []

    def read(self, size: int | None = -1) -> bytes:
        self.asked.append(-1 if size is None else size)
        return super().read(size)


class Trickle(Recording):
    given = 0

    def read(self, size: int | None = -1) -> bytes:
        data = super().read(min(3, -1 if size is None else size))
        self.given += len(data)
        return data


class Unsized:
    def read(self, size: int = -1) -> bytes:
        return b""


def chunks(*parts: Any) -> Iterator[Any]:
    yield from parts


async def streamed() -> AsyncIterator[bytes]:
    yield b"a"


class TestContent:
    def test_bytes_are_kept_and_measured(self) -> None:
        result = FileResult(b"abc", filename="a.txt")

        assert (result.content, result.size, result.content_type) == (b"abc", 3, None)

    def test_a_django_file_is_measured(self) -> None:
        assert FileResult(ContentFile(b"abcd"), filename="a.txt").size == 4

    def test_a_given_size_is_kept(self) -> None:
        assert FileResult(ContentFile(b"abcd"), filename="a.txt", size=9).size == 9

    def test_a_size_that_is_not_an_int_is_none(self) -> None:
        content = SimpleNamespace(read=lambda size=-1: b"", size=lambda: 3)

        assert FileResult(content, filename="a.txt").size is None

    @pytest.mark.parametrize(
        "content",
        [
            pytest.param(io.BytesIO(b"ab"), id="a-file-object-without-a-size"),
            pytest.param(File(Unsized()), id="a-django-file-that-cannot-tell"),
            pytest.param(chunks(b"ab"), id="a-generator"),
        ],
    )
    def test_a_size_that_needs_a_read_is_none(self, content: Any) -> None:
        assert FileResult(content, filename="a.txt").size is None

    @pytest.mark.parametrize(
        ("content", "named"),
        [
            pytest.param("text", "str", id="str"),
            pytest.param(bytearray(b"ab"), "bytearray", id="bytearray"),
            pytest.param(memoryview(b"ab"), "memoryview", id="memoryview"),
            pytest.param(3, "int", id="not-iterable"),
        ],
    )
    def test_content_that_is_not_a_file_is_refused(self, content: Any, named: str) -> None:
        with pytest.raises(TypeError, match=f"is a {named}"):
            FileResult(content, filename="a.txt")

    def test_an_async_iterable_is_refused(self) -> None:
        stream = streamed()

        with pytest.raises(TypeError, match="async iterable"):
            FileResult(stream, filename="a.txt")


class TestFilename:
    @pytest.mark.parametrize("name", ["", ".", ".."])
    def test_a_name_that_names_no_file_is_refused(self, name: str) -> None:
        with pytest.raises(ValueError, match="is not a file name"):
            FileResult(b"", filename=name)

    def test_a_name_that_is_not_text_is_refused(self) -> None:
        with pytest.raises(ValueError, match="is not a file name"):
            FileResult(b"", filename=b"a.txt")

    @pytest.mark.parametrize(
        "char",
        [
            pytest.param("/", id="slash"),
            pytest.param("\\", id="backslash"),
            pytest.param("\x00", id="nul"),
            pytest.param("\n", id="newline"),
            pytest.param("\r", id="carriage-return"),
            pytest.param("\t", id="tab"),
            pytest.param("\x1b", id="escape"),
            pytest.param("\x7f", id="delete"),
            pytest.param("\x85", id="next-line"),
        ],
    )
    def test_each_unsafe_character_is_refused_and_named(self, char: str) -> None:
        with pytest.raises(ValueError, match=f"holds {repr(char).replace(chr(92), chr(92) * 2)}"):
            FileResult(b"", filename=f"report{char}x.csv")

    @pytest.mark.parametrize("name", ["résumé 2026.pdf", "a..b.txt", ".env", "naïve – draft.csv"])
    def test_a_safe_name_is_kept(self, name: str) -> None:
        assert FileResult(b"", filename=name).filename == name


class TestRead:
    def test_bytes_are_read_whole(self) -> None:
        assert FileResult(b"abc", filename="a.txt").read() == b"abc"

    def test_a_file_object_is_read_and_closed(self) -> None:
        content = io.BytesIO(b"x" * 70_000)

        assert FileResult(content, filename="a.txt").read() == b"x" * 70_000
        assert content.closed

    def test_an_iterable_is_joined(self) -> None:
        assert FileResult([b"a", b"b"], filename="a.txt").read() == b"ab"

    def test_content_exactly_at_the_ceiling_is_read(self) -> None:
        content = io.BytesIO(b"abc")

        assert FileResult(content, filename="a.txt").read(max_bytes=3) == b"abc"
        assert content.closed

    def test_a_file_object_past_the_ceiling_is_closed_and_refused(self) -> None:
        content = Recording(b"abcdef")

        with pytest.raises(FileTooLarge, match="4-byte ceiling") as raised:
            FileResult(content, filename="a.txt").read(max_bytes=4)

        assert (raised.value.max_bytes, content.closed, content.asked) == (4, True, [5])

    def test_short_reads_never_take_more_than_the_ceiling_plus_one_byte(self) -> None:
        content = Trickle(b"x" * 1000)

        with pytest.raises(FileTooLarge):
            FileResult(content, filename="a.txt").read(max_bytes=10)

        assert (content.given, content.asked) == (11, [3, 3, 3, 2])

    def test_a_declared_size_past_the_ceiling_is_refused_unread(self) -> None:
        content = Recording(b"abcdef")

        with pytest.raises(FileTooLarge):
            FileResult(content, filename="a.txt", size=6).read(max_bytes=4)

        assert (content.asked, content.closed) == ([], True)

    def test_a_declared_size_within_the_ceiling_is_read(self) -> None:
        assert FileResult(b"abc", filename="a.txt").read(max_bytes=10) == b"abc"

    def test_a_declared_size_is_not_trusted_under_the_ceiling(self) -> None:
        with pytest.raises(FileTooLarge):
            FileResult(io.BytesIO(b"abcdef"), filename="a.txt", size=1).read(max_bytes=4)

    def test_a_generator_past_the_ceiling_is_closed(self) -> None:
        stream = chunks(b"abc", b"def", b"ghi")

        with pytest.raises(FileTooLarge):
            FileResult(stream, filename="a.txt").read(max_bytes=4)

        assert next(stream, None) is None

    def test_a_chunk_that_is_not_bytes_is_refused(self) -> None:
        content = io.StringIO("text")

        with pytest.raises(TypeError, match="gave a str"):
            FileResult(content, filename="a.txt").read()

        assert content.closed

    def test_an_iterable_chunk_that_is_not_bytes_is_refused(self) -> None:
        with pytest.raises(TypeError, match="gave a int"):
            FileResult([b"a", 1], filename="a.txt").read()


class TestIterableCeiling:
    def test_an_iterable_stops_at_the_first_chunk_past_the_ceiling(self) -> None:
        taken: list[int] = []

        def stream() -> Iterator[bytes]:
            for part in (b"x" * 5, b"y" * 100, b"z" * 100):
                taken.append(len(part))
                yield part

        with pytest.raises(FileTooLarge):
            FileResult(stream(), filename="a.txt").read(max_bytes=10)

        assert taken == [5, 100]


class TestClose:
    def test_bytes_and_a_list_have_nothing_to_close(self) -> None:
        FileResult(b"a", filename="a.txt").close()
        FileResult([b"a"], filename="a.txt").close()

    def test_a_file_object_is_closed(self) -> None:
        content = File(io.BytesIO(b"a"))

        FileResult(content, filename="a.txt").close()

        assert content.closed

    def test_a_generator_is_closed(self) -> None:
        stream = chunks(b"a", b"b")

        FileResult(stream, filename="a.txt").close()

        assert next(stream, None) is None
