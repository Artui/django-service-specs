# JSON Schema

A transport that hands an operation to a client describes it first: an MCP
server lists each tool with an input and an output schema, an agent toolset
gives the model the same, a form builder picks its widgets from one. The
kernel emits that description from the spec's own declarations -
[`Parameters`][django_service_specs.parameters.parameters.Parameters] for what
goes in, [`Output`][django_service_specs.output.output.Output] for what comes
out - so no adapter describes itself.

That is the point of emitting it here. Every adapter already reads its
library's declaration into Parameters and Output, and the schema is read from
those alone, so there is **one dialect whichever library declared the spec**.
A pydantic model's own `model_json_schema()` is not used: it speaks a
different dialect - references, titles on every field, a decimal as an
`anyOf` - and a transport would hand its clients whichever one the project
happened to install.

## The functions

- [`spec_input_schema(spec, *, unknown_arguments=REJECT)`][django_service_specs.schema.spec_input_schema.spec_input_schema]
  describes everything `spec.parameters()` declares: the arguments dispatch
  checks.
- [`spec_output_schema(spec, *, paginate=False, projection=None, handle_description=None)`][django_service_specs.schema.spec_output_schema.spec_output_schema]
  describes what [`present`][django_service_specs.dispatch.present.present]
  returns for the spec, or `None` when the spec declares no output. With
  `paginate=True` a list is described as the page envelope, and with a
  `projection` as an agent audience is served it; see
  [paging and projection](paging-and-projection.md).
- [`parameters_schema(parameters, *, unknown_arguments=REJECT)`][django_service_specs.schema.parameters_schema.parameters_schema]
  and [`output_schema(output)`][django_service_specs.schema.output_schema.output_schema]
  are the same over a bare declaration, for a transport describing something
  that is not a whole spec.

Each schema is a plain `dict`, built anew on every call, so a transport can add
its own keys - a `$schema`, an annotation of its own - without reaching the
declaration or another transport's copy.

## An example

The notes list and the author write from the earlier pages, described:

```python
--8<--
docs/examples/schema.py:schema
--8<--
```

The notes list takes a search term with help text and an ordering with two
choices and a default, and refuses any other argument:

```json
{
  "type": "object",
  "properties": {
    "search": {"type": "string", "description": "Part of the title, in any case."},
    "ordering": {"type": "string", "enum": ["title", "-title"], "default": "title"}
  },
  "additionalProperties": false
}
```

