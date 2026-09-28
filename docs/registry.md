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

## Registering

`register(name, spec, tags=...)` adds one entry, and refuses three mistakes
where they are written, at import time:

- **A name already in this registry** raises `ValueError`, so a copy-pasted
  declaration fails instead of shadowing an operation.
- **Something that is not a `ServiceSpec` or a `SelectorSpec`** raises
  `TypeError`.
- **A spec with no permission check** raises `ImproperlyConfigured`. Dispatch
  would refuse it on every call, and finding out at the first call is later
  than finding out at startup. An operation that is open says so with
  `permissions=[Unrestricted()]`.

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

Three calls derive a new registry from an existing one:

- **`by_tag(*tags)`** keeps the entries carrying **any** of the tags. It is a
  union; chain the calls for an intersection:
  `registry.by_tag("catalogue").by_tag("write")`. No tags keeps nothing.
- **`subset(*names)`** keeps the named entries, **in the order named**. A name
  that is not registered raises `KeyError`: a typo is a configuration error,
  not a quietly smaller surface.
- **`merge(*others)`** combines registries, in order. Names are unique within
  one registry, so two independent registries may each use a name; merging is
  where that becomes a conflict, and it raises `ValueError`.

Every view is a **snapshot**. It shares the spec objects rather than copying
them, it never changes its source, and a `register()` on the source afterwards
does not appear in a view taken before it. A transport reads its view once, at
configuration time, to build its own table of operations; nothing reads a
registry per dispatch.

There is **no global registry**. A project holds as many registries as it has
reasons to, with no state shared between them, and passes each transport the
one it should expose.
