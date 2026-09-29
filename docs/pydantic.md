# The pydantic adapter

[`PydanticValidator`][django_service_specs.adapters.pydantic.pydantic_validator.PydanticValidator]
and
[`PydanticPresenter`][django_service_specs.adapters.pydantic.pydantic_presenter.PydanticPresenter]
let a pydantic model declare an operation's input and its output. The model
does what it does for any other caller - builds the instance, runs its own
validators, dumps itself as JSON - and the adapter reads the model's fields into
the kernel's `Parameters` and `Output`, so a transport describes the operation
exactly as it describes one declared with the
[dataclass adapter](declaring.md#the-dataclass-adapter).

## Installing

pydantic is an optional extra:

```bash
pip install "django-service-specs[pydantic]"
```

The package root never imports pydantic, so nothing changes for a project that
does not install it. The adapter is imported from its own subpackage, and is
the only thing that needs the extra:

```python
from django_service_specs.adapters.pydantic import PydanticPresenter, PydanticValidator
```

## Declaring with models

The nested write from [Relations](relations.md), declared as models:

```python
--8<--
docs/examples/pydantic_adapter.py:write
--8<--
```

`validate()` returns the values keyed by field name, with nested values left as
model instances, which is what
[`create_from_input`][django_service_specs.mutations.create_from_input.create_from_input]
reads a row from. The presenter reads the author and its prefetched books
through the related manager, validates what it read with `AuthorOut`, and
returns `model_dump(mode="json", by_alias=True)`.

## What a model declares

A model's fields are read as the dataclass adapter reads a dataclass's, from
the same table, so a model and a dataclass declaring the same field declare the
same parameter:

| Annotation | Declares |
| --- | --- |
| `str`, `int`, `float`, `bool` | Their JSON types. |
| `Decimal`, `datetime`, `date` | A `string` with the format it decodes from. |
| `X \| None` | Nullable. |
| `Literal[...]`, an `Enum` (Django's `TextChoices` and `IntegerChoices` included) | Choices. |
| `list[X]` | An array. `list[SomeModel]` is an array of rows, each declared as nested Parameters. |
| a model | An object, with its fields as nested Parameters. |
| `dict[str, X]` | An object with no declared fields. Its values are the model's to validate. |

`Annotated` is looked through, so `Annotated[str, Field(max_length=100)]`
declares a string. Anything else - `Any`, a union of two types, `UnsetType`, a
`RootModel`, `set`, `tuple`, a `dict` not keyed by `str` - is refused with
`ImproperlyConfigured` naming the model and the field, when the validator or
presenter is constructed.

A field is **required** when pydantic says so. Its **default** is declared when
JSON carries it as itself: `3`, `"draft"`, `None`, `[]`. A `default_factory`,
or a default such as a `Decimal` or a date, is not declared, and the field is
optional all the same. The field's `description` is the parameter's `help`.

What `PydanticValidator(AuthorIn)` declares, then, is what
`DataclassValidator` declares for the dataclass `AuthorIn` in
[Declaring an operation](declaring.md#the-dataclass-adapter), with the price's
description as its help: `name`, and an optional array of `books` whose rows
take a `title`, a `price` in the `decimal` format, a `status` with its choices
and default, a nullable `published_on` in the `date` format, and the nullable
`pk` that lets an update match a row. The rule stated there holds here too:
**a row that updates must declare its key.** The title's `max_length` and the
price's `gt` are not declared; see the last section for why.

## Names

A parameter is named for the key pydantic validates by: the field's
`validation_alias` when it is a string, else its `alias`, else its name. An
output field is named for the key `model_dump(by_alias=True)` emits: the
`serialization_alias`, else the `alias`, else the name.

```python
--8<--
docs/examples/pydantic_adapter.py:names
--8<--
```

`Contact` takes `fullName` and `mail`, and outputs `fullName` and `email`.
`validate()` returns `{"full_name": ..., "email": ...}`: the **field names**,
whatever the wire called them, because those are the keywords the service is
called with. A model that sets `validate_by_alias=False` takes its field names.

An `AliasPath` or `AliasChoices` is refused: a parameter has one name, and a
transport must be able to say which.

## A model that contains itself

`Category.children` is a list of `Category`, which has no end. The adapter
describes a model at most four times on one path, the top counting as the
first, and the level past that as an object with no declared fields:

```python
--8<--
docs/examples/pydantic_adapter.py:tree
--8<--
```

The bound is on the **description**, not on the data. The shape check stops
looking at the fourth level, and pydantic validates every level below it, so a
tree ten levels deep is built in full and a bad name ten levels down is refused
at its path. A model that appears twice side by side is described in full both
times: the count is per path.

## Refusals

A refusal keeps pydantic's words, addressed into the kernel's refusal tree, as
[Arguments and refusals](arguments.md#the-refusal-tree) describes it:

- a field is addressed by its parameter name, and a row by its index as an
  `int`: `{"books": {0: {"price": ["Input should be greater than 0"]}}}`;
- a model refusing itself - a `model_validator` raising - is addressed at
  `non_field_errors` inside that model, or at the top for the model being
  validated: `{"books": {1: {"non_field_errors": ["Value error, A published
  book has a publication date."]}}}`.

The kernel's shape check runs first, so a wrong JSON type is refused in the
kernel's words and never reaches the model. pydantic's words are what a caller
reads for the model's own rules: bounds, patterns, validators.

The context reaches pydantic's validators as `info.context`, a dict with
`"principal"` and `"target"`, so a `field_validator` can check a value against
the caller or the row being updated.

## Output

`PydanticPresenter` declares the model's fields in order, then its
`computed_field`s. A field declared `exclude=True` is not output, and a field
with an `exclude_if` is declared as not always present. A field's `title` is
its `label`, and a
[`FieldMarking`][django_service_specs.output.field_marking.FieldMarking] is
declared in its `Annotated` metadata, as `BookOut` does above.

`present(value)` takes an instance of the model, a model row, any object
carrying the fields' names, or a mapping keyed by them. Anything but an
instance is read one field at a time and validated by the model; a related
collection is read through `.all()`, so a prefetch is used, and a field the
value does not carry takes the model's default. A value the model refuses
raises pydantic's `ValidationError` as it is: the value is the operation's own,
so a mismatch is a defect, not a refusal to report.

## Where it differs from the dataclass adapter

- **Nothing is omittable.** `validate()` returns every field, a left-out one at
  its default, and `UnsetType` is refused, because a pydantic model has no
  value that means "not sent". An update whose fields may be left out is
  declared with the dataclass adapter's `X | UnsetType = UNSET`, as
  `AuthorPatch` is.
- **Time zones are pydantic's.** An offset-less date-time stays naive, where
  the dataclass adapter makes it aware as Django's forms do. Declare the
  offset, or convert in the service.

## What `model_json_schema()` is not used for

A transport describes an operation's input from `parameters()`, whichever
adapter declared it, and the model's own JSON Schema is not consulted. There is
one dialect: a `Decimal` is a `string` in the `decimal` format for a model as
for a dataclass, where pydantic's schema describes it as a number or a
patterned string. The price of that is that what `Parameters` cannot carry -
`max_length`, `gt`, a pattern - is not described. It is still enforced, by the
model, in `validate()`.
