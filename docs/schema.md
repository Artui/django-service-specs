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
  checks. A `many` service spec's is its `reads`, its `shapes` and the one
  required list `many_argument` names, each row an object of the Validator's
  parameters. A spec's `shapes` are properties like any other, closed set
  included, though only the presenter reads what is sent for them.
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
      "maxItems": 1000,
      "items": {
        "type": "object",
        "properties": {
          "title": {"type": "string"},
          "price": {"type": "string", "format": "decimal"},
          "status": {
            "type": "string",
            "anyOf": [
              {"const": "draft", "title": "Draft"},
              {"const": "published", "title": "Published"}
            ],
            "default": "draft"
          },
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
  the element's nullability alone, never by the array's. So do an array's
  `format`, `minimum` and `maximum`, which describe each element: a CSV
  number filter's `items` are `{"type": "string", "format": "decimal"}`, and
  the array node states only its own `"minItems"` and `"maxItems"`.
- **Labelled choices are an `anyOf`** of `{"const": value, "title": label}`
  in place of the `enum`, where some label says more than its value, as the
  book's `status` above shows; labels that only repeat their values keep the
  `enum`. A choice with no label is a bare `{"const": value}`, and a `null`
  is `{"type": "null"}`, titled when it is labelled: the `null` a nullable
  parameter gains among them. Each value is listed once, so the entries are
  disjoint and `anyOf` admits exactly what `oneOf` would. It is `anyOf`
  because a model provider's schema dialect is narrower than JSON Schema: an
  OpenAI strict schema refuses `oneOf`, and so does Gemini, while Google's
  transform empties a `{"const": null}` into `{}`, which matches every
  value. A title is rendered when the schema is built, so a lazy label is in
  the language active then, and it constrains nothing. What a spec returns
  still states labelled choices as a `oneOf`.
- **A file is `{}`.** No JSON value is one, so any type stated for it would be
  false, and JSON Schema has no keyword for a multipart part. Whether it is
  required, and its `description`, are still stated.
- **An `any` is `{}` too**, since every JSON value is one; its `default` and
  `description` are stated as on any other node. Like a file's, its node
  admits `null` whether or not it is `nullable`, and the shape check is what
  refuses a `null` it does not allow.
  An output field may be `any` as well, for a value whose JSON type is open
  (a computed field, a JSON column): its node is `{}`, with its `title` if it
  has a label, rather than a string the value may not be.
- **`required` lists what the shape check refuses when absent**: a required
  parameter with no default. A required parameter that declares a default is
  not refused when omitted, because the Validator supplies the default, so it
  is not listed.
- **A partial update requires only its reads.** A `partial` spec's
  Validator parameters are listed in no `required`, at any depth, because
  dispatch refuses none of them absent; see [a partial update](#a-partial-update).
- **A value JSON cannot carry is left out whole.** A default of
  `Decimal("9.99")` or `date.today`, or a choice set holding one, would break
  the encoding every transport performs on the schema, so it is not stated
  rather than restated in a form the declaration did not choose. Leaving out
  only the unencodable choices would claim the others are refused.

What stays incomplete is only what the declaration does not carry. A
Parameter's `minimum` and `maximum` are stated as `"minimum"` and
`"maximum"` on an `integer` and a `number`; a bound only the Validator holds, a `maxLength` or a form field's
`max_value`, is not, unless the Parameter's
[`json_schema_extra`](#keywords-no-field-spells) states it. An array's `min_length` is stated as `"minItems"`, and
its `"maxItems"` is **the maximum in force**: the declared `max_length`, or
where none is declared the `SERVICE_SPECS_MAX_ARRAY_LENGTH` setting's, 1000
unless the project sets another. It is the one bound stated without being
declared, because [the shape check refuses past
it](arguments.md#how-long-a-list-may-be) and a client told nothing would send
a call that cannot run. Under a setting of `None`, an array with no
`max_length` states none. The setting is read each time a schema is built,
so building one for an array with no `max_length` reads Django's settings and
needs them configured: outside a configured Django it raises
`ImproperlyConfigured`, as the shape check does, rather than state the default
when a project configured later may set another. JSON Schema reads `minimum`
and `maximum` on a number instance alone, so a decimal string states neither:
a validating client would ignore both and a strict one may flag them as
keywords that do not apply. The shape check enforces them all the same, so a
decimal's bound is the one enforced without being stated.

### Keywords no field spells

A `Parameter` and an `OutputField` each take `json_schema_extra`: a mapping of
the JSON Schema keywords none of their fields spells, which
[`parameters_schema`][django_service_specs.schema.parameters_schema.parameters_schema]
and [`output_schema`][django_service_specs.schema.output_schema.output_schema]
add to that declaration's node last, at any depth, as `spec_input_schema` and
`spec_output_schema` do through them:

```python
--8<--
docs/examples/schema.py:extra
--8<--
```

`isbn_input` is:

```json
{
  "type": "object",
  "properties": {
    "isbn": {
      "type": "string",
      "description": "The 13-digit ISBN, digits only.",
      "pattern": "^97[89][0-9]{10}$",
      "maxLength": 13
    }
  },
  "additionalProperties": false
}
```

and `tags_output`:

```json
{
  "type": "object",
  "properties": {
    "tags": {"type": "array", "items": {"type": "string"}, "uniqueItems": true}
  },
  "required": ["tags"]
}
```

It is how an adapter whose library declares more than a Parameter carries
keeps it on every route rather than on its own; none of the adapters this
package ships sets it. Because the node already holds everything the declaration
states, a keyword a field states is refused when the declaration is built,
naming the field to declare it on, whether or not this declaration sets that
field:

| On | Refused keywords |
| --- | --- |
| `Parameter` | `type`, `format`, `default`, the choices' `enum`, `anyOf` and `const`, `minimum`, `maximum`, `minItems`, `maxItems`, `items`, `description`, `properties`, `required` and `additionalProperties` |
| `OutputField` | `type`, `format`, `items`, the choices' `enum`, `oneOf` and `const`, `title`, `properties` and `required` |

So a custom `format` is refused too, since `format` is a field, and either
side winning would advertise what the declaration does not say or drop what
was written. Refusing a keyword only when one build happened to state it would
make one declaration valid until the array cap came on or a spec moved to
`REJECT`. A value JSON cannot carry - a `Decimal`, a lazy translation - is
refused too, at any depth, naming its key, since every transport encodes the
schema as JSON. The mapping is held as a deep copy, so changing it afterwards
leaves the declaration as written, and its values are placed in each schema as
the declaration holds them, as a default's are.

It is advertised, not enforced. The shape check never reads it, so on a
Parameter what it states holds only where the spec's Validator enforces it,
and on an OutputField it describes what the presenter renders.

### A partial update

A spec declaring `partial=True` takes any subset of its Validator's
parameters, so its schema lists none of them in `required`: not at the top,
not in an object's fields, not in an array's rows. A client reading
`required` to decide what to send would otherwise never send the partial call
the spec exists for. The spec's `reads` and its target selector's keep their
`required`, as dispatch keeps them, so the schema still says which row the
update names. An update whose target selector reads `pk` and whose Validator
requires `title` and `body` has `"required": ["pk"]`.

On a `many` spec the list stays required and each row requires nothing.
`parameters()` is unchanged: it still says what a whole update needs, and
the schema is where the relaxing happens, through the one function the shape
check relaxes a partial call with, so the two cannot drift. A read a `kwargs`
provider fills is still listed as declared;
[`server_owned_keys`][django_service_specs.specs.server_owned_keys.server_owned_keys]
is how a transport finds those, and the schema's `required` less that set is
exactly what dispatch refuses when it is absent. A transport that binds or
withholds parameters of its own subtracts its
[`ServerArguments`][django_service_specs.types.server_arguments.ServerArguments]'
`names()` too: see [arguments the server supplies](dispatching.md#arguments-the-server-supplies).

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
| A `LIST` selector spec with `allow_none=True` | `{"type": "array", "items": <item>}`: its selector's `None` is presented as `[]` |
| A `RETRIEVE` selector spec | the item |
| A `RETRIEVE` selector spec with `allow_none=True` | the item, with `"null"` in its type |
| A service spec whose output selector is a `LIST` | `{"type": "array", "items": <item>}` |
| A service spec whose output selector is a `RETRIEVE` | the item, with `"null"` in its type |
| A service spec with no output selector | the item |
| A service spec with no output selector, with `allow_none=True` | the item, with `"null"` in its type |
| A `many` service spec with no output selector | `{"type": "array", "items": <item>}`, with `"null"` in its type under `allow_none=True` |
| A `returns_many` service spec | `{"type": "array", "items": <item>}`, with `"null"` in its type under `allow_none=True`; never paged, with or without `paginate=True` |

Where the table says `"null"` is
[`can_present_nothing`][django_service_specs.schema.can_present_nothing.can_present_nothing]'s
answer, exported for a transport that writes an output schema of its own, so
the two cannot disagree. It reads neither `many` nor `returns_many`: either
service's list may be `None` exactly where any service's return may.

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

### A spec that declares shapes

A spec's `shapes` say what its presenter renders, and a `fields` selection there
leaves keys out of a row, so whether a key is present depends on what the
caller sent. Nothing in the presenter's declaration says that for every value
a caller may send, so for a spec declaring any `shapes` the item lists no
`required`: not at its top, not in a nested object's fields, not in an array's
rows. Every field is still described, nested ones included, so a client
still knows what a key means when it is there.

The trigger is any shape, not one marked as a field selection. A shape is a
`Parameter`, the presenter reads it however it likes - a `query` over each
row leaves keys out as surely as a `fields` list - and a flag saying "this one
selects fields" would be a claim nothing could check.

What the kernel writes around the item keeps its own `required`, wherever the
item sits: the `affordances` object dispatch adds to each row stays required,
with its answers' schema whole, and a page's envelope still requires `items`,
`page`, `totalPages` and `hasNext`. A spec declaring no shapes is described
exactly as before, with the `required` its presenter's `always_present`
states. [Shaping each row by the call](paging-and-projection.md#shaping-each-row-by-the-call)
shows a shaped list.

## What is deliberately not emitted

- **No `title` on an input property.** A Parameter has no label of its own;
  on input a `title` is only ever a choice's. On output, a field's `label`
  becomes its `title`, and adapters set a label only where the author wrote
  one, so a title is never the field's name restated.
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
