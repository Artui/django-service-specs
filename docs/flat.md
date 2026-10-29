# Reading a flat source

A query string and a form's fields are flat: every value is a string, and a key
may repeat. A transport reading one has to decide which key is a list, what a
comma in a value means, and what a field left blank is, before
[`coerce_flat`][django_service_specs.parameters.coerce_flat.coerce_flat] can
turn the strings into what a JSON caller would have sent. Those decisions are
the kernel's, so every transport reading a flat wire makes them the same way:
[`flat_arguments`][django_service_specs.flat.flat_arguments.flat_arguments]
reads the source by the declaration, and nothing else.

```python
--8<--
docs/examples/flat.py:read
--8<--
```

It takes Django's `QueryDict`, or any `MultiValueDict`, and returns strings and
lists of strings. It coerces nothing: the transport merges its route's kwargs
into what it read, then calls `coerce_flat` once over the whole, so a path
segment with no converter is read by the same rules as the query beside it.

- **An `array` takes every value its key was sent with**, and anything else
  takes the last, as `QueryDict` reads a repeated key.
- **An array of numbers, integers, booleans or decimal strings splits a value
  on its commas**, `?ids=3,5` as `["3", "5"]`, with the space around each part
  trimmed, because no such element can hold a comma, and it is the spelling a
  django-filter CSV filter advertises. Repeated keys and commas may mix. An
  empty part, `?ids=3,,5`, is kept, so `coerce_flat` refuses it at its index as
  it refuses any malformed element.
- **A string array splits only where its choices hold no comma**, as an
  ordering's do, so django-filter's `?o=title,-pk` is `["title", "-pk"]`.
  Otherwise a comma is part of the string, and the value is taken whole.
- **An array is read no further than one element past the most it takes**, its
  `max_length` or the `SERVICE_SPECS_MAX_ARRAY_LENGTH` default, so `coerce_flat`
  still refuses the list at its name, and a value of a million commas never
  becomes a million elements. Django's `DATA_UPLOAD_MAX_NUMBER_FIELDS` counts
  keys, and a comma list is one key.
- **A blank value is absent unless `""` is one the parameter can take.** A plain
  string and an `any` can; a number, a boolean, a date, a decimal, and a string
  whose choices leave the blank out cannot. A flat wire has no other way to say
  "left blank", and a filter form's empty date input is not a malformed date.
  Each blank element of an array is read the same way, and an array with
  nothing left is absent.
- **Django's `csrfmiddlewaretoken` is dropped**: it is the field
  `{% csrf_token %}` renders into a form, and no Django transport takes it as an
  argument.
- **A key the parameters do not declare is kept as it is**, so the closed
  argument set in [`check_arguments`](arguments.md#the-closed-argument-set)
  stays the one place that refuses it, under the caller's policy.

`flat_arguments` is an opt-in module: the transports reading a flat wire share
it, and nothing `dispatch` or the registry runs imports it.
