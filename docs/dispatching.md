# Dispatching

[`dispatch`][django_service_specs.dispatch.dispatch.dispatch] runs one spec for
one principal with one set of arguments, and returns a
[`DispatchResult`][django_service_specs.dispatch.dispatch_result.DispatchResult].
It is the whole of what a transport calls: an HTTP view, an MCP tool, a
command and a task worker each build a principal and a mapping of arguments,
dispatch, and answer the result in their own terms.

```python
result = dispatch(spec, principal=user, arguments={"pk": 3, "title": "Final"})
```

## The order

The same six steps for a read and a write, and for the async entry point:

1. **The shape check and the closed argument set**, over `spec.parameters()`:
   presence, JSON type, format, choices and nullability at every level of
   nesting, with no query. An argument no parameter declares is refused.
2. **Class-level authorization**: every permission check's `has_permission`,
   or the [grant](#grants) a transport passed instead.
3. **Target resolution**: a read's own selector, or a write's instance or
   collection selector, called with the arguments its `reads` declare, then
   shaped. A retrieve that finds nothing is `kind="not_found"`, unless the
   selector allows `None`.
4. **Object-level authorization**: every check's `has_object_permission`, on a
   retrieved row. Never on a list, which has no single object to check, and
   never on a `None` that `allow_none` let through.
5. **Validation**: a write's Validator, on only the arguments it declares, with
   the resolved target in its context.
6. **The run**: the service, inside `transaction.atomic()` unless the spec says
   `atomic=False`, then the output selector if one is declared.

A read stops after step four: its selector is its run.

The order is the design, and each place reads as if it could move:

- **The shape check comes first** because it costs nothing and reveals nothing
  the declaration does not already say, so a malformed call is refused before
  it costs a row lookup.
- **Class-level authorization comes before resolution**, so a principal it
  refuses learns nothing about which rows exist: a missing row and a present
  one are refused alike.
- **Resolution comes before validation**, so the Validator's context carries
  the row. An update's uniqueness check has to exclude the row being updated,
  and it cannot if the row is resolved afterwards.

## The result

A `DispatchResult` has a `kind` and a `value`:

| `kind` | When | `value` |
| --- | --- | --- |
| `"list"` | A `LIST` read, or a write whose output selector is a `LIST` | The rows, a queryset when the selector returned one |
| `"instance"` | Everything else that ran | The row, the service's return, or what the output selector re-read |
| `"not_found"` | A required row does not exist | `None` |

A write's result also carries `service_result` (the service's own return,
before any output selector), `instance` (the resolved target) and `data` (the
validated values the service received).

**Not-found is reported, not raised.** A transport decides what a missing row
means on its own wire - a 404, an exit code, a tool error - and most transports
have no status codes for the kernel to choose from.

```python
--8<--
docs/examples/dispatching.py:list
--8<--
```

```python
--8<--
docs/examples/dispatching.py:retrieve
--8<--
```

`note_spec` scopes its selector to the principal, so another user's note is not
found rather than refused: it does not exist for them.

One case is not reported as not-found: **a retrieve output selector that finds
nothing**. The service has already run and, under `atomic`, committed, so
reporting not-found would tell the caller the write did not happen. The value
is `None` under `kind="instance"` instead.

## Presenting

Nothing is rendered by `dispatch`.
[`present`][django_service_specs.dispatch.present.present] renders a result
through the spec's presenter when the transport asks, so one that hands the
row to a template never pays for rendering it.

- A `"list"` result is presented item by item, into a list. With no presenter
  the items come back as they are, still in a list: a queryset is evaluated
  here rather than handed back lazily.
- An `"instance"` result is presented through the presenter. A value of `None`
  is returned as `None`, never handed to a presenter to render as a row of
  blank fields.
- A `"not_found"` result raises `ValueError`. Presenting nothing as a success
  is the bug this refuses; answer the not-found first.

[`apresent`][django_service_specs.dispatch.apresent.apresent] does the same from
async code, in one executor hop, since a presenter may query.

## Permissions

A [`PermissionCheck`][django_service_specs.authorization.permission_check.PermissionCheck]
takes a principal and a spec, and nothing else: no request and no view, because
most transports have neither. Checks are **instances**, so a check can carry
its own configuration - a codename, a group - and a spec reads as the list of
checks it applies. `has_permission` is the class-level check;
`has_object_permission` runs on a resolved row and allows unless overridden;
`message` is what [`NotPermitted`][django_service_specs.authorization.not_permitted.NotPermitted]
says when the check refuses. A check is sync-only: it may query.

**A spec with no permission check is refused**, with `ImproperlyConfigured`, at
dispatch and at [registration](registry.md). Off HTTP there is no view whose
policy an undeclared operation could inherit, and running it anyway is how an
off-HTTP runner skips authorization with nothing warning. An operation that is
genuinely open says so with `permissions=[Unrestricted()]`, which is also one
search away when someone asks which operations are open.

### Grants

**Dispatch enforces the permission check by default.** A transport that has
already authorized through its own machinery - an HTTP view that ran its
framework's permission classes - says so with a
[`Grant`][django_service_specs.authorization.grant.Grant] rather than by
skipping the check, and pays for one class-level evaluation instead of two:

```python
--8<--
docs/examples/dispatching.py:grant
--8<--
```

