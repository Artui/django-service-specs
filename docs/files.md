# Presenting a file

Some operations answer with a file rather than a record: an export, an invoice
PDF, a label to print. The kernel declares that once, on the spec's presenter,
and each transport reads the declaration when it registers the spec and answers
in its own terms: a download over HTTP, a blob to an MCP client, bytes to an
agent, a refusal where it has no answer for a file.

Three names carry it:

- [`FileResult`][django_service_specs.types.file_result.FileResult] is the
  file: its content, its name, its media type and, when known, its size.
- [`FilePresenter`][django_service_specs.output.file_presenter.FilePresenter]
  is the declaration, in the presenter seat every spec already has.
- [`file_output`][django_service_specs.schema.file_output.file_output] is what a
  transport asks at registration.

## A service that builds the file

```python
--8<--
docs/examples/files.py:service
--8<--
```

The service returns a `FileResult` carrying its own name, and the presenter
fills in the media type it declares. A `FileResult` that already names one
passes through unchanged.

The content is `bytes`, a binary file object (a Django `File`, an open
`IO[bytes]`) or an iterable of `bytes`, which a transport may stream. A `str`
is refused, being text rather than a file, and so is an async iterable, which no
transport streams yet. `size` is read from `bytes` or a Django `File` when it is
not given, and is what an HTTP response sends as `Content-Length`.

### A name that is safe to show

The filename is shown to a caller and quoted into a header, never joined to a
path. So a `FileResult` refuses, when it is built, a name that is empty, `.`
or `..`, or that holds `/`, `\`, a NUL or any other control character. A name
built from row data is checked like any other.

## A selector that renders a row

```python
--8<--
docs/examples/files.py:selector
--8<--
```

When the value is not a `FileResult`, `render(value)` gives the content, and the
presenter wraps it under `filename`: a string, or a callable of the value.
Without `render` the value is the content. A value with no name to give it,
neither from the presenter nor carried by a `FileResult`, is refused when it is
presented.

A service spec with an
[output selector](declaring.md) whose presenter is a `FilePresenter` presents a
file too, through `presenter_for_output()`.

## What a transport does with it

```python
--8<--
docs/examples/files.py:transport
--8<--
```

`file_output` answers the `FilePresenter` a spec presents through, or `None`
for a spec whose result is JSON. It refuses, with `ImproperlyConfigured`, a
file that would be one of many: a `LIST` selector spec, a service spec whose
output selector is a `LIST`, or one declared `many` or `returns_many`. A list
of files has no answer on any transport. It refuses a file presented with
affordances too, since those are keys on an object. A service spec's own
`affordances` only check the call, so they are allowed, and so is `allow_none`:
a `None` is answered as the transport answers nothing for any other spec.

`read(max_bytes=)` gives the whole content and closes it. Past the ceiling it
closes the content and raises
[`FileTooLarge`][django_service_specs.types.file_too_large.FileTooLarge], which
names the ceiling. A file object is never asked for more than the ceiling plus
one byte in all, however short its reads run; an iterable's chunks are taken
whole, so reading stops at the first chunk past the ceiling, and that chunk is
in memory. A transport that refuses after presenting calls `close()`.

[`present`][django_service_specs.dispatch.present.present],
[`present_for_audience`][django_service_specs.dispatch.present_for_audience.present_for_audience]
and [`project_payload`][django_service_specs.output.project_payload.project_payload]
hand a `FileResult` on untouched: it is neither an object nor a list.

## No JSON schema

A `FilePresenter`'s `output()` is `None`, so `spec.output()` is `None` and
[`spec_output_schema`][django_service_specs.schema.spec_output_schema.spec_output_schema]
describes nothing. An empty `Output()` would advertise an object that never
arrives.
