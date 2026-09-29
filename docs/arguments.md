# Arguments and refusals

Parameters are declared; arguments are supplied. This page is about the
arguments: what is checked before an operation runs, the shape a refusal
takes, how a flat transport's strings become typed values, and the two
families of error a transport answers.

## The shape check

[`check_arguments`][django_service_specs.parameters.check_arguments.check_arguments]
is step one of every dispatch, and of
[`bind_arguments`][django_service_specs.dispatch.bind_arguments.bind_arguments].
It checks what a caller can get wrong that the declaration can see - presence,
JSON type, format, choices and nullability - at every level of nesting, with no
query. It returns a cleaned copy and never modifies what it was given.

It is **no stricter than the libraries behind it**. A decimal accepts a JSON
number as well as a string, because every decimal validator does, and a check
stricter than the worker would refuse calls that would have run. A required
parameter with a declared default is not refused when absent, because the
Validator will supply the default. A JSON `true` is neither an `integer` nor a
`number`, although Python makes `bool` an `int`: sent for a count, it is a
caller's mistake, not the number one.

NaN and the infinities are refused, and that is a type rule rather than a
stricter check: JSON has no spelling for either, so they are outside the
`number` type, and only a decoder reading an overflowing literal such as `1e400`,
or a Python caller, can produce one. Two validators would take one all the same -
pydantic's `float` and the dataclass adapter's - where Django's number fields
refuse both. A `number`, a decimal or an element of an array with no `items` is
refused with `"Enter a number."`; any other type refuses one as the wrong type.
Like every rule here, it holds wherever the declaration reaches: inside a
free-form object, or an object or array element that nothing declares, the
contents are the Validator's.

It runs before the Validator by design, so a Validator is only ever handed
well-shaped arguments - and a test of a Validator fed a malformed argument
passes without exercising the Validator.

## The closed argument set

An argument no parameter declares is refused where it appeared, under
`"Unknown argument."`. That holds **at every level**, inside each row and each
nested object as well as at the top: closed only at the top, an unknown key in
a row would reach the row's constructor and come back as a `TypeError` naming
no row.

[`UnknownArguments.REJECT`][django_service_specs.validation.unknown_arguments.UnknownArguments]
is the default everywhere. An untrusted caller's undeclared key is refused
before it costs a query, and a trusted caller's typo - a command's misspelt
option, a task enqueued with last month's argument name - fails where the
caller can see it instead of being dropped. `IGNORE` drops undeclared keys
instead, at every level:

```python
--8<--
docs/examples/arguments.py:ignore
--8<--
```

There is no third policy that passes an undeclared argument through. Reaching a
callable is exactly what the closed set prevents: on a read, with no Validator
in front of it, it would let a caller supply a keyword the operation's author
never offered.

`dispatch`, `adispatch` and `bind_arguments` each take `unknown_arguments=`.

## The refusal tree

Every refusal of arguments is
[`InvalidArguments`][django_service_specs.parameters.invalid_arguments.InvalidArguments],
whoever made it: the shape check, the closed argument set, `coerce_flat`, a
Validator, or a relation write. It carries **every** problem found, not the
first, as one tree in `.detail` addressed by path:

```python
--8<--
docs/examples/arguments.py:tree
--8<--
```

- A field's messages are a list under its name: `{"title": ["..."]}`.
- A nested object's are a tree under its name: `{"author": {"name": ["..."]}}`.
- An array's rows are keyed by their **`int` index**, and only the rows that
  failed appear: the first book above is fine, so there is no key `0`.
- A message about a row itself, rather than one of its fields, sits under
  **`non_field_errors`** inside the row. The third book is not an object at all,
  so it has no field to hang the message on. `non_field_errors` is Django's and
  DRF's spelling of the same idea, so a transport that renders either's errors
  reads these without a translation table.

Every leaf is a list of strings, so the tree is JSON-serializable once the
integer keys are written as strings, which is what `json.dumps` does. The
messages are spelled as Django's own form fields spell them wherever one has
the message, so Django's catalogue translates them and a project adds nothing.

[`DataclassValidator`][django_service_specs.adapters.dataclass.dataclass_validator.DataclassValidator]
answers in the same tree, and so does a relation write that refuses a row, so
a transport reads one shape whichever of them refused.

