# Declaring an operation

An operation is a **spec**: a frozen dataclass that says what the operation
takes, who may run it, what it acts on and what it returns. There are two.

- [`SelectorSpec`][django_service_specs.specs.selector_spec.SelectorSpec] is a
  **read**: a list or a retrieve.
- [`ServiceSpec`][django_service_specs.specs.service_spec.ServiceSpec] is a
  **write**: a service, the row or rows it acts on, and what it returns.

Specs are usually built at module level, at import time. Anything that could
need the app registry - reading a Validator's declaration, resolving an
annotation - happens on first use instead, so building a spec never does.
A declaration no reader could act on is refused where it is written, with
`ImproperlyConfigured` naming the field: a Validator *class* where an instance
belongs, both an instance and a collection selector, a presenter declared on a
service and on its output selector, a string where `select_related` wants a
sequence.

## Every callable declares what it receives

The service, the selector, `extend_queryset`, the providers, the preconditions
and a pool seed's resolver are all called the same way: with the keywords their signature declares, picked from a
pool dispatch builds for the call, and nothing else. A callable that takes
`**kwargs` receives the whole pool.

| Name | Holds | In the pool of |
| --- | --- | --- |
| `user` | The principal | Every callable |
| `progress` | The transport's progress reporter, or `null_progress` | Every callable; the caller's reporter only in the run's pool and its spec's callable affordance conditions' |
| each validated value, by name | What the Validator returned | The service |
| `data` | The Validator's `data`: the validated values as one mapping, or the instance a `DataclassValidator` built | The service |
| what the Validator binds, by name | A value bound for the call, its `Validated.pool` | The service |
| `instance` | The row an instance selector resolved | The service, its providers |
| `collection` | The rows a collection selector resolved | The service, its providers |
| each of a selector's `reads`, by name | The checked argument | That selector, its `kwargs` provider |
| each of a service spec's `reads`, by name | The checked argument | The service, its providers |
| each key a `kwargs` provider returns | The author's value, outranking the caller's | The selector or service it is declared on |
| `result` | The service's return | The output selector, which is handed it as `instance` too |
| `queryset` | The shaped queryset so far | `extend_queryset` |
| a registered seed | Its resolver's value | Every callable |

