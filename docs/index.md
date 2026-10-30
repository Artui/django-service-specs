# django-service-specs

A service contract for Django. An operation is declared once - what it takes,
who may run it, how its arguments are validated, what it returns - and any
transport dispatches it: an HTTP view, an MCP tool, an agent tool, a management
command, a background task.

Each transport would otherwise restate the operation in its own terms: a
serializer for the view, a JSON Schema for the tool, argparse options for the
command, and a permission check in whichever of them remembered one. Declared
once, the operation carries all of that itself, and a transport reads the
declaration rather than repeating it.

## Two positions, three layers

Everything else follows from two decisions, and both read as limitations.

**Django is the base, and the only one.** There is no pure-Python protocol
layer beneath the kernel and no Django-free subpackage inside it. A principal
is a Django user, a target is a model row, a transaction is Django's. Django
is the only framework the package depends on, and `typing_extensions` its only
other dependency.

**DRF is an adapter, never a dependency.** The package exists so a Django
project with business logic and no API framework can hand its operations to an
agent, a command or a queue. Nothing in `django_service_specs` imports
`rest_framework`, and the test suite runs without it installed.

On that base the package is in three layers. Every subpackage is classified
into one, and a test fails if core imports anything classified outside it:

- **Core** is what every transport needs to run a spec: the declaration, the
  [registry](registry.md) and [dispatch](dispatching.md), with authorization
  always on, because dispatch always authorizes. It is what dispatch and the
  registry import, and nothing more.
- **Opt-in modules** are subpackages core never imports: model writes,
  [relation writes](relations.md) and the [schema](schema.md) projection.
  Opt-in is a classification, not a switch. No setting turns a module on or
  off; a spec that uses none of them dispatches without them. The validator
  adapters for dataclasses, [forms](forms.md) and [pydantic](pydantic.md) sit
  outside core the same way, as libraries a project writes against.