## Flat transports

Argv and a query string carry strings. Validation libraries read strings
differently from one another, so turning them into what a JSON caller would
have sent is the kernel's job rather than each transport's:
[`coerce_flat`][django_service_specs.parameters.coerce_flat.coerce_flat],
directed by the declaration.

```python
--8<--
docs/examples/arguments.py:flat
--8<--
```

- An `integer` or a `number` is parsed.
- A `boolean` is parsed from exactly four spellings - `true`, `false`, `1`, `0`,
  in any case - and anything else is refused with
  `"Enter true, false, 1 or 0."`. Libraries disagree about every other
  spelling (a Django `BooleanField` reads `"no"` as true), so refusing is the
  one answer that cannot set a flag the caller meant to clear.
- A decimal, a date-time and a date **stay strings**, for the Validator to
  decode, exactly as they would arrive off a JSON wire.
- An array's elements are coerced by its `items` type, and a single value
  becomes a one-element list, since a flat transport sends a one-element list
  as a bare value.
- **A parameter with nested Parameters is refused by name** - an object, or an
  array of rows, has no flat spelling - with `"This argument has nested
  parameters, which a flat transport cannot send."`, rather than passing the
  string on to fail as a type error that does not say why.
- A key the parameters do not declare passes through untouched, so the closed
  argument set in `check_arguments` stays the one place that refuses it.

## Two families of error

Every error a transport answers belongs to one of two families, and the family
says **who refused**.

| Family | Members | Who refused |
| --- | --- | --- |
| [`DispatchError`][django_service_specs.types.dispatch_error.DispatchError] | `InvalidArguments`, `NotPermitted`, `PrincipalUnavailable` | Dispatch, before the operation ran |
| [`ServiceError`][django_service_specs.services.service_error.ServiceError] | `ServiceValidationError`, `ServiceConflict`, `ServiceNotFound` | The operation itself |

**Neither subclasses the other, and none of their members crosses over.** That
reads like an oversight and is the point:

- Every consumer reads a service error as a refusal the caller adapts to: an
  agent turns one into a result the model reads and routes around, and the run
  goes on. A denial declared that way becomes something the model retries,
  where a denial should end the attempt.
- An MCP server tells "invalid arguments" from "a business rule refused
  well-shaped arguments" by exactly this type difference. So
  `InvalidArguments` is not a `ServiceValidationError`: the first says the
  input was not well-shaped or did not validate, the second states a business
  rule about input that did.

A service raises the second family. [`ServiceValidationError`][django_service_specs.services.service_validation_error.ServiceValidationError]
carries a `detail` (a string, a field-keyed mapping, or a list),
[`ServiceConflict`][django_service_specs.services.service_conflict.ServiceConflict]
says the request collides with the current state and a caller may re-read and
try again, and
[`ServiceNotFound`][django_service_specs.services.service_not_found.ServiceNotFound]
says the thing is absent, or not the caller's to see - the same answer for
both, since refusing a row the caller cannot see confirms that it exists.

A transport answers each type in its own terms. One HTTP-shaped ladder:

```python
--8<--
docs/examples/transport.py:transport
--8<--
```

The subclasses of `ServiceError` are matched before `ServiceError` itself, or
the base class swallows them. A transport that has never heard of
`ServiceConflict` still handles it as a `ServiceError`.

Every 400 is a field map, whichever family refused: a service's string or
list detail goes under `non_field_errors`, where a message about the input as
a whole sits in an `InvalidArguments` tree too. A service's own refusal that
names no field (`ServiceError` itself) is a 422: the request was understood
and refused, which is not the same as malformed.

This is the ladder
[`error_response`][django_service_specs.http.error_response.error_response]
ships, statuses included, for a transport that answers over HTTP. They are
djangorestframework-services' statuses;
[Serving over HTTP](http.md) has the whole of it.

Configuration errors are neither family. A spec with no permission check, a
parameter named after a pool seed, shaping declared on a selector that returns
no queryset: each raises Django's `ImproperlyConfigured`, because it is the
declaration that is wrong, for every caller.
