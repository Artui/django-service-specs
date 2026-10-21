# The forms adapter

[`FormValidator`][django_service_specs.adapters.forms.form_validator.FormValidator]
makes a Django form class a
[`Validator`][django_service_specs.validation.validator.Validator]. The form
you already have - its fields, their validators, `clean_<field>()`, `clean()`
and, on a `ModelForm`, the model's own validation and uniqueness checks - is
what validates the arguments, and the adapter reads its fields into the
`Parameters` every transport describes itself from.

It needs nothing beyond Django, so like the dataclass adapters it is exported
from the package root:

```python
from django_service_specs import FormValidator
```

There is no presenter: a form describes what goes in, not what comes out.

To serve the form as a page,
[django-spec-html](https://artui.github.io/django-spec-html/pages/)'s `SpecFormView` renders it,
dispatches the post and re-renders it with what dispatch refused. A host's own
view does the same with
[a refusal, placed on a form](https://artui.github.io/django-spec-html/http/#a-refusal-placed-on-a-form).

## A form as a Validator

```python
--8<--
docs/examples/forms_adapter.py:form
--8<--
```

What `book_validator.parameters()` declares, then, in the form's own order:
`title`, a required string with the help text as its `help`; `price`, a
required string in the `decimal` format; `status`, a required string with the
choices `draft` and `published`; `published_on`, an optional, nullable string
in the `date` format; `author`, a required integer, because authors are matched
on their primary key; and `shelves`, an optional array of strings whose every
element is one of `fiction` and `poetry`.

`validate()` binds the arguments to a new `BookForm` and returns its
`cleaned_data`: a `Decimal` for the price, a `date`, the `Author` row itself
for `author`. The rule `clean()` states is the form's to enforce, and its
message comes back about the whole call:
`{"non_field_errors": ["A published book needs its publication date."]}`.

The form is read when `FormValidator` is built, so a field it cannot describe
fails on that line, naming the form, the field and the field's class. Nothing
in the reading queries: a `ModelChoiceField`'s rows are never listed. The one
thing read later is `help_text`, on each `parameters()` call, so a lazily
translated help text is in the caller's language rather than whichever was
active at import.

## What each field declares

The first match wins, so a subclass is read as the most specific field it
extends.

| Field | Declares |
| --- | --- |
| `BooleanField`, `NullBooleanField` | A `boolean`. |
| `DecimalField` | A `string` in the `decimal` format. It takes a JSON number too, and an integer whatever its digits. |
| `FloatField` | A `number`. An integer past a float's range is refused as the field refuses an infinity: `invalid`, in its own words. |
| `IntegerField` | An `integer`. |
| `DateTimeField`, `DateField` | A `string` in the `date-time` or `date` format. |
| `TimeField`, `DurationField` | A `string`. |
| `ChoiceField` | A `string` with the choices as strings, since a plain choice field cleans with `str` and compares against each choice's `str`. The empty choice is dropped and option groups are flattened. |
| `TypedChoiceField` | Choices, of the JSON type every value shares. Values of mixed types, or of a type JSON does not have, are refused. |
| `MultipleChoiceField`, `TypedMultipleChoiceField` | An `array` of the same, whose choices constrain each element. No choice field declares a length, so the `SERVICE_SPECS_MAX_ARRAY_LENGTH` setting bounds every list one takes. |
| `ModelChoiceField` | The JSON type of the model field rows are matched on - `to_field_name`, or the primary key - and no choices: they are rows, and listing them would query. It validates to the row. |
| `ModelMultipleChoiceField` | An `array` of the same, so one matching rows on a `DecimalField` declares the `decimal` format for each element and `?rows=12.50,9.99` is two of them. Django matches each against the column's own spelling, `"12.50"` and not `12.5`. It validates to a queryset. |
| `FileField`, `ImageField` | A `file`, which a multipart request carries and a Python caller hands as a Django `File`. The form is bound with it as its `files`, where a file field reads, and its own checks run on it. An optional one also declares its [clear checkbox](#clearing-a-file). |
| any other `CharField` (`EmailField`, `URLField`, `SlugField`, `UUIDField`, `RegexField`, `GenericIPAddressField`) | A `string`. |

A key past the range of the integer column rows are matched on names no row,
so either field refuses it as it refuses a key no row holds: `invalid_choice`,
in its own words, beside the form's other refusals. The adapter answers it
before the form queries, because Django hands a `ModelMultipleChoiceField`'s
keys to the database driver in an `__in` lookup, and SQLite's raises
`OverflowError` for one past 64 bits on every Django version, as it does for a
`ModelChoiceField`'s on Django 4.2. The range is the database's own for the
column, as Django reads it to answer an exact lookup past it with no rows, and
a key sent as a string of digits is the integer it spells.

A `ModelForm` value past the range of its model's integer column is refused in
the words, and with the code, of the validator Django's model field carries
from 5.0: `max_value` past its top, `min_value` past its bottom. Django 4.2
states no range for SQLite, so there the form took such a value, and a
uniqueness check or a constraint querying with it raised the driver's
`OverflowError`. The value is judged where Django 5.0 and later judge it: after
the form field, its `clean_<field>()` and the form's `clean()`, on what they
hand back, read as the model reads it, so digits a text field cleans to are
the integer they spell. So a value the field refuses is refused in the field's
words, its own bounds included, a `clean_<field>()` refusing it is reported in
its own words, and one that brings the value inside the range has it taken.
Only a column Django validates is judged, the ones it does not leave out of
the model's checks: a value `clean()` sets in `cleaned_data` for a column the
form has no field for, and a field the form declares over a column
`Meta.fields` leaves out or `Meta.exclude` names, are never written onto the
row by the form, and are the form's to use, whatever their size.

Every choice field's choices carry their labels as `choice_labels`, the label
Django displays keyed by the value as the caller sends it, so a schema states
each as a `title`. A choice set given as a callable is computed per form and
may query, so it is not read: the field is declared as a `string` with no choices, which every
choice field accepts, and the form checks the choice when it validates.

Refused, with `ImproperlyConfigured`:

- `JSONField`: it takes any JSON value, and a parameter declares one type.
- `MultiValueField`, such as `SplitDateTimeField`: it is cleaned from several
  widget values at once, which only an HTML form sends. Declare a field per
  value.
- `ComboField`: it has no JSON type of its own.
- A `ModelChoiceField` with no queryset, since there is no model to read its
  key from, or one matching rows on a model field with no JSON type.
- Any field class the table does not cover, a project's own included.

## Presence, null and defaults

The Parameters say what the form does about presence and `null`, so on
those the shape check in front of it never refuses what the form would take.

- **`required` is the field's own.** For a `BooleanField` that is a statement
  about presence too: an absent checkbox cleans to `False`, which a required
  one refuses exactly as it refuses `false`. A `NullBooleanField` is never
  required, whatever it says: its validation is empty, and it takes an absent
  value as `None`.
- **`nullable` is `not required`**, and always true for a `NullBooleanField`.
  A form reads `None` as an empty value for every field, so an optional field
  takes `null` and cleans it to its empty value - `""` for a string, `None`
  for a number or a row, `[]` for a multiple choice - and a required one
  refuses it. The shape check and the form agree on it field for field.
- **There is no `default`.** A field's `initial` is what an unbound form
  displays; a bound form cleans an absent optional field to its empty value,
  never to its initial.

**The types are JSON's, and do not cross.** A form reads its data as an HTML
post's strings, so it also takes a value of another type through `str` - a
number for a `CharField`, `1` for the choice `"1"`. The shape check refuses
one, as it does for any declaration: a caller sends the declared type. The
empty choice is the other case. An optional choice field reads `""` as no
value, and a caller says that with `null`.

## Declare the fields on the class

The adapter reads `base_fields`: the fields the class declares. A field the
form adds or changes in its own `__init__` is not described, and under
[`UnknownArguments.REJECT`][django_service_specs.types.unknown_arguments.UnknownArguments],
the default, the closed argument set refuses its key before the form is ever
built. A field declared `disabled` is not a parameter either: a form ignores
what a caller sends for it and cleans its `initial`, which `validate()`
returns with the rest.

The form is built from the arguments alone - `data=`, and `instance=` for a
`ModelForm` - so a form whose `__init__` requires anything more, such as the
signed-in user, cannot be used as it is.

## Partial updates

On a [`partial`](declaring.md#partial-updates) spec's call, every field the
arguments do not name is taken off the bound form before it validates, so it
is neither required nor cleaned, and `validate()` returns no key for it: an
absent `BooleanField` does not come back `False`, nor an absent `CharField`
`''`, which an update would write over the row. A value that is sent is
checked exactly as on a whole call, so a required field may be left out but
not sent empty. On a `ModelForm` the fields left out keep the target's
values, and each one's own model check skips them. Its uniqueness checks and
constraints do not: they run over the row as it would be saved, what was sent
on top of the target's values, and leave out only the model fields the form
never declares, as a whole call does. An update that sends one field of a
`unique_together` pair or a `UniqueConstraint` and collides is refused as the
whole call would be, under `non_field_errors`, rather than failing with an
`IntegrityError` when the row is saved. That needs a target row: a partial
call with none checks only what was sent. `clean()` sees only
what was sent, so it reads `cleaned_data` with `get`. The parameters are the
same for both calls: `required` says what a whole call needs.

## Clearing a file

Django clears an optional file through its widget's clear checkbox, which a
`ClearableFileInput` - the default widget of a `FileField` and an
`ImageField` - posts beside the file as `<name>-clear`. The adapter declares
that checkbox as a parameter of its own, a `boolean` right after the file, so
the closed argument set, the shape check and the schema all know it. A
`ModelForm` over `title`, an `attachment` declared `blank=True` and a
required `scan` declares `title`, `attachment`, `attachment-clear` and
`scan`, in that order.

It is the only way a caller clears a file: `null` keeps the file the row
holds, as a form reads no data beside an initial value, and `false` is
refused as not a file.

- **Checked with no upload**, the form cleans the field to `False`, its own
  value for a cleared file. `validate()` returns it under the field's name,
  `{"attachment": False}`, and nothing under the checkbox's. A `ModelForm`
  writes it as no file through the model field's `save_form_data`, and so do
  the [mutation helpers](relations.md#the-helpers): a service handing the
  validated values to `update_from_input(row, data)` clears the file with no
  more code.
- **Unchecked**, or absent, the file is kept.
- **Checked beside an upload**, the form refuses the pair under the field's
  name, in its own words.
- **On a partial call**, a checked checkbox sends its file field, so
  `{"attachment-clear": true}` alone clears the file; an unchecked one is
  what an absent one is, and leaves the field out.

A required file field has no checkbox, since its widget never reads one, and
neither has a file field whose widget is not a `ClearableFileInput`. A form
field already named as a checkbox would read the same argument, so it is
refused when the Validator is built.

## A ModelForm behind an update

```python
--8<--
docs/examples/forms_adapter.py:model_form
--8<--
```

Dispatch resolves the row before it validates, and hands it to the Validator
in the
[`ValidationContext`][django_service_specs.validation.validation_context.ValidationContext].
When the target is a row of the form's model, the form is built with
`instance=` set to **a copy of it**, so its uniqueness check excludes the row
being updated: renaming `ada` to `ada` is not a clash, and renaming her to
`bob` is refused in the form's own words,
`{"username": ["A user with that username already exists."]}`.

It is a copy because a `ModelForm` writes the cleaned values onto its instance
as it validates. Handed the target itself, it would change the row the service
receives before the service runs, and
[`update_from_input`][django_service_specs.mutations.update_from_input.update_from_input],
which saves only the fields whose value changed, would find nothing to save.
Any other target - the queryset a collection selector resolves, or none for a
create - builds the form as a create.

## Refusals

A refusal is one
[`InvalidArguments`][django_service_specs.parameters.invalid_arguments.InvalidArguments]
carrying the form's own errors and messages, `{field: [messages]}`. The
messages about the whole form, which Django keeps under `"__all__"`, are
moved to `non_field_errors`: the key every other refusal in the kernel uses,
so a transport reads a form's refusal as it reads any other. See
[Arguments and refusals](arguments.md) for the tree.