It returns a list, so its output is an array of rows. The rows' fields carry
markings - `id` is a handle, `title` the label - which this schema does not
apply; see [what is not emitted](#what-is-deliberately-not-emitted).

```json
{
  "type": "array",
  "items": {
    "type": "object",
    "properties": {"id": {"type": "integer"}, "title": {"type": "string"}},
    "required": ["id", "title"]
  }
}
```

The author write takes rows, and each row is described in full and closed as
the top is. A book's `price` is a decimal, its `status` has choices and a
default, and `published_on` and `pk` may be null:

```json
{
  "type": "object",
  "properties": {
    "name": {"type": "string"},
    "books": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "title": {"type": "string"},
          "price": {"type": "string", "format": "decimal"},
          "status": {"type": "string", "enum": ["draft", "published"], "default": "draft"},
          "published_on": {"type": ["string", "null"], "format": "date", "default": null},
          "pk": {"type": ["integer", "null"], "default": null}
        },
        "required": ["title", "price"],
        "additionalProperties": false
      }
    }
  },
  "required": ["name"],
  "additionalProperties": false
}
```

Its output selector re-reads the author once the write has committed, so the
output may be null (see [what a spec returns](#what-a-spec-returns)), and the
book's status states each choice's display as a `title`:

```json
{
  "type": ["object", "null"],
  "properties": {
    "id": {"type": "integer"},
    "name": {"type": "string"},
    "books": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "id": {"type": "integer"},
          "title": {"type": "string"},
          "price": {"type": "string", "format": "decimal"},
          "status": {
            "type": "string",
            "oneOf": [
              {"const": "draft", "title": "Draft"},
              {"const": "published", "title": "Published"}
            ]
          }
        },
        "required": ["id", "title", "price", "status"]
      }
    }
  },
  "required": ["id", "name", "books"]
}
```

## Precise: never false, and not incomplete where the declaration knows

A schema is a claim a client acts on. A model that reads "this may not be
null" never sends null; a form builder that reads an enum offers nothing else.
So the rule is that the schema never states something the kernel would
contradict, and states everything the declaration knows.

- **Nullable is stated for every node**, objects and arrays included, as a
  type list: `["string", "null"]`. Parameters carries `nullable` whichever
  library declared the field, so the schema does not depend on it. An
  array's element states its own, from `items_nullable`, on `items`: the
  array and its elements may each be null or not, independently.
- **An enum lists every accepted value.** An enum claims to be the whole set,
  so leaving a value out is a falsehood rather than an omission. A nullable
  parameter with choices therefore lists `null` among them, because the shape
  check accepts a null before it reads the choices. An array's choices
  constrain each element, so they sit on `items`, and gain `null` there by
  the element's nullability alone, never by the array's.
- **`required` lists what the shape check refuses when absent**: a required
  parameter with no default. A required parameter that declares a default is
  not refused when omitted, because the Validator supplies the default, so it
  is not listed.
- **A value JSON cannot carry is left out whole.** A default of
  `Decimal("9.99")` or `date.today`, or a choice set holding one, would break
  the encoding every transport performs on the schema, so it is not stated
  rather than restated in a form the declaration did not choose. Leaving out
  only the unencodable choices would claim the others are refused.

What stays incomplete is only what the declaration does not carry. There are
no bounds (`maxLength`, `minimum`) because Parameters has none yet; the
Validator enforces them, and adding them to Parameters would reach the schema
too.

### The decimal convention

A decimal is `{"type": "string", "format": "decimal"}`. The shape check also
accepts a JSON number for one, because every decimal validator does, and the
schema does not advertise that: a string is the form every validator reads
without a binary float's rounding, so it is the one a client is told to send.

## The closed set follows the policy

Dispatch closes the argument set under `UnknownArguments.REJECT`, the
default, and the schema says so with `"additionalProperties": false`, at
exactly the levels the shape check closes: the top, every object parameter
that declares its `fields`, and every row of an array of rows. A declared
object with no fields at all is closed too, since it refuses every key.

Under `UnknownArguments.IGNORE` an undeclared key is accepted and dropped, so
a schema saying `false` would tell the client a call that runs is invalid.
The schema leaves the keyword out at every level instead, as
`lenient_author_input` in the example does: the same description as
`author_input` with every `"additionalProperties": false` gone. Pass the
policy the transport dispatches with.

## Flat and self-contained

Every schema is inline. There is no `$defs` and no `$ref`, however deeply the
declaration nests: most MCP clients refuse a tool schema holding a reference,
and none of the family's transports resolve one.

A declaration that refers to itself - a category tree, a threaded comment -
cannot be inlined without end, so an adapter bounds it where it reads the
declaration: past the bound, a nested object is declared with no `fields`.
The schema of that node is `{"type": "object"}`. It is the one thing still
known to be true, it is what a caller can still send, and it constrains
nothing a valid call could fail. An object parameter declared without fields
is described the same way for the same reason.

## What a spec returns

[`spec_output_schema`][django_service_specs.schema.spec_output_schema.spec_output_schema]
describes what dispatch presents, which depends on the kind of spec as well as
on its presenter:

| Spec | Schema |
| --- | --- |
| No presenter, on the spec or its output selector | `None` |
| A `LIST` selector spec | `{"type": "array", "items": <item>}` |
| A `RETRIEVE` selector spec | the item |
| A `RETRIEVE` selector spec with `allow_none=True` | the item, with `"null"` in its type |
| A service spec whose output selector is a `LIST` | `{"type": "array", "items": <item>}` |
| A service spec whose output selector is a `RETRIEVE` | the item, with `"null"` in its type |
| A service spec with no output selector | the item |
| A service spec with no output selector, with `allow_none=True` | the item, with `"null"` in its type |

A `RETRIEVE` selector spec without `allow_none` answers a missing row as
not-found, which a transport reports in its own terms and never presents, so
its item is not nullable. A service spec's `RETRIEVE` output selector is
nullable whatever its `allow_none` says: once the service has run, a re-read
that finds nothing is `None` rather than not-found, because not-found would
tell the caller a committed write did not happen.

A service spec that presents what the service returned is described as the
item, and dispatch presents a `None` it returned as `None`. Whether a service
may return one is not otherwise in its declaration, so the spec says it with
`allow_none=True`, the name a selector spec already uses, and the item gains
`"null"`:

```python
--8<--
docs/examples/schema.py:allow_none
--8<--
```

Left undeclared, a `None` is not stated, and the item stays the strict object
its presenter declares: a schema that admitted `null` for every write would
describe every service as one that may return nothing. On a service spec with
an output selector, `allow_none` changes nothing: a `RETRIEVE` re-read admits
`"null"` already, and a `LIST` one presents its rows rather than the
service's return.

## What is deliberately not emitted

- **No `title` on input.** A Parameter has no label. On output, a field's
  `label` becomes its `title`, and adapters set a label only where the author
  wrote one, so a title is never the field's name restated.
- **No `additionalProperties` on output.** Output is not a set a caller can get
  wrong, and a transport may add keys of its own to what it sends.
- **No `default` or `description` on output.** A default says what happens when
  a caller omits an argument, which means nothing for a value that came back. A
  projected schema is the exception for `description`: a marking's description,
  or the transport's `handle_description` on a handle, is stated there.
- **No marking, unless a projection is passed.** Without one, a field marked as
  a handle, a label or hidden is described like any other, which is what
  `present` and every HTTP response return. With one,
  [`spec_output_schema`][django_service_specs.schema.spec_output_schema.spec_output_schema]
  describes what
  [`present_for_audience`][django_service_specs.dispatch.present_for_audience.present_for_audience]
  returns; see [paging and projection](paging-and-projection.md).
- **No `$schema` key.** A transport whose wire wants one adds it.