The fixed names - `user`, `progress`, `data`, `instance`, `collection`,
`result` and `queryset` - are
[reserved][django_service_specs.pool.reserved_pool_seeds.RESERVED_POOL_SEEDS]:
a parameter declared under one is refused, and so is a validated value
returned under one, so an argument can never outrank a value dispatch put in
the pool itself. A caller naming an argument `user` is the case that matters.
[Pool seeds](dispatching.md#pool-seeds) add names of your own, reserved the
same way.

A parameter with no default that the call's pool lacks, where a caller could
have filled it, is refused before the callable runs, on `dispatch` and
`adispatch` alike, as
[`InvalidArguments`][django_service_specs.parameters.invalid_arguments.InvalidArguments]
keyed by the parameter with the shape check's own `"This field is
required."`, rather than reaching the callable as a `TypeError`. That is a
read declared optional that the caller left out, whether the selector, its
`extend_queryset`, the service or a precondition takes it, or a Validator
parameter the caller left out, which the service takes - unless the spec is
`partial`, whose calls may leave any of those out.

Any other parameter the pool lacks is the declaration's error, and raises as
the callable's own `TypeError`. The argument set is closed, so a name that is
none of the selector's `reads` - or, for the service, none of its Validator's
parameters, which is every name when it has no Validator - can never be sent:
`REJECT` refuses it as unknown and `IGNORE` drops it. A Validator parameter
the caller did send, and the Validator did not hand back under that name -
a form that pops it in `clean()`, a pydantic field returned under its own
name rather than its alias - has been sent already. Refusing either as a
missing argument would ask for a value the caller cannot send or already
did, and a client that reads `InvalidArguments` as its own mistake would
send the call again. It is decided at dispatch rather than when the spec is
declared, because a registered seed may fill such a parameter, and the seeds
are known only then.

Four kinds of parameter are never missing: one with a default, `**kwargs`,
`*args`, and a positional-only one, which dispatch never passes by name.
Nothing the output selector declares is refused either: its pool carries no
argument, and the service has already run. Where an argument may be left out,
give the parameter a default.

## A read

```python
--8<--
docs/examples/declaring.py:selector
--8<--
```

`kind` is [`SelectorKind.LIST`][django_service_specs.specs.selector_kind.SelectorKind]
or `RETRIEVE`. A retrieve returns one row: a queryset is read with `.first()`,
a `DoesNotExist` raised by a selector written with `.get()` means the same
missing row, and a missing row is reported as not-found unless the spec sets
`allow_none=True`, which makes it the value `None` - the shape of an optional
singleton, or of an upsert's target. On a list, `allow_none=True` says the
selector may return `None` for "no rows": the result is the empty list, its
scope check and `preconditions` are asked of that empty set as they are of an
empty queryset, and the shaping is skipped, since there is nothing to shape.
Without it, a list selector's `None` is passed on as it came, and presenting it
fails as the author's error.

`reads` is the selector's whole input. There is no Validator in front of a
read, so these Parameters are what the closed argument set and the shape check
hold the caller to: an argument the spec does not declare is refused before
the selector runs.

`select_related`, `prefetch_related` and `annotations` are applied to the
queryset the selector returns, in that order, then `extend_queryset`, with
the shaped queryset as `queryset`, and `filter_set` last. Declaring any of
them on a selector that returns something other than a queryset is refused at
dispatch.

`filter_set` is a django-filter `FilterSet` class, installed with the
`filter` extra. One that declares no filters - its `base_filters` missing,
empty or `None` - is refused with `ImproperlyConfigured` when the spec is
built, unless it is a django-filter `FilterSet` class: it declares no
Parameters, so it would be handed none of the caller's data and never
filter. A duck-typed stand-in taking `(data, queryset)` declares its filters
in `base_filters`, and a step narrowing the queryset by no argument belongs
in `extend_queryset`. A real `FilterSet` declaring no filters is accepted,
and narrows nothing. Its filters are reads: each is read as a Parameter by
[`filter_set_parameters`][django_service_specs.filters.filter_set_parameters.filter_set_parameters]
and joins `reads` after the author's own, named as django-filter reads it -
`price_min` and `price_max` for a range - so the schema, the closed argument
set and the shape check cover every filter, and a filter named like a read
declared differently is refused. Every filter is optional. A number filter,
and each bound of a numeric range, is a `decimal` string, which its
`DecimalField` reads exactly: read as a float on the way, a key past `2**53`
would match its neighbour's row. A JSON number is still taken. Each such
decimal is bounded at `minimum=-1e50` and `maximum=1e50`: django-filter's
number filter refuses a value past `1e50` and leaves a range's bounds and
every negative value open, while an integer column's conversion builds every
digit of a value such as `"1E+999999999"`, which holds a worker for minutes.
So the shape check refuses either side of the line before the FilterSet is
reached. A CSV filter's numbers stay `number`, so `?pks=1,2` splits, and keep
the float reading, which cannot reach that far.

A selector spec also takes `kwargs`, `preconditions` and `progress_reporter`,
which [a write](#providers-and-preconditions) declares the same way. Its
`kwargs` provider is called from the base pool and its `reads`, and on a
selector nested in a write scopes the lookup. Its preconditions run on what
its selector found, never on a missing row. A nested selector declaring
`preconditions` or a `progress_reporter`, or an output selector declaring
`kwargs`, is refused when the write is built: dispatch never runs them.

`permissions` is required on a spec that is dispatched or registered, and
ignored on a selector nested inside a `ServiceSpec`: authorization belongs to
the spec being dispatched.

## A write

A `ServiceSpec` names its service and, at most, one target selector:

- **`instance_selector_spec`**, a `RETRIEVE`, for a service that acts on one
  row. It arrives as `instance`, and a missing row is not-found: the service
  never runs and the Validator is never asked. With `allow_none=True` on the
  selector, a missing row arrives as `instance=None` instead, which is how an
  upsert is written.
- **`collection_selector_spec`**, a `LIST`, for a bulk operation. The rows
  arrive as `collection`.
- Neither, for a create.

`output_selector_spec` re-reads what the service produced, with its return in
the pool as `result`. It is how a write returns a row with fresh annotations or
prefetches, or a list after a bulk change; the
[relation-write example](relations.md#a-worked-example) uses one. Without one,
the service's own return is what is presented, and `allow_none=True` on the
spec declares that it may be `None`, so its
[output schema](schema.md#what-a-spec-returns) admits `"null"`.

`atomic=True`, the default, runs the service inside `transaction.atomic()`.
`metadata` holds a project's own per-operation facts, stored as given, for its
own checks or audit hooks to read.

`reads` are the arguments the service, its providers and its preconditions
read with no Validator in front of them - the `project_pk` a create is scoped
by - named after a selector spec's. They are checked as a read's are and
handed to each callable that declares them, never to the Validator.

`spec.parameters()` is everything the write takes: its target selector's
`reads`, its own, then its Validator's parameters. A name two of them declare
is refused - two sources claiming one argument is a declaration bug, and a
last-wins merge would hide which declaration a transport describes. The
selector sees only its own `reads`, and the Validator only its own parameters.

### Partial updates

`partial=True` declares an update that sends only what changes, as an HTTP
`PATCH` does. Dispatch does not refuse an absent Validator parameter of such a
call, at any depth, and tells the Validator through
`ValidationContext.partial`. The spec's `reads` and its target selector's stay
required as declared unless a `kwargs` provider fills them, so a partial
update still names its row, and a value
that is sent is checked as on a whole call. `parameters()` is unchanged:
`required` still says what a whole update needs.
[`spec_input_schema`](schema.md#a-partial-update) is what a client reads, so
it requires none of the Validator's parameters at any depth, and keeps the
reads required as dispatch does.

A Validator returns only the fields the caller sent, or refuses the call.
[`FormValidator`](forms.md#partial-updates) binds only the sent fields;
`DataclassValidator` and `PydanticValidator` cannot, because each builds or
validates every field, and say so with `supports_partial = False`. With
those, an update a caller may send in part declares each such field
optional, as `AuthorPatch` below does.

Two declarations are refused with `ImproperlyConfigured` when the spec is
built, rather than on every call:

- `partial=True` with no `validator`. Only a Validator's parameters are
  relaxed, so with none the declaration changes nothing.
- `partial=True` over a Validator whose `supports_partial` is `False`, such
  as the dataclass and pydantic adapters. Every call would be refused. The
  message names the service and the Validator's class; a partial spec needs
  a Validator that can bind only what was sent, such as a `FormValidator`,
  or one of its own.

### Many rows in one call

`many=True` declares a call carrying a list of rows under one argument,
`many_argument`, `"items"` unless it names another, for one run of the
service over all of them, inside one transaction under `atomic`:

```python
--8<--
docs/examples/declaring_writes.py:many
--8<--
```

Each row is shape-checked and validated by the spec's Validator, which
declares what a row is, before the service runs, and every failing row is
refused in one `InvalidArguments` keyed by the row's `int` index under
`many_argument`, beside the shape check's refusals of the other rows; see
[the refusal tree](arguments.md#the-refusal-tree). Beside the list the call
takes the spec's `reads` and nothing else, so a value asked once for the whole
call - a confirmation - is a read. The service receives the rows' `data` as a
list under `data`, and their values as a list under `many_argument`; neither
is spread by field.

The list is an array parameter, so it is bounded as one:
**`many_min_length`** and **`many_max_length`** are its `min_length` and
`max_length`. Neither is declared by default, so an empty list runs the
service on no rows, and `many_min_length=1` is how a spec refuses one. Where
no `many_max_length` is declared, the `SERVICE_SPECS_MAX_ARRAY_LENGTH`
setting bounds the list, 1000 rows by default, since every row is a Validator
run inside one transaction. A list outside either is refused at
`many_argument` as a whole, `{"items": ["Ensure this field has no more than
200 elements."]}`, before any row is checked, beside the top level's other
refusals. Either is refused on a spec that is not `many`.

A `many` spec must declare a Validator and no target selector, since a list of
rows resolves no target, and a condition on the row among its `affordances` is
refused. With no output selector its result is `kind="list"`, unless the
service returned `None`.

### Providers and preconditions

Four declarations put the author's code between the checks and the run. Each
is called with the keywords it declares, like any other callable here, and is
sync-only: an `async def` one is refused when the spec is built.

- **`kwargs`** returns extra pool entries, merged after the caller's
  arguments, so a key it answers is the author's value whatever the caller
  sent - a tenant, a scope. A value of `UNSET` declines a key the provider is
  annotated as able to decline (or any key of an untyped provider) and leaves
  the caller's in place; a key it is annotated to fill is the server's, so the
  caller's value for it is checked and then dropped.
- **`input_data`**, on a write alone, returns values merged over the caller's
  arguments before the Validator sees them, so a server-owned field - an
  owner, a status - is the author's. A Validator field it is annotated to fill
  is not demanded of the caller, and the Validator still refuses it if the
  provider declines it. A value the caller sends for a field the provider is
  annotated to fill is dropped, not used in its place. The Validator is what
  consumes it, and the service is handed none of it directly, so a spec that
  declares `input_data` with no Validator is refused with
  `ImproperlyConfigured` when it is built: declare a Validator, or use
  `kwargs` for a value the service reads.
- **`preconditions`** are raise-to-abort rules, in declaration order, after
  the affordances and before the service, outside its transaction. What the
  first to raise raises reaches the caller as it is. One answering with a
  coroutine or an async generator is refused with `ImproperlyConfigured`
  rather than read as a pass.
- **`progress_reporter`** returns a
  [`ProgressReporter`][django_service_specs.types.progress_reporter.ProgressReporter]
  the run reports to beside the transport's - a task record, an audit trail -
  called on the run's first report. A service spec refused before its run
  never calls it; a selector spec's selector is its run, so one refused at
  its object check, its scope check or a precondition may already have.

Both providers are called from the base pool, the `reads` and the resolved
target, and never see the Validator's values. A provider returning a name
dispatch seeds itself is refused, so a provider can outrank an argument and
never a seed.

A provider annotated to return a `TypedDict` says which keys it fills before
it runs, and [`provider_keys`][django_service_specs.pool.provider_keys.provider_keys]
reads them: `filled`, and `declinable` for a key whose value admits
`UnsetType`. A filled key is not demanded of the caller where the provider's
values reach it, and the caller's value for it is dropped: a selector's `kwargs` fills that selector's `reads`, a
service spec's `kwargs` its `reads`, and `input_data` its Validator's fields.
A provider annotated to fill a parameter declared anywhere else -
`input_data` naming a read, `kwargs` naming a Validator field or the target
selector's read - is refused with `ImproperlyConfigured` when the spec is
built or, for a Validator field, when `parameters()` is assembled.
[`server_owned_keys`][django_service_specs.specs.server_owned_keys.server_owned_keys]
gathers what every provider of a spec fills, with the seeds' names. None of
them is a parameter dispatch demands, so a transport building an input schema
of its own subtracts the set from what `parameters()` lists:

```python
--8<--
docs/examples/declaring_writes.py:providers
--8<--
```

On a `many` spec, the keys an `input_data` provider fills are fields inside
each row, merged over every row, so a transport subtracting the set from the
top-level `parameters()` - the list and the reads - removes nothing: it hides
them from the list's items instead.

## Parameters

[`Parameter`][django_service_specs.parameters.parameter.Parameter] is one thing
an operation takes, and every transport describes itself from it rather than
from whichever validation library the spec happens to use: a JSON Schema,
argv options, the closed argument set and the shape check are all derived from
the same declaration.

- **`type`** is a JSON type: `string`, `integer`, `number`, `boolean`, `array`
  or `object`. JSON's own, because that is what crosses every wire the kernel
  serves: a JSON-RPC call, a queue row, and argv once it has been read. The
  one other type is **`file`**, a Django `File`: what a multipart body carries
  beside its fields, and what a Python caller hands a command or a task. No
  JSON caller can send one, and it declares no choices.
  **`any`** declares no type, as an unannotated argument does: a key that may
  be `3` or `"abc"`. The value is handed on as it arrived, with no coercion,
  so a query string's `"3"` stays the string `"3"`, and the schema states no
  `"type"` for it. It takes no `choices`, `format`, `fields`, `items` or
  bound, and an array's `items` never name it: an array with no `items` takes
  any element already.
- **`format`** is `decimal`, `date-time` or `date`, on a `string`: a value JSON
  cannot carry, which travels as a string for the Validator to decode.
- **`items`** is an array's element: a JSON type name for a flat list, or the
  `Parameters` of the object each row is. **`fields`** is the same for an
  `object`. Nesting is what lets a write declare its rows, so a malformed row
  is refused by the declaration rather than reaching a constructor.
- **`choices`**, **`nullable`** and **`required`** mean what they say.
  `choices` on an array constrains each element.
- **`minimum`** and **`maximum`** bound a number, inclusively: an `integer`, a
  `number` or a `decimal` string, refused in the words Django's
  `MinValueValidator` and `MaxValueValidator` use. Each is an `int` or a
  finite `float`, and a bound on any other type is refused where it is
  written. A decimal string is compared as the decimal it spells, by its
  exponent, so `"1E+999999999"` is refused without building the integer it
  names. The schema states both as `"minimum"` and `"maximum"`.
- **`min_length`** and **`max_length`** bound how many elements an `array`
  takes, inclusively, each a non-negative `int`, and are refused on any other
  type. An array that declares no `max_length` is still bounded, by the
  `SERVICE_SPECS_MAX_ARRAY_LENGTH` setting, 1000 by default; see
  [how long a list may be](arguments.md#how-long-a-list-may-be). The schema
  states them as `"minItems"` and `"maxItems"`.
- **`choice_labels`** names the choices for a reader, as a mapping of a choice
  to its label or as Django's pairs. The labels constrain nothing; the schema
  states each as a choice's `title`. A label may be a lazy translation.
- **`items_nullable`** is the element's own nullability, as `list[int | None]`
  declares it: whether a `null` may stand where an element would. It is
  independent of `nullable`, which is the array's, and it needs `items`,
  since an undeclared element admits anything already.
- **`default`** is [`UNSET`][django_service_specs.types.unset.UNSET] when none
  is declared, so a default of `None` stays a real default. It is reported, not
  applied: whether an omitted argument arrives as its default is the validating
  library's behaviour.

Any other bound - a length, a Validator field's `max_value` - is the
Validator's alone. A Parameter's bounds are for the line a caller must not
cross before any Validator runs.

[`Parameters`][django_service_specs.parameters.parameters.Parameters] is an
ordered set of them. `Parameters.of(a, b)` builds one, `+` joins two, and a
name declared twice is refused either way.

## The Validator

A [`Validator`][django_service_specs.validation.validator.Validator] turns
JSON-like arguments into the values a service receives. The contract is two
methods, and a third method and an attribute with defaults:

- `parameters()` declares what it takes, as `Parameters`. It must never query,
  because a transport describes a spec before any call.
- `validate(arguments, context)` returns the validated values keyed by name, or
  raises [`InvalidArguments`][django_service_specs.parameters.invalid_arguments.InvalidArguments].
  It receives only the arguments its own `parameters()` declare, already
  through the shape check, and a
  [`ValidationContext`][django_service_specs.validation.validation_context.ValidationContext]
  carrying the principal and the resolved target. It may query - a uniqueness
  check does - and the target is there so that an update's check can exclude
  the row being updated. The context also says whether the call is
  [`partial`](#partial-updates).
- `validated(arguments, context)` is what dispatch calls: a
  [`Validated`][django_service_specs.validation.validated.Validated] carrying
  the `values` the service is spread with, the call's `data`, and a `pool` of
  any other value bound for the call, such as the bound object a library
  validated through. The default wraps `validate()`, with the values as
  `data` and nothing bound, so a Validator overrides it only where its `data`
  is not that mapping. A bound value named after a seed, a validated value or
  a parameter is refused.
- `supports_partial`, a class attribute, says whether `validate()` can honour
  a [`partial`](#partial-updates) call by returning only what was sent. It is
  `True` by default. A Validator that builds every field sets it `False`, and
  a partial spec over it is then refused when the spec is built.

Three things a newcomer may look for are absent on purpose:

- **It is nominal.** An adapter subclasses `Validator`, and subclassing is the
  opt-in. A structural check on a method name would let stock classes through
  by accident: an `is_valid` method matches a Django form, a `validate` method
  matches a pydantic model class, and neither was written to this contract.
- **There is no `instance` or `many` argument.** The row a call acts on is
  target resolution, and many rows are the spec's [`many`](#many-rows-in-one-call),
  each validated on its own. `partial` arrives in the context, because it is
  the spec's statement about the call, not the Validator's.
- **It is sync-only.** It may query, so the async entry point runs it in
  Django's thread-sensitive executor; a `validate` or `validated` declared
  `async def` is refused when the spec is built.

### The dataclass adapter

[`DataclassValidator`][django_service_specs.adapters.dataclass.dataclass_validator.DataclassValidator]
is the reference adapter: what any adapter owes the kernel, with nothing but
the standard library and Django. It reads a dataclass's fields and annotations
into `Parameters`, and builds the instance from the arguments, nested
dataclasses included. The call's `data` is the instance it built, so a
service declaring `data` receives an `AuthorIn` and one declaring the fields
by name receives them as before. It cannot validate a partial call, so a
partial spec over it is refused when the spec is built.

```python
--8<--
docs/examples/declaring.py:validator
--8<--
```

| Annotation | Declares |
| --- | --- |
| `str`, `int`, `float`, `bool` | Their JSON types. `float` also takes an integer; nothing else crosses types, so `true` is not an `int`. Through dispatch, the shape check hands an `int` field a whole float such as `2.0` as `2`. |
| `Decimal`, `datetime`, `date` | A `string` with the format it decodes from. A decimal also takes a JSON number. |
| `X \| None` | Nullable. Inside a list, `list[X \| None]`, the element is: `items_nullable`. |
| `Literal[...]`, an `Enum` (Django's `TextChoices` and `IntegerChoices` included) | Choices. An `Enum` decodes to the member. A Django `Choices` enum's labels are its `choice_labels`; a plain `Enum`'s member names and a `Literal` label nothing. |
| `list[X]` | An array. `list[SomeDataclass]` is an array of rows, each declared as nested Parameters. |
| a dataclass | An object, with its fields as nested Parameters. |
| `X \| UnsetType` | The argument may be left out, and the field then holds `UNSET`. |

A field with a default or a `default_factory` is optional; one with neither is
required. An annotation outside the table is refused, naming the field.

What `DataclassValidator(AuthorIn)` declares, then: `name`, a required string,
and `books`, an optional array whose rows take a required `title`, a required
`price` (a `string` in the `decimal` format), a `status` with the choices
`draft` and `published` and the default `draft`, a nullable `published_on` in
the `date` format, and a nullable integer `pk`. Its `validate()` returns the
books as `BookIn` instances, which is what the relation writes read a row from.

Two rules on that example are easy to miss:

- **A row that updates must declare its key.** A relation write matches an
  incoming row to an existing one by primary key, so `BookIn` declares
  `pk: int | None = None`: present for a book that exists, absent for a new
  one. Without it no incoming row matches, and every update replaces every
  row. Nothing fails when that happens, which is why it is said here.
- **An update's fields should be omittable.** `AuthorIn.books` defaults to an
  empty list, which is right for a create and wrong for an update: an author
  updated without `books` would arrive with `books=[]` and lose them all.
  `AuthorPatch` declares every field `X | UnsetType = UNSET`, so a field the
  caller left out arrives as `UNSET`, and the mutation helpers leave it alone.

An offset-less date-time is made aware in the current time zone when `USE_TZ`
is on, as Django's forms do, so a date-time means the same instant whichever
library validated it. Every failure is reported at once, as one
`InvalidArguments` tree; [Arguments and refusals](arguments.md) describes it.

## Output and the Presenter

A [`Presenter`][django_service_specs.output.presenter.Presenter] turns one value
an operation produced into JSON-like data. It is the output-side counterpart of
the Validator:

- `output()` declares the result as an
  [`Output`][django_service_specs.output.output.Output], an ordered tuple of
  [`OutputField`][django_service_specs.output.output_field.OutputField]. It
  never queries. The declaration is what a reader that never renders needs: an
  agent tool's output schema, a command's table header when there are no rows,
  a confirmation page. An HTML transport hands the row to a template and never
  renders it, and still reads the declaration.
- `present(value)` renders **one** value. Dispatch's
  [`present`][django_service_specs.dispatch.present.present] hands a list's
  items over one at a time, so a Presenter never has to guess whether it was
  given a row or a collection. It may query, and it is sync-only: an
  `async def` `present` is refused when the spec is built.

An `OutputField` carries what a reader needs beyond a name and a type: a
`label`, `choices` as value-and-display pairs (a table shows the display, a
schema states it), `always_present` for a key that some rows omit, and a
[`FieldMarking`][django_service_specs.output.field_marking.FieldMarking] saying
who the field is for. The
[`FieldAudience`][django_service_specs.output.field_audience.FieldAudience] is
`CONTENT` by default, `LABEL` for the field that names the record,
`HANDLE` for an opaque identifier that is passed to other tools and never read
out to a person, and `HIDDEN` for plumbing. A marking may also carry a
[`ValueFormatter`][django_service_specs.types.value_formatter.ValueFormatter],
which renders the field's value for that audience, a date-time in the
active time zone say, and states the JSON type it produces (see
[formatting a value](paging-and-projection.md#formatting-a-value)). The kernel
carries the marking on the declaration and applies it only for a caller that
names an audience,
through
[`present_for_audience`][django_service_specs.dispatch.present_for_audience.present_for_audience];
`present`, and so every HTTP response, serves every field. See
[paging and projection](paging-and-projection.md).

[`DataclassPresenter`][django_service_specs.adapters.dataclass.dataclass_presenter.DataclassPresenter]
declares the output as a dataclass and reads each field off the value **by
attribute**, so the value is usually a model row and is never converted into
the dataclass first. A nested dataclass field is read the same way, and a list
field may be a related manager, read through `.all()` so a prefetch is used.
A `Decimal` is rendered as its string, a date or date-time in ISO 8601, an
`Enum` as its value. A marking is declared in the field's annotation, as
`NoteRow` does above: `Annotated[int, FieldMarking.handle()]`.

A read's presenter is its own `presenter`. A write's is its own, or its output
selector's when it declares none, and declaring both is refused. A presenter on
an instance or collection selector is never read, because the service consumes
those rows rather than returning them.
