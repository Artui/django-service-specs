# django-service-specs

[![CI](https://github.com/Artui/django-service-specs/workflows/tests/badge.svg)](https://github.com/Artui/django-service-specs/actions/workflows/tests.yml)
[![PyPI](https://img.shields.io/pypi/v/django-service-specs.svg)](https://pypi.org/project/django-service-specs/)
[![Python versions](https://img.shields.io/pypi/pyversions/django-service-specs.svg)](https://pypi.org/project/django-service-specs/)
[![Django versions](https://img.shields.io/pypi/djversions/django-service-specs.svg)](https://pypi.org/project/django-service-specs/)
[![Docs](https://img.shields.io/badge/docs-artui.github.io-blue.svg)](https://artui.github.io/django-service-specs/)
[![Coverage](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/Artui/django-service-specs/gh-pages/coverage.json)](https://github.com/Artui/django-service-specs/actions/workflows/tests.yml)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![License](https://img.shields.io/pypi/l/django-service-specs.svg)](LICENSE)

A service contract for Django: declare an operation's parameters, permission
check, validation and output once, and dispatch it from any transport - an HTTP
view, an MCP tool, an agent tool, a management command or a background task.

Django is the base and the only dependency. Django REST Framework is **not a
dependency**, and nothing in the package imports it, so a project with business
logic and no API framework can hand its operations to an agent, a command or a
queue with Django alone.
[`djangorestframework-services`](https://github.com/Artui/djangorestframework-services)
will depend on this package and become its DRF adapter; this package will
never depend on it.

**No agent transport reads a spec without DRF yet.** The family's MCP server
([`djangorestframework-mcp-server`](https://github.com/Artui/djangorestframework-mcp-server))
and its Pydantic AI toolset
([`djangorestframework-pydantic-ai`](https://github.com/Artui/djangorestframework-pydantic-ai))
both require DRF and `djangorestframework-services` today. What a tool-building
transport reads off a spec besides dispatch - affordances, paging, the agent
projection of an output, progress - is here, and those transports are planned
to read kernel specs through it, with DRF behind an extra, once
`djangorestframework-services` is this package's DRF adapter. Until then a
project without DRF can dispatch its specs from its own views, commands, tasks
and agent tools, and no ready-made MCP server or agent toolset serves them.

**Status:** early. The public API may still change between minor releases,
and every change is recorded in the [changelog](CHANGELOG.md).

## Install

```bash
pip install django-service-specs
```

The package has no models and needs no entry in `INSTALLED_APPS`. A principal
is a user of `django.contrib.auth`, and a generic-relation write needs
`django.contrib.contenttypes`. Django 4.2 or later, on Python 3.10 or later.

The pydantic adapter is the one part that needs more, and it comes with an
extra:

```bash
pip install "django-service-specs[pydantic]"
```

## Quickstart

One write, declared once: what it takes (a dataclass behind a `Validator`),
which row it acts on (an instance selector), who may run it
(`permissions=[...]`), and what it returns (a `Presenter`). `Note` is a model
with a `title` and an `owner` who is a user.

```python
from dataclasses import dataclass
from typing import Any

from django_service_specs import (
    DataclassPresenter,
    DataclassValidator,
    Parameter,
    Parameters,
    PermissionCheck,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    dispatch,
    present,
)
from notes.models import Note  # a title, and an owner who is a user


@dataclass
class Rename:  # what the operation takes
    title: str


@dataclass
class NoteOut:  # what it returns
    id: int
    title: str


class IsOwner(PermissionCheck):
    message = "Only the note's owner may rename it."

    def has_permission(self, principal: Any, spec: Any) -> bool:
        return principal.is_authenticated

    def has_object_permission(self, principal: Any, spec: Any, target: Any) -> bool:
        return target.owner_id == principal.pk


def rename_note(*, instance: Note, title: str) -> Note:
    instance.title = title
    instance.save(update_fields=["title"])
    return instance


rename_note_spec = ServiceSpec(
    service=rename_note,
    permissions=[IsOwner()],
    validator=DataclassValidator(Rename),
    instance_selector_spec=SelectorSpec(
        kind=SelectorKind.RETRIEVE,
        selector=lambda *, pk: Note.objects.filter(pk=pk),  # the row, or none
        reads=Parameters.of(Parameter("pk", "integer", required=True)),
    ),
    presenter=DataclassPresenter(NoteOut),
)


def rename(user: Any, arguments: dict[str, Any]) -> Any:
    result = dispatch(rename_note_spec, principal=user, arguments=arguments)
    if result.kind == "not_found":
        return None  # a transport answers this in its own terms: a 404, an exit code
    return present(rename_note_spec, result)
```

`rename(user, {"pk": 1, "title": "Final"})` returns `{"id": 1, "title": "Final"}`
for the note's owner, `None` when there is no note 1, and raises `NotPermitted`
for anyone else. The same `rename_note_spec` can be dispatched from an HTTP
view, an MCP tool, a management command or a task: each supplies a principal
and the arguments, and answers the result in its own terms; over HTTP,
`SpecView.as_view(spec=rename_note_spec)` is that view. This code is
`docs/examples/quickstart.py`, where `Note` comes from the test suite's own
app, and the test suite runs it.

## The order dispatch runs in

`dispatch()` and `adispatch()` take the same steps, in the same order, for a
write and a read:

1. **Shape check and closed argument set.** Every argument against the declared
   parameters, at every level of nesting, with no query.
2. **Class-level authorization.** Every permission check's `has_permission`,
   before any row is resolved, so a refused principal learns nothing about
   which rows exist.
3. **Target resolution.** The selector finds the row or rows. A missing row is
   returned as `DispatchResult(kind="not_found")`, never raised.
4. **Object-level authorization.** `has_object_permission` on a retrieved row.
5. **Validation.** The Validator, with the resolved row in its context, so an
   update's uniqueness check can exclude the row being updated.
6. **The run.** The service, inside `transaction.atomic()` unless the spec
   says `atomic=False`, then the output selector if one is declared.

A read stops after step four: its selector is its run.

`present()` renders the result afterwards, and only when the transport asks,
so one that hands the row to a template never pays for rendering it.

## What it refuses

| Refused | Raised | Who refused |
| --- | --- | --- |
| An argument of the wrong type, missing, or not declared | `InvalidArguments`, with every problem in `.detail` | Dispatch |
| Arguments the Validator rejects | `InvalidArguments` | Dispatch |
| A permission check says no, or a `Grant` does not cover the call | `NotPermitted` | Dispatch |
| An identifier that names no active user | `PrincipalUnavailable` | Dispatch |
| A business rule, raised by the service | `ServiceError`, `ServiceValidationError`, `ServiceConflict`, `ServiceNotFound` | The operation |
| A required row that does not exist | Nothing: `DispatchResult(kind="not_found")` | - |
| An operation that declares no permission check | `ImproperlyConfigured`, at registration and at dispatch | Configuration |

The first four share the base `DispatchError`; the service's own share
`ServiceError`. **Neither subclasses the other.** A consumer reads a service
refusal as something the caller adapts to - an agent routes around it and
keeps going - so a denial declared as one becomes something a model retries.
And an MCP server tells arguments of the wrong shape from a business rule on
well-shaped ones by exactly this type difference.

An operation that is open to anyone says so with `permissions=[Unrestricted()]`.
Off HTTP there is no view whose policy it could inherit, so leaving the list
out is refused rather than read as "no restriction".

## Documentation

[artui.github.io/django-service-specs](https://artui.github.io/django-service-specs/):

- [Declaring an operation](https://artui.github.io/django-service-specs/declaring/) - specs, Parameters, Validators, Output and Presenters
- [Dispatching](https://artui.github.io/django-service-specs/dispatching/) - the order, results, grants, the async rule and pool seeds
- [Serving over HTTP](https://artui.github.io/django-service-specs/http/) - a spec as a Django view answering JSON, and the status of each refusal
- [Arguments and refusals](https://artui.github.io/django-service-specs/arguments/) - the shape check, the error tree and the two error families
- [Affordances](https://artui.github.io/django-service-specs/affordances/) - when an operation is possible right now, its refusal's stable code, and asking for one more value
- [Relation writes](https://artui.github.io/django-service-specs/relations/) - nested writes through the five relation specs
- [The registry](https://artui.github.io/django-service-specs/registry/) - one named set of operations for several transports
- [The forms adapter](https://artui.github.io/django-service-specs/forms/) - a Django form class as the Validator, `ModelForm` included
- [The pydantic adapter](https://artui.github.io/django-service-specs/pydantic/) - a pydantic model as the Validator and the Presenter
- [JSON Schema](https://artui.github.io/django-service-specs/schema/) - the input and output schema a transport describes an operation with
- [API reference](https://artui.github.io/django-service-specs/reference/)

## License

MIT
