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

The service, the selector, `extend_queryset` and a pool seed's resolver are all
called the same way: with the keywords their signature declares, picked from a
pool dispatch builds for the call, and nothing else. A callable that takes
`**kwargs` receives the whole pool.

| Name | Holds | In the pool of |
| --- | --- | --- |
| `user` | The principal | Every callable |
| `progress` | The transport's progress reporter, or `null_progress` | Every callable; the caller's reporter only in the run's pool and a callable affordance condition's |
| each validated value, by name | What the Validator returned | The service |
| `data` | All of the validated values, as one mapping | The service |
| `instance` | The row an instance selector resolved | The service |
| `collection` | The rows a collection selector resolved | The service |
| each of a selector's `reads`, by name | The checked argument | That selector |
| `result` | The service's return | The output selector |
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
singleton, or of an upsert's target.

`reads` is the selector's whole input. There is no Validator in front of a
read, so these Parameters are what the closed argument set and the shape check
hold the caller to: an argument the spec does not declare is refused before
the selector runs.

`select_related`, `prefetch_related` and `annotations` are applied to the
queryset the selector returns, in that order, and `extend_queryset` last, with
the shaped queryset as `queryset`. Declaring any of them on a selector that
returns something other than a queryset is refused at dispatch.

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
[relation-write example](relations.md#a-worked-example) uses one.

`atomic=True`, the default, runs the service inside `transaction.atomic()`.
`metadata` holds a project's own per-operation facts, stored as given, for its
own checks or audit hooks to read.

`spec.parameters()` is everything the write takes: its target selector's
`reads`, then its Validator's parameters. A name both declare is refused -
two sources claiming one argument is a declaration bug, and a last-wins merge
would hide which declaration a transport describes. The selector sees only its
own `reads`, and the Validator only its own parameters.

## Parameters

[`Parameter`][django_service_specs.parameters.parameter.Parameter] is one thing
an operation takes, and every transport describes itself from it rather than
from whichever validation library the spec happens to use: a JSON Schema,
argv options, the closed argument set and the shape check are all derived from
the same declaration.

- **`type`** is a JSON type: `string`, `integer`, `number`, `boolean`, `array`
  or `object`. JSON's own, because that is what crosses every wire the kernel
  serves: a JSON-RPC call, a queue row, and argv once it has been read.
- **`format`** is `decimal`, `date-time` or `date`, on a `string`: a value JSON
  cannot carry, which travels as a string for the Validator to decode.
- **`items`** is an array's element: a JSON type name for a flat list, or the
  `Parameters` of the object each row is. **`fields`** is the same for an
  `object`. Nesting is what lets a write declare its rows, so a malformed row
  is refused by the declaration rather than reaching a constructor.
- **`choices`**, **`nullable`** and **`required`** mean what they say.
  `choices` on an array constrains each element.
- **`items_nullable`** is the element's own nullability, as `list[int | None]`
  declares it: whether a `null` may stand where an element would. It is
  independent of `nullable`, which is the array's, and it needs `items`,
  since an undeclared element admits anything already.
- **`default`** is [`UNSET`][django_service_specs.types.unset.UNSET] when none
  is declared, so a default of `None` stays a real default. It is reported, not
  applied: whether an omitted argument arrives as its default is the validating
  library's behaviour.

There are no bounds (`maxLength`, `minimum`) on a Parameter; the Validator
enforces those.

[`Parameters`][django_service_specs.parameters.parameters.Parameters] is an
ordered set of them. `Parameters.of(a, b)` builds one, `+` joins two, and a
name declared twice is refused either way.

## The Validator

A [`Validator`][django_service_specs.validation.validator.Validator] turns
JSON-like arguments into the values a service receives. The contract is two
methods:

- `parameters()` declares what it takes, as `Parameters`. It must never query,
  because a transport describes a spec before any call.
- `validate(arguments, context)` returns the validated values keyed by name, or
  raises [`InvalidArguments`][django_service_specs.parameters.invalid_arguments.InvalidArguments].
  It receives only the arguments its own `parameters()` declare, already
  through the shape check, and a
  [`ValidationContext`][django_service_specs.validation.validation_context.ValidationContext]
  carrying the principal and the resolved target. It may query - a uniqueness
  check does - and the target is there so that an update's check can exclude
  the row being updated.

Three things a newcomer may look for are absent on purpose:

- **It is nominal.** An adapter subclasses `Validator`, and subclassing is the
  opt-in. A structural check on a method name would let stock classes through
  by accident: an `is_valid` method matches a Django form, a `validate` method
  matches a pydantic model class, and neither was written to this contract.
- **There is no `partial`, `instance` or `many`.** Those are one HTTP
  framework's update and list semantics. Off HTTP, what an update may omit is a
  property of the declared parameters, the row it acts on is target
  resolution, and a list is an array parameter.
- **It is sync-only.** It may query, so the async entry point runs it in
  Django's thread-sensitive executor, and it must not be `async def`.

### The dataclass adapter

[`DataclassValidator`][django_service_specs.adapters.dataclass.dataclass_validator.DataclassValidator]
is the reference adapter: what any adapter owes the kernel, with nothing but
the standard library and Django. It reads a dataclass's fields and annotations
into `Parameters`, and builds the instance from the arguments, nested
dataclasses included.

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
| `Literal[...]`, an `Enum` (Django's `TextChoices` and `IntegerChoices` included) | Choices. An `Enum` decodes to the member. |
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
  given a row or a collection. It may query, and it is sync-only.

An `OutputField` carries what a reader needs beyond a name and a type: a
`label`, `choices` as value-and-display pairs (a table shows the display, a
schema states it), `always_present` for a key that some rows omit, and a
[`FieldMarking`][django_service_specs.output.field_marking.FieldMarking] saying
who the field is for. The
[`FieldAudience`][django_service_specs.output.field_audience.FieldAudience] is
`CONTENT` by default, `LABEL` for the field that names the record,
`HANDLE` for an opaque identifier that is passed to other tools and never read
out to a person, and `HIDDEN` for plumbing. The kernel carries the marking on
the declaration and applies it only for a caller that names an audience,
through
[`render_for_audience`][django_service_specs.dispatch.render_for_audience.render_for_audience];
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
