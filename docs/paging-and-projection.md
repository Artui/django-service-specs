# Paging and projection

A transport that serves an operation to an agent does two things to its output
that an HTTP response does not. It serves a long list **a page at a time**, so
one call cannot pour a whole table into a model's context. And it **shapes
each row for its reader**: an identifier is passed to the next tool rather than
read out, a choice is spoken by its display rather than its stored value, and
plumbing is not shown at all.

Both are functions a transport calls between dispatch and the wire. Neither is
applied by [`dispatch`][django_service_specs.dispatch.dispatch.dispatch],
[`present`][django_service_specs.dispatch.present.present] or
[`SpecView`][django_service_specs.http.spec_view.SpecView], so a caller that
names no audience - every HTTP response - is not projected: no marking
applies to it, so it is served every field, each value as presented, and a
list as a bare array.

```python
--8<--
docs/examples/paging_and_projection.py:declare
--8<--
```

The output says who each field is for, with the
[`FieldMarking`][django_service_specs.output.field_marking.FieldMarking]s
described under [declaring an operation](declaring.md): `id` is a handle,
`title` names the record, `author_id` is plumbing, `status` is content
whose choices have displays, and `price` and `published_on` are content
rendered through a formatter.

## Built once, where the transport registers

```python
--8<--
docs/examples/paging_and_projection.py:register
--8<--
```

[`audience_projection_for_spec`][django_service_specs.output.audience_projection_for_spec.audience_projection_for_spec]
reads the spec's [`Output`][django_service_specs.output.output.Output] into an
[`AudienceProjection`][django_service_specs.output.audience_projection.AudienceProjection]:
each field's marking, the one field marked as the label, each choice field's
displays, and the same again for every nested output that has anything to
project. A second field marked as the label is refused here, naming both: a
record has one name.

[`spec_output_schema`][django_service_specs.schema.spec_output_schema.spec_output_schema]
takes that projection and describes what the projected payload will carry, and
`paginate=True` wraps the list in the page envelope. This is `output_schema`
above:

```json
{
  "type": "object",
  "properties": {
    "items": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "id": {
            "type": "integer",
            "description": "An identifier to pass to other tools. Never read it out."
          },
          "title": {"type": "string"},
          "status": {
            "type": "string",
            "oneOf": [{"const": "Draft"}, {"const": "Published"}]
          },
          "price": {"type": "string", "examples": ["EUR 9.99"]},
          "published_on": {"type": ["string", "null"], "examples": ["31 January 2026"]}
        },
        "required": ["id", "title", "status", "price", "published_on"]
      }
    },
    "page": {"type": "integer"},
    "totalPages": {"type": "integer"},
    "hasNext": {"type": "boolean"}
  },
  "required": ["items", "page", "totalPages", "hasNext"]
}
```

Each change to the item is the mirror of one the payload undergoes:

- `author_id` is gone from the properties and from `required`.
- `status` is described in its displays, because that is what the payload
  carries. The `title` that annotated each stored value is dropped, since the
  value now equals it, and a stated `"type"` is restated as the type of the
  displays, so an integer choice spoken as `"Low"` is never described as an
  integer. `"null"` is named last exactly where the stated type admitted it,
  and beside a `oneOf` entry that admits more than its constants the type is
  left as written, because narrowing it would refuse what that entry admits. Two values sharing one
  display list it once, so a row served it matches one entry of the `oneOf`
  rather than two, and an array of such choices stops claiming `uniqueItems`:
  two values selected together are served as that display twice.
- `price` and `published_on` are described as what their formatters produce,
  and nothing they said about the value before survives: the `"format"` of a
  decimal and a date is gone, since `"EUR 9.99"` is neither. `"null"` stays
  in `published_on`'s type, because a null is never formatted.
- `id` keeps its values on both sides - a handle is passed to other tools,
  which take the stored value - and carries `handle_description`, the
  transport's sentence for a handle whose marking declares no description of
  its own. It defaults to nothing: what to do with an identifier is advice
  for one kind of reader, and only the transport knows which kind is reading.

The projection applies to the item, never to the array or the envelope around
it, whose keys belong to no `Output`.

## Formatting a value

A [`ValueFormatter`][django_service_specs.types.value_formatter.ValueFormatter]
is a transform and the JSON type it produces, declared together, and a
[`FieldMarking`][django_service_specs.output.field_marking.FieldMarking]
carries it. `euros` above is the generic form: `render` turns the presented
value - the decimal's string - into the string a reader is told, `produces`
is the type the schema states, and `schema` adds what the produced value
looks like. A fragment naming `type` is refused, so a formatter cannot
advertise one type and declare another.

