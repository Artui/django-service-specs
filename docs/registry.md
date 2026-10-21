# The registry

A project that exposes its operations over more than one transport - an MCP
server and a command line, say - needs one place that says which operations
exist and what they are called, or each transport enumerates specs for itself
and they drift.
[`SpecRegistry`][django_service_specs.registry.spec_registry.SpecRegistry] is
that place: a `name -> spec` map with tags, in registration order, from which
each transport takes the view it exposes.

```python
--8<--
docs/examples/registry.py:registry
--8<--
```

## What an entry holds

Each entry is a
[`RegisteredSpec`][django_service_specs.registry.registered_spec.RegisteredSpec]:
a canonical `name`, the `spec`, and a frozen set of `tags`. That is only the
part of an operation that is the same on every transport. An HTTP route's URL
kwargs, an MCP tool's annotations and an agent adapter's own metadata stay at
the binding that configures them.

Tags are free-form labels for facts every transport can read in its own
vocabulary: `"read"`, `"admin"`, `"destructive"`. Whether an entry is a read or
a write is not a tag and not a field; it is read off the spec itself, so a
stored label can never disagree with the object it describes.

## A declaration of another library's

The `spec` may also be any object with an `as_kernel_spec()` method, a
[`SpecSource`][django_service_specs.specs.spec_source.SpecSource]:
djangorestframework-services' spec is one, and so is every `ServiceSpec` and
`SelectorSpec`, each compiling to itself. It is registered as it is, with no
wrapper, and kept as registered, so `entry.spec` and `specs()` hand back the
object itself. `dispatch`, `adispatch`, `check_call`, `bind_arguments`,
`present`, `apresent`, `present_for_audience`, `resolve_target`, the three
`authorize` functions, the affordance functions and their async twins,
`server_owned_keys`, `check_requested_input`, `shape_queryset`,
`spec_input_schema`, `spec_output_schema`, `can_present_nothing` and
`audience_projection_for_spec` take it as they take a spec, and
[`kernel_spec`][django_service_specs.specs.kernel_spec.kernel_spec] is how a
transport reads the spec it compiles to anywhere else. It is compiled the
first time anything reads it, and that compiled spec answers every later call
for the same object.

A [`Grant`][django_service_specs.dispatch.grant.Grant] compares specs as
compiled, so a transport that authorizes the object it holds and mints a grant
from it can dispatch that object or the spec it compiles to under the same
grant. Each permission check is asked about the compiled spec, the same object
`dispatch` hands it for that declaration.

The entry answers a read-only `agent_contract`: the registered object's own
`agent_contract()` when it has one, and `None` otherwise, which is every
`ServiceSpec` and `SelectorSpec`. It is asked, never passed: `register()` takes
no `agent_contract=`.

```python
--8<--
docs/examples/registry.py:source
--8<--
```

## Registering

`register(name, spec, tags=...)` adds one entry, and refuses three mistakes
where they are written, at import time:

- **A name already in this registry** raises `ValueError`, so a copy-pasted
  declaration fails instead of shadowing an operation.
- **Something that is not a `ServiceSpec` or a `SelectorSpec`, nor compiles
  to one,** raises `TypeError`, naming the registration.
- **A spec with no permission check**, whether declared here or compiled from
  another library's declaration, raises `ImproperlyConfigured`. Dispatch
  would refuse it on every call, and finding out at the first call is later
  than finding out at startup. An operation that is open says so with
  `permissions=[Unrestricted()]`.

## Open specs, reported

A registry refuses a spec that declares no check, and a spec refuses an empty
`permissions`, so every registered spec declares at least one. What still
reaches a registry open to every principal is a spec whose checks are all
`Unrestricted`, a subclass of it included. One real check beside an
`Unrestricted()` guards the spec, because every check must pass.

`unguarded_specs(registry)` lists those entries, in registry order, each as an
`UnguardedSpec` carrying its name and an `UnguardedReason`. An entry is judged
by the spec it compiles to, the one dispatch runs, so a declaration of
another library's is read through what it compiles to rather than through
checks of its own.

The fact is the registry's, and the sentence reporting it is a transport's,
since it names the command an operator types, which the registry does not
know. The management command's `--explain` and the system check that warns
once per open spec a command serves, `django_spec_cli.W001`, are
[django-spec-cli's](https://artui.github.io/django-spec-cli/#open-specs-explain);
its check runs when `"django_spec_cli"` is in `INSTALLED_APPS`. This package
registers no system check, so listing `"django_service_specs"` reports
nothing.

Reporting is the whole of it: `unguarded_specs` refuses nothing, and is no
authorization boundary. It makes the declaration visible to whoever reads
the report.

## Reading it

| Call | Returns |
| --- | --- |
| `get(name)` | The entry, or `None` |
| `all()` | Every entry, in registration order |
| `queries()` | The `SelectorSpec` entries, in registration order |
| `mutations()` | The `ServiceSpec` entries, in registration order |
| `specs()` | A new `{name: spec}` dict, the shape a transport that takes a mapping of specs accepts |
| `name in registry`, `len(registry)`, iteration | As for a mapping of entries |

Registration order is kept so that a transport's listing - a tool list, a help
screen - comes out the same on every start.

## Views

Four calls derive a new registry from an existing one:

- **`by_tag(*tags)`** keeps the entries carrying **any** of the tags. It is a
  union; chain the calls for an intersection:
  `registry.by_tag("catalogue").by_tag("write")`. No tags keeps nothing.
- **`subset(*names)`** keeps the named entries, **in the order named**. A name
  that is not registered raises `KeyError`: a typo is a configuration error,
  not a quietly smaller surface.
- **`merge(*others)`** combines registries, in order. Names are unique within
  one registry, so two independent registries may each use a name; merging is
  where that becomes a conflict, and it raises `ValueError`.
- **`replace(name, spec)`** puts `spec` under `name` in place of the spec
  registered there. The entry keeps its tags and its place in the order, and
  the replacement is checked as `register` checks a spec. A name that is not
  registered raises `KeyError`, since a replacement for an operation nobody
  registered is a typo rather than a registration.

`replace` is how a transport serves a variant of an operation without a second
name for it. The registry holds what every transport shares; a variant shaped
for one transport is the registered spec's own
[`derive(...)`](declaring.md#a-variant-of-a-spec), in the registry that
transport is handed:

```python
--8<--
docs/examples/registry.py:replace
--8<--
```

`search_only` is the variant
[derived from `list_notes_spec`](declaring.md#a-variant-of-a-spec).

Every view is a **snapshot**. It shares the spec objects rather than copying
them, it never changes its source, and a `register()` on the source afterwards
does not appear in a view taken before it. A transport reads its view once, at
configuration time, to build its own table of operations; nothing reads a
registry per dispatch.

There is **no global registry**. A project holds as many registries as it has
reasons to, with no state shared between them, and passes each transport the
one it should expose.