A grant is bound **by identity** to one spec object and one principal object.
Carried to another operation or another user it covers nothing, and dispatch
refuses it with `NotPermitted`. It covers the class-level check only, unless
it says `target_checked=True`, which a transport can claim once it has resolved
the row and run the object-level check itself; otherwise dispatch still runs
`has_object_permission` on the row it resolves. And **a grant cannot be
serialized**: pickling one raises `TypeError`, so it cannot ride a queue into a
worker. A task runs later, against state that may have moved, and
re-authorizes by construction.

[`authorize`][django_service_specs.authorization.authorize.authorize] and
[`authorize_target`][django_service_specs.authorization.authorize_target.authorize_target]
are the two checks dispatch runs, exported for a transport that runs them
itself; `authorize` returns the grant it honoured or a new one covering the
spec and principal.

### Principals off HTTP

HTTP has a session to resolve a user from; a queue payload, a command argument
or an agent's notion of who is asking carries an identifier.
[`resolve_principal`][django_service_specs.authorization.resolve_principal.resolve_principal]
is the one place that becomes a user row, and it refuses a missing, malformed
or deactivated one with
[`PrincipalUnavailable`][django_service_specs.authorization.principal_unavailable.PrincipalUnavailable].
It never falls back to an anonymous user: an operation dispatched with no
resolvable principal has no principal, not an anonymous one. The stock
permission classes of the HTTP frameworks pass a deactivated user, which is why
the refusal lives at lookup.

## Binding without dispatching

Some transports bind input themselves: an MCP server answering a malformed call
before it opens a transaction, a queue validating a task in the worker.
[`bind_arguments`][django_service_specs.dispatch.bind_arguments.bind_arguments]
runs the same two steps dispatch does - the shape check over
`spec.parameters()`, then the Validator on its own arguments - so a transport
that binds for itself cannot drift from the gate dispatch applies.

```python
--8<--
docs/examples/dispatching.py:bind
--8<--
```

It returns the Validator's values: `{"title": "Final"}` here, without the `pk`
the instance selector reads. A read has no Validator, and gets its checked
arguments back.

**It does not resolve or authorize.** Dispatch runs both between the two
steps. A caller of `bind_arguments` owns them: it authorizes before binding,
and passes the row it resolved as `target`, or `None` for a create.

## The async entry point

[`adispatch`][django_service_specs.dispatch.adispatch.adispatch] takes the same
steps in the same order, from async code, and
[`apresent`][django_service_specs.dispatch.apresent.apresent] renders its result.

**Only the run may be `async def`**: a write's service, or a read's own
selector. Every other callable a spec carries is sync-only - a permission
check, a Validator, a Presenter, a selector nested in a write,
`extend_queryset`, a seed's resolver - because each may query, and because a
spec is written once for both entry points: a check written `async def` could
not be called from `dispatch`. The run is the one callable no step shares.

So `adispatch` runs the steps in **one** thread-sensitive executor hop, and the
run's shape decides only what joins it:

- A sync run joins the hop, so a sync spec costs exactly one.
- An atomic `async def` service joins it too. `transaction.atomic` is
  sync-only, so the transaction is opened on the executor thread and the
  coroutine is driven inside it, where its own ORM calls reach the connection
  holding the transaction.
- A non-atomic `async def` run is awaited on the event loop after the hop.
  Holding the executor thread while it waits on the network would stall every
  thread-sensitive call queued behind it. Anything after it - an output
  selector, a read's shaping and object-level check - takes a second hop.

```python
--8<--
docs/examples/async_dispatch.py:async
--8<--
```

`adispatch` takes exactly one of `principal` and `principal_id`. An identifier
is resolved with `resolve_principal` inside the hop, since resolving it is a
query. A grant never covers a principal resolved there, because a grant is
bound to the principal object it was made for.

The sync `dispatch` accepts an `async def` run as well, and drives it to
completion, inside the transaction when the spec is atomic.
[`run_service`][django_service_specs.services.run_service.run_service] and
[`arun_service`][django_service_specs.services.arun_service.arun_service] are
that bridge, exported for a transport that calls a service directly.

## Pool seeds

Off HTTP there is no request for ambient values to hang off: a tenant, a
correlation id, a locale, a clock. A
[`PoolSeeds`][django_service_specs.pool.pool_seeds.PoolSeeds] registry is that
channel. Each registration is a name and a resolver, and the resolver's value
is in every pool dispatch builds - the service's, each selector's,
`extend_queryset`'s - for any of them to declare:

```python
--8<--
docs/examples/dispatching.py:seeds
--8<--
```

A resolver declares what it wants from the pool like any other callable, and
sees the principal, never an argument: a seed is ambient, and a caller must not
steer one by naming an argument after something its resolver reads.

A registered name is **reserved**, and that is half of what registering does.
A spec that declares a parameter by that name is refused at dispatch with
`ImproperlyConfigured`; a caller that sends it is refused like any other
undeclared argument; and `extend()` refuses one of the dispatcher's own names,
or a name registered twice, with `ValueError`. Either half alone is a trap: a
value with no reservation would share the pool with an argument of the same
name, and a reservation with no value would fail the callable that declares
it.

`PoolSeeds` is immutable and `extend()` returns a new registry, so pass one per
dispatch rather than installing one process-wide: two mounts with different
ambient context need them to differ. An adapter that builds a pool of its own
builds it with [`base_pool`][django_service_specs.pool.base_pool.base_pool]
and binds a callable with
[`resolve_callable_kwargs`][django_service_specs.pool.resolve_callable_kwargs.resolve_callable_kwargs],
the declare-to-receive rule every callable here is called through.