[`FieldMarking.timestamp`][django_service_specs.output.field_marking.FieldMarking.timestamp]
is a formatter already written: a date-time as a local string, `strftime`'s
`fmt` defaulting to day-first and 24-hour, with the example in the schema
rendered from that same format. A date-time is converted to Django's active
time zone, which is the only zone it can be rendered in: the projection is
built once, before any request, so a zone chosen per call would describe one
payload and serve another. A date, like `published_on`, is read as midnight,
which is why its format names no time.

Both sides of the projection read one formatter, so the payload and the
schema change together, and a formatter decides over the rest of the field's
declaration:

- it wins over a choice's display, being the transform an author wrote by
  hand;
- it is never applied to a `HANDLE`, which another tool takes as input, so a
  marking that declares both is honoured as the handle;
- a null passes through it unformatted.

## Serving a page

```python
--8<--
docs/examples/paging_and_projection.py:call
--8<--
```

[`paginate_output`][django_service_specs.dispatch.paginate_output.paginate_output]
slices a list result's value into one
[`OutputPage`][django_service_specs.types.output_page.OutputPage]. `page`
defaults to 1 and `limit` to
[`DEFAULT_PAGE_SIZE`][django_service_specs.dispatch.paginate_output.DEFAULT_PAGE_SIZE].
Both are clamped at both ends - `limit` to between 1 and `max_page_size`,
`page` to between 1 and the last page that exists - and the clamp is reported
rather than silent: the envelope's `page` is the page actually served, and
`totalPages` and `hasNext` are counted at the limit actually used. A queryset
is counted with one `COUNT` before it is sliced, so a page past the end is
never an unbounded `OFFSET`.

The names a caller pages by, and the ceiling, are the transport's. They are
not arguments of the spec, whose argument set is closed, so the tool takes
them off the call before dispatch sees the rest; and two mounts of one spec
may well allow different page sizes.

[`present_for_audience`][django_service_specs.dispatch.present_for_audience.present_for_audience]
is `present` followed by the projection, and the page's rows are what it
presents. [`envelope`][django_service_specs.types.output_page.OutputPage.envelope]
then wraps them. With three books, page 2 at a limit of 2 is:

```json
{
  "items": [
    {
      "id": 3,
      "title": "A Wizard of Earthsea",
      "status": "Published",
      "price": "EUR 9.99",
      "published_on": "01 November 1968"
    }
  ],
  "page": 2,
  "totalPages": 2,
  "hasNext": false
}
```

The order matters. Paging first means only the page's rows are read and
presented. Projecting before wrapping means the projection never walks the
envelope's keys.

A selector spec declaring [`affordances`](affordances.md#answers-for-each-row-of-a-list)
pages the same way. Dispatch answers them on the queryset before
`paginate_output` slices it, so each page's rows carry the `affordances` object
the whole list would have, and the projection passes that object through
whole, `reason` included. `spec_output_schema` puts it on the item inside the
envelope, with or without `paginate=True` and `projection=`.

From async code, present with
[`apresent`][django_service_specs.dispatch.apresent.apresent], which runs the
queries in the executor, and project what it returns with
[`project_payload`][django_service_specs.output.project_payload.project_payload]:
projecting reads only the presented data and the declaration, so it is safe on
the event loop.

## One spec, two mounts

```python
--8<--
docs/examples/paging_and_projection.py:override
--8<--
```

`overrides` replaces the declared marking of the fields it names, for this
mount only. Here a tool whose callers go on to look up the author keeps
`author_id`, as a handle:

```json
{
  "id": 1,
  "title": "The Dispossessed",
  "status": "Published",
  "price": "EUR 9.99",
  "published_on": "01 May 1974",
  "author_id": 1
}
```

An override that leaves two fields marked as the label is refused in the
mount's `name`.

## A caller naming no audience

```python
--8<--
docs/examples/paging_and_projection.py:unprojected
--8<--
```

`present` applies no marking, so the same spec over HTTP still serves every
field, each choice as its stored value and each formatted field as it was
presented:

```json
{
  "id": 1,
  "title": "The Dispossessed",
  "status": "published",
  "price": "9.99",
  "published_on": "1974-05-01",
  "author_id": 1
}
```

Render an agent's **answer** with the projection. A pipeline that feeds one
spec's output into the next keeps presenting with `present`, or the handles
the next step reads by will have been projected away.

## The pieces on their own

A transport with a schema or a payload that did not come from a spec uses the
two halves directly:
[`annotate_output_schema`][django_service_specs.output.annotate_output_schema.annotate_output_schema]
applies a projection to an item schema, or to an array of them, and
[`project_payload`][django_service_specs.output.project_payload.project_payload]
applies it to a presented value. Both return their input unchanged for an
empty projection, and neither modifies what it is given.
