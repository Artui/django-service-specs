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
An integral float is an `integer`: JSON Schema counts `5.0` as one, so the
`{"type": "integer"}` the kernel advertises admits it, and the check hands
the Validator `5` wherever the declaration reaches, so the Validator's own
type check and bounds read the int. `5.5` is still refused, and a `number`
keeps its float. DRF's `IntegerField`, like Django's form field, reads
`str(value)`, so given `1e16` it reads `"1e+16"` and refuses it; the check
follows JSON Schema and hands on `10000000000000000`.

**A string spelling a number is that number** where an `integer` or a
`number` is declared, wherever the declaration reaches, and the number is
handed on: `"3"`, `"3.0"` and `" 3 "` are 3, and a number's `"1e3"` is
1000.0. Django's forms and pydantic's lax mode both read these strings so,
and the reading is the one [`coerce_flat`](#flat-transports) makes, which the
check shares. Where the two differ it is Django's: an integer's `"5."` and
`"5 .0"` are 5, which pydantic's `int` refuses. A string that spells no such
number is refused as the type it is not, and `true` is still neither. The
number goes on rather than the string because a Validator stricter than those
two, the dataclass adapter's, refuses `"3"` for an `int`.

**A `number`'s string is read as a JSON decoder reads its literal**: digits
alone are the exact integer they spell, and a point or an exponent makes a
float. So `"9007199254740993"` goes on as that integer, as the JSON literal
does, where a float would round it to its neighbour, and `"3"` goes on as the
3 a JSON body's `3` is. Digits alone that Python's `int` refuses, past the
4300 it reads from Python 3.10.7 on, spell no number either, even where zeros
in front leave a float able to read them. A fraction finer than a float holds is rounded, as the
JSON literal is; a value that must be exact is declared a `decimal`, and so is
each element of an array that must be: `items="string"` with
`format="decimal"`, as a django-filter CSV number filter declares, keeps every
digit of each element and still splits `?pks=1,2`.

**Only an ASCII string spells an `integer` or a `number`**, and this is one of
three places the check is stricter than the libraries behind it, the others
being a declared `minimum` or `maximum` and
[the length of a list](#how-long-a-list-may-be). Python's `int` and `float`,
and so Django's number fields, read Arabic-Indic and fullwidth digits and
strip any Unicode space; no JSON number is spelled so, and pydantic refuses
them. `"\u0665"`, the JSON spelling of an Arabic-Indic five, is refused as the
type it is not, by the check and by `coerce_flat` alike. A `decimal` string is
not read this way, and on purpose: it is checked as Python's `Decimal` reads
it, which takes those digits too, because every decimal field behind the check
reads it so - Django's `DecimalField`, DRF's and pydantic's `Decimal` each hand
the string to `Decimal` - and the string is handed on unchanged. `"\u0665"`
sent for a decimal is 5 to all of them, as `"5"` is.

A **`file`** is a Django `File`, an upload included, and nothing else is one:
no JSON value can be, so a JSON caller's string for one is refused at its
name.

An **`any`** declares no type, so every value is one and is handed on exactly
as it arrived: a `"3"` stays the string, never read as the number it spells.
`null` is still refused unless the parameter is `nullable`, and NaN and the
infinities are still no JSON value. Nothing is checked against a type, so a
value of no JSON type is handed on too: a Python caller's, or a multipart
upload sent under the parameter's name.

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

### How long a list may be

**An array's length is read before any of its elements**, so a list longer
than it takes is refused whole, at its name, and costs no per-element work.
A parameter's `min_length` and `max_length` bound it inclusively. One that
declares no `max_length` is still bounded, by the
**`SERVICE_SPECS_MAX_ARRAY_LENGTH`** setting: 1000 unless the project sets
another count, the line Django's `DATA_UPLOAD_MAX_NUMBER_FIELDS` draws for a
form body, or `None`, which bounds no array. A declared `max_length` outranks
the setting either way, wider or narrower. The setting is read at the call,
so `override_settings` reaches a spec built at import, and so checking an
array with no `max_length`, by the shape check or `coerce_flat`, needs
Django's settings configured.

```python
--8<--
docs/examples/arguments.py:length
--8<--
```

Like the ASCII rule and a declared `minimum` or `maximum`, this is a place
the check can be stricter than the library behind it, on purpose: a list is a
cost its caller controls the size of. Each row of
a [`many`](declaring.md#many-rows-in-one-call) call is a Validator run inside
one transaction, and each value of a django-filter `in` lookup is one query
variable, past whose limit the database refuses the query and the caller
gets a 500 rather than a refusal. The default reaches every array the
declaration reaches - a row's own array included, a CSV filter's, a `many`
call's list of rows - and a project whose Validator takes longer lists
raises the setting or declares the `max_length`. A `min_length` past the
setting on a parameter with no `max_length` of its own is a declaration no
call could meet, refused as `ImproperlyConfigured` at the call and when its
schema is built, since the setting cannot be read where the parameter is
written.

The messages are DRF's, `"Ensure this field has no more than {max_length}
elements."` and `"Ensure this field has at least {min_length} elements."`: no
Django catalog entry counts a list's elements, and DRF's catalog translates
these wherever DRF is installed.

Under `partial=True` no absent parameter is refused, at any depth: a partial
update sends only what changes. A value that is present is checked as it would
be otherwise, and an unknown key is still refused. Dispatch relaxes a
[`partial`](declaring.md#partial-updates) write's Validator parameters, and a
parameter a provider is annotated to fill, so a transport checking a call as
dispatch will calls
[`bind_arguments`][django_service_specs.dispatch.bind_arguments.bind_arguments]
rather than `check_arguments(partial=True)`.

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

A [`many`](declaring.md#many-rows-in-one-call) write's rows are addressed the
same way, under its `many_argument`: `{"items": {2: {"title": [...]}}}`, a
message about a row itself under `non_field_errors` inside it, and the list's
own refusal - absent, null, not a list - as `{"items": [...]}`. The shape
check's refusals of some rows and the Validator's of others come back in the
one tree.

Every leaf is a list of strings, so the tree is JSON-serializable once the
integer keys are written as strings, which is what `json.dumps` does. The
messages are spelled as Django's own form fields spell them wherever one has
the message, so Django's catalogue translates them and a project adds nothing.
Each also carries a code, which the next section reads.

[`DataclassValidator`][django_service_specs.adapters.dataclass.dataclass_validator.DataclassValidator]
answers in the same tree, and so does a relation write that refuses a row, so
a transport reads one shape whichever of them refused.

## The codes a refusal carries

A message is for a person, and is translated. A program reading the tree needs
something that is not, so every refusal the kernel and its shipped adapters
make is a
[`CodedMessage`][django_service_specs.parameters.coded_message.CodedMessage]: a
`str` carrying a `code`. The code is the one a DRF field gives the same mistake,
so an adapter building DRF's `ErrorDetail` from the tree maps each one across
unchanged, and a client of both reads one `get_codes()`.

```python
--8<--
docs/examples/arguments.py:codes
--8<--
```

| Refusal | Code | Raised by |
| --- | --- | --- |
| A required argument is absent | `required` | the shape check |
| A null where none is allowed | `null` | the shape check |
| A key nobody declared, under `REJECT` | `unknown` | the shape check |
| A value of the wrong type, a malformed date or date-time, a decimal or number that is not finite, a row that is not an object | `invalid` | the shape check |
| A value that is not an array where one is declared | `not_a_list` | the shape check |
| A number past its `maximum`, or short of its `minimum`, an array's element at its index | `max_value`, `min_value` | the shape check |
| A value outside its `choices` | `invalid_choice` | the shape check |
| An array longer than it takes, or shorter | `max_length`, `min_length` | the shape check, `coerce_flat` |
| A flat string that spells no integer, number or boolean, or one sent for a parameter with nested parameters | `invalid` | `coerce_flat` |
| A request body that is not JSON | `parse_error` | `request_arguments` |
| A request body that is not a JSON object | `invalid` | `request_arguments` |
| A read a selector, its `extend_queryset` or a precondition asks for that nothing filled | `required` | dispatch, as the shape check would |
| A value a FilterSet refuses | its form field's own code, `invalid` where it has none | the FilterSet, through dispatch |
| A number past a signed 64-bit integer sent to a filter on an integer column, a range filter's bound at its own argument and a CSV filter's element at its index | `max_value`, `min_value` | dispatch, applying the FilterSet |
| A model choice filter's key past the range of the column its rows are matched on | `invalid_choice` | dispatch, applying the FilterSet |
| A `null` row in a relation's list | `null` | a [relation write](relations.md) |
| A row's data Django fails to write | the `ValidationError`'s own code, `invalid` where it has none and for a `TypeError` or `ValueError` | a [relation write](relations.md) |

The shipped Validators code theirs the same way:

| Validator | Its refusals |
| --- | --- |
| `DataclassValidator` | `required`, `null`, `unknown`, `invalid_choice`, and `invalid` for a wrong type, a decimal or date that does not parse, and a `ValueError` from `__post_init__`; a Django `ValidationError` from `__post_init__` keeps its own code, `invalid` where it has none |
| `FormValidator` | Django's own code on each message, the field's and the form's: `required`, `max_length`, `invalid_choice`, `unique_together` and the rest; `invalid` for a message raised with none |
| `PydanticValidator` | pydantic's error type mapped to DRF's code: `missing` is `required`, a `None` a type refuses `null`, a length `max_length` or `min_length`, a bound (an exclusive one too) `max_value` or `min_value`, a `Literal` or `Enum` `invalid_choice`, a list's type `not_a_list`, a decimal's digits `max_digits`, `max_decimal_places` or `max_whole_digits`, a forbidden extra key `unknown`; any other of pydantic's own types, and a `ValueError` in a validator, `invalid`; a `PydanticCustomError` keeps its type as its code |

**Django's codes are Django's**, and not always DRF's: a pair a model holds
unique together says `unique_together` from a form, where DRF's serializer
validator says `unique`. They come through as Django raised them rather than
translated to a guess.

Two have no DRF field to follow. DRF ignores a key a serializer does not
declare, so it has no code for refusing one, and `unknown` names the
[policy](#the-closed-argument-set) that refused it. And a body DRF cannot parse
is its `ParseError`, which is not a validation error there and is here, so
`parse_error` is that exception's own code. A free-form `object` is `invalid`,
as a nested serializer's refusal is, where DRF's `DictField` would say
`not_a_dict`. An empty `many` list refused by `many_min_length=1` is
`min_length`, as its message says, where a `ListSerializer` with
`allow_empty=False` says `empty`.

**A `CodedMessage` is its message to everything else.** It equals and hashes as
its `str`, and `json.dumps` writes the plain message, so the codes never reach a
body a transport writes and a test comparing a tree with plain strings is
unchanged by them. A copy and a pickle keep the code.

**A Validator's messages reach the tree as it raised them**, on one call and
row by row on a `many` call. Dispatch does not rewrap them: a library's own
coded message, DRF's `ErrorDetail` among them, keeps its code, and a plain
`str` stays one, with no code. So does a project's own Validator raising
plain strings, so read a code with
`getattr(message, "code", ...)` and choose the default, as the example's
`"invalid"` is DRF's own for a message raised with none.

**One check answers a field.** The shape check runs before the Validator, so a
call it refuses is never validated, and only its codes come back: a title that
is blank and sent beside an unknown key reads `unknown` alone, not `blank`
too. A [`many`](declaring.md#many-rows-in-one-call) call reads the same way
row by row: a row the shape check refuses is never handed to the Validator,
while every row it lets through is, so the two checks' refusals of different
rows come back in one tree.

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

- An `integer` or a `number` is parsed. An integer is read as Django's
  `IntegerField` reads one: `"5.0"` and `"5."` are 5, and `"5.5"` is refused
  with `"Enter a whole number."`. A number is read as a JSON decoder reads
  the same literal: `"3"` is the integer 3, exactly, and `"2.5"` and `"1e3"`
  are floats, so `?pks=9007199254740993` is that key and not its neighbour.
  Each element of an array, a repeated query-string key's included, is read
  the same way.
- A `boolean` is parsed from exactly four spellings - `true`, `false`, `1`, `0`,
  in any case - and anything else is refused with
  `"Enter true, false, 1 or 0."`. Libraries disagree about every other
  spelling (a Django `BooleanField` reads `"no"` as true), so refusing is the
  one answer that cannot set a flag the caller meant to clear.
- A decimal, a date-time and a date **stay strings**, for the Validator to
  decode, exactly as they would arrive off a JSON wire. So does each element
  of an array of decimal strings, which the shape check then reads and
  bounds as a decimal, at its index.
- **An `any` stays the string it arrived as**: it declares no type to read the
  string as, so `?pk=3` reaches the Validator as `"3"`, not 3.
- An array's elements are coerced by its `items` type, and a single value
  becomes a one-element list, since a flat transport sends a one-element list
  as a bare value. **An array longer than it takes is refused whole**, before
  any element is parsed, by [the same length rule](#how-long-a-list-may-be) as
  the shape check's. A query string's `?ids=1,2,3` is split into no more
  than one element past the most the array takes, so a value of a million
  commas is refused without becoming a million elements first: Django's
  `DATA_UPLOAD_MAX_NUMBER_FIELDS` counts keys, and a comma list is one.
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