- **A transport only wires** a protocol onto specs and dispatch, and belongs in
  a distribution of its own. The [HTTP views](http.md) are
  [django-spec-html](https://artui.github.io/django-spec-html/) and the
  [management command](commands.md) is
  [django-spec-cli](https://artui.github.io/django-spec-cli/).

**Where the transports stand.**
[`djangorestframework-services`](https://github.com/Artui/djangorestframework-services)
depends on this package, never the reverse: its `ServiceSpec` is the DRF
adapter over this kernel. The family's MCP server and Pydantic AI toolset reach
specs through it today, so both still require DRF. What they read off a spec
besides dispatch is here - see [affordances](affordances.md) and
[paging and projection](paging-and-projection.md) - and transport
distributions that read kernel specs with no DRF at all are planned. Until then
a project without DRF dispatches its specs from its own views, commands, tasks
and agent tools.

## Install

```bash
pip install django-service-specs
```

The package has no models and runs with no entry in `INSTALLED_APPS`. A
principal is a user of `django.contrib.auth`, and a generic-relation write needs
`django.contrib.contenttypes`. List `"django_service_specs"` there for its
[translations](#translations) to load; it registers nothing else, and the system
check reporting every spec a management command serves that
[authorizes nothing](registry.md#open-specs-reported) is django-spec-cli's.

```python
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django_service_specs",
    # ...
]
```

| | Minimum |
| --- | --- |
| Python | 3.10 |
| Django | 4.2 |

## Translations

A refusal reads in the language active where it is raised. Each refusal type's
`default_message` is a msgid, looked up with `gettext` each time a refusal is
built with no message of its own, so nothing is fixed at import; a message the
caller passes, `NotPermitted("Ask the owner.")`, is shown as given. Where DRF has the same message the msgid is DRF's (`Not found.`, and
its `ListField`'s two length messages), so a project with DRF installed keeps
DRF's translation of those three.

The package ships its source catalog,
`django_service_specs/locale/en/LC_MESSAGES/django.po`: every msgid it marks,
untranslated, which is what a contributed language starts from. It ships no
translated language. Django loads a catalog only from an app in
`INSTALLED_APPS` or from a directory in `LOCALE_PATHS`, so a language
compiled beside that file loads once `"django_service_specs"` is listed.

### Keeping one catalog

A project that keeps every translation in its own catalog, under
`LOCALE_PATHS`, cannot have `makemessages` collect these msgids: it reads the
project's source and never `site-packages`, and it marks each msgid it did not
find there obsolete. So combine the template it writes with the package's
catalog, and merge that into each language, after every `makemessages` run and
every upgrade of this package:

```bash
KERNEL_PO="$(python -c 'import importlib.util, pathlib; print(pathlib.Path(importlib.util.find_spec("django_service_specs").origin).parent / "locale/en/LC_MESSAGES/django.po")')"
django-admin makemessages --locale de --keep-pot
msgcat --use-first locale/django.pot "$KERNEL_PO" --output-file locale/django.pot
msgmerge --update --backup=none locale/de/LC_MESSAGES/django.po locale/django.pot
django-admin compilemessages --locale de
```

`msgmerge` brings back each translation the `makemessages` run had marked
obsolete, so a msgid translated once stays translated. `--use-first` keeps the
project's own header and, for a msgid both catalogs hold, the project's entry.

## Quickstart

A write that renames a note. `Note` is a model with a `title` and an `owner`
who is a user; the examples on these pages import their models from the
package's own test suite, which is where they run.

```python
--8<--
docs/examples/quickstart.py:quickstart
--8<--
```

What each part is:

- **`Rename`**, wrapped in [`DataclassValidator`][django_service_specs.adapters.dataclass.dataclass_validator.DataclassValidator],
  declares what the operation takes. A transport reads the declaration as
  [`Parameters`][django_service_specs.parameters.parameters.Parameters] to
  describe itself - a JSON Schema, argv options - and dispatch validates the
  arguments against it.
- **The instance selector** finds the row the service acts on, from the `pk`
  argument its `reads` declare. A missing row is reported as not-found and the
  service never runs.
- **`IsOwner`** is a [`PermissionCheck`][django_service_specs.authorization.permission_check.PermissionCheck]:
  `has_permission` runs before any row is looked up, `has_object_permission`
  on the row once it is.
- **`rename_note`** is the service. It is called with the keywords it declares
  and nothing else: the resolved row as `instance`, and each validated value by
  name.
- **`NoteOut`**, wrapped in [`DataclassPresenter`][django_service_specs.adapters.dataclass.dataclass_presenter.DataclassPresenter],
  declares what comes back and renders it, reading each field off the row by
  attribute.

`rename(owner, {"pk": 1, "title": "Final"})` returns `{"id": 1, "title": "Final"}`.
For another user it raises [`NotPermitted`][django_service_specs.authorization.not_permitted.NotPermitted],
and for a note that does not exist it returns `None`, because
[`dispatch`][django_service_specs.dispatch.dispatch.dispatch] reports a missing
row as `kind="not_found"` rather than raising: an HTTP view answers it with a
404, a command with an exit code, a tool with an error result.

## Where to go next

- [Declaring an operation](declaring.md): the two spec types, Parameters, the
  Validator contract and its dataclass adapter, Output and the Presenter.
- [Dispatching](dispatching.md): the seven steps, results, grants, a target
  resolved ahead of the call, the async entry point, and pool seeds.
- [Arguments and refusals](arguments.md): the shape check, the error tree, flat
  transports, and the two error families.
- [Reading a flat source](flat.md): a query string or a form's fields, read by
  the declaration before `coerce_flat` types it.
- [Affordances](affordances.md): when an operation is possible right now, the
  refusal's stable code, offering only what a call could pass, and asking for
  one more value.
- [Relation writes](relations.md): writing a row and its related rows in one
  operation.
- [The registry](registry.md): one named set of operations for several
  transports.
- [The forms adapter](forms.md): a Django form class, `ModelForm` included,
  as the Validator.
- [The pydantic adapter](pydantic.md): a pydantic model as the Validator and
  the Presenter, with the `pydantic` extra.
- [JSON Schema](schema.md): the input and output schema a transport
  describes an operation with.
- [Paging and projection](paging-and-projection.md): a list served a page at
  a time, and each row shaped for an agent reading it.
- [API reference](reference.md): every public name.
