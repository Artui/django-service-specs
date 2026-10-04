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

## Two positions

Everything else follows from two decisions, and both read as limitations.

**Django is the base, and the only one.** There is no pure-Python protocol
layer beneath the kernel and no Django-free subpackage inside it. A principal
is a Django user, a target is a model row, a transaction is Django's. The
package depends on Django and nothing else.

**DRF is an adapter, never a dependency.** The package exists so a Django
project with business logic and no API framework can hand its operations to an
agent, a command or a queue. Nothing in `django_service_specs` imports
`rest_framework`, and the test suite runs without it installed.
[`djangorestframework-services`](https://github.com/Artui/djangorestframework-services)
will depend on this package, never the reverse, with its own `ServiceSpec`
becoming the DRF adapter over this kernel.

**No agent transport reads a spec without DRF yet.** The family's MCP server and
Pydantic AI toolset both require DRF and `djangorestframework-services` today.
What they read off a spec besides dispatch is here - see
[affordances](affordances.md) and [paging and projection](paging-and-projection.md) -
and they are planned to read kernel specs through it, with DRF behind an extra,
once `djangorestframework-services` is this package's DRF adapter. Until then a
project without DRF dispatches its specs from its own views, commands, tasks
and agent tools.

## Install

```bash
pip install django-service-specs
```

The package has no models and needs no entry in `INSTALLED_APPS`. A principal
is a user of `django.contrib.auth`, and a generic-relation write needs
`django.contrib.contenttypes`.

| | Minimum |
| --- | --- |
| Python | 3.10 |
| Django | 4.2 |

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
- [Dispatching](dispatching.md): the seven steps, results, grants, the async
  entry point, and pool seeds.
- [Serving over HTTP](http.md): a spec as a Django view, answered as JSON:
  the arguments a request carries, the principal, and the status of each refusal.
- [Arguments and refusals](arguments.md): the shape check, the error tree, flat
  transports, and the two error families.
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
