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

A deactivated principal is refused first, as `PrincipalUnavailable`: an
authenticated one whose `is_active` is false. One with no `is_active` reads as
active, and anonymous goes on to the permission check, which decides whether
anonymous may act. Then the same seven steps for a read and a write, and for
the async entry point:

1. **The shape check and the closed argument set**, over `spec.parameters()`:
   presence, JSON type, format, choices and nullability at every level of
   nesting, with no query. An argument no parameter declares is refused. A
   [`partial`](declaring.md#partial-updates) write's absent Validator
   parameters are not refused, nor one its `input_data` provider is annotated
   to fill.
2. **Class-level authorization**: every permission check's `has_permission`,
   or the [grant](#grants) a transport passed instead.
3. **Target resolution**: a read's own selector, or a write's instance or
   collection selector, called with the arguments its `reads` declare and
   what its `kwargs` provider returns, then shaped. A retrieve that finds
   nothing is `kind="not_found"`, unless the selector allows `None`. A
   [`target=`](#a-target-resolved-ahead-of-the-call) the caller passed stands
   in for this step.
4. **Object-level authorization**: every check's `has_object_permission` on a
   retrieved row, and its [`has_scope_permission`](#permissions) where no
   single row is: a list a read returns or a write's collection, empty or not,
   and the `None` of a create, of a `many` write and of a missing row a
   write's `allow_none` lets through. A read's own `None` under `allow_none`
   is asked of neither.
5. **Validation**: a write's `input_data` provider, then its Validator on only
   the arguments it declares, with the provider's values merged over the
   caller's, and the resolved target and `partial` in its context.
6. **Affordances, then preconditions**: a write's `affordances`, in
   declaration order - the first one not met refuses the call with
   `ActionUnavailable`, carrying its `code` - then its `preconditions`, the
   first to raise aborting the call with what it raised.
7. **The run**: the service, inside `transaction.atomic()` unless the spec says
   `atomic=False`, called with what its `kwargs` provider returns beside the
   validated values, then the output selector if one is declared.

A read stops after step four and its `preconditions`, which run on what its
selector found: its selector is its run. Its `affordances` are answers about
each row, for a list to report, and refuse nothing.

A [`many`](declaring.md#many-rows-in-one-call) write resolves nothing in steps
three and four, where its scope check is asked of `None`, never of the
caller's rows. Step one raises only the top level's refusal; a row's is raised
in step five, beside the Validator's refusals of the other rows, so a
principal refused in step two learns nothing about the rows it sent.

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
- **A deactivated principal is refused before the shape check**, so it learns
  nothing about its arguments, and it is refused at the same point whether it
  was handed over, named by `principal_id` or read off `request.user`.
- **Affordances come after object-level authorization and validation**, so a
  principal who may not see the row is never told what state it is in. They
  come before the run's transaction opens, so a refusal never opens one.
  Preconditions follow them, in the same place, as djangorestframework-services
  orders the two.

## The result

A `DispatchResult` has a `kind` and a `value`:

| `kind` | When | `value` |
| --- | --- | --- |
| `"list"` | A `LIST` read, a write whose output selector is a `LIST`, or a `many` write with no output selector whose service returned something | The rows, a queryset when the selector returned one, `[]` when a selector declaring `allow_none` returned `None` |
| `"instance"` | Everything else that ran | The row, the service's return, or what the output selector re-read |
| `"not_found"` | A required row does not exist | `None` |

A write's result also carries `service_result` (the service's own return,
before any output selector), `instance` (the resolved target) and `data` (the
Validator's `data` the service received: the validated values, or the
instance a `DataclassValidator` built, or a `many` write's list of them).

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

The output selector is called from the base pool plus the service's return,
under two names: `result`, and `instance`, as djangorestframework-services
binds it. They are one value, whatever the service returned, `None` included,
so a re-read declares whichever its author wrote. `instance` there is what the
service returned, not the target it acted on, which the result carries as
`result.instance`.

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
`has_scope_permission` is the same question for a call that resolves no
single row - asked of the set a collection write acts on or a list read
returns, and of `None` where the call acts on no existing row, a create - and
allows unless overridden too. It is a method of its own rather than
`has_object_permission` handed a set or `None`, because a check written for a
row reads an attribute off it and would fail on either. `message` is what
[`NotPermitted`][django_service_specs.authorization.not_permitted.NotPermitted]
says when the check refuses.

**A check is sync-only**: it may query, so the async entry point runs it in
the executor. An `async def` method would answer with a coroutine, which is
truthy and would allow every call, so a spec refuses a check declaring one
when it is built, with `ImproperlyConfigured` naming the method. A method that
hands back a coroutine from a plain `def` - a decorated `async def` - is
refused where its answer is read, so the call fails closed.

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
the row and run the object-level check itself, and which covers a service
spec's target only when that target is handed to `dispatch` as `target=`;
otherwise dispatch still runs `has_object_permission` on the row it resolves.
A selector spec's claim covers whatever its selector returns: a selector spec
takes no `target=`, so there is no row handed in to bind the claim to, and
dispatch skips the check on the row the arguments make the selector find. A
transport claims it only when it has checked that very row, found from the
same arguments; without the claim, the check sees the row the call returns,
shaped and annotated, and the list it returns. A grant stands in for neither
check that is not about permission: a deactivated principal is refused with
one, and a write's affordances are still answered. And **a grant cannot be
serialized**: pickling one raises `TypeError`, so it cannot ride a queue into a
worker. A task runs later, against state that may have moved, and
re-authorizes by construction.

[`authorize`][django_service_specs.authorization.authorize.authorize],
[`authorize_target`][django_service_specs.authorization.authorize_target.authorize_target]
and [`authorize_scope`][django_service_specs.authorization.authorize_scope.authorize_scope]
are the three checks dispatch runs, exported for a transport that runs them
itself; `authorize` returns the grant it honoured or a new one covering the
spec and principal, and the other two are skipped under `target_checked`
where the target was handed in as `target=`.

### A target resolved ahead of the call

A page that shows the row before the call acts on it - the form in front of
an update, the confirmation in front of a delete - must show the row dispatch
would find, refused where dispatch would refuse it.
[`resolve_target`][django_service_specs.dispatch.resolve_target.resolve_target]
runs dispatch's own steps for a write's target and nothing else: the
deactivated principal, the shape check over **the target selector's
parameters alone**, class-level authorization, then the very lookup and checks
dispatch runs. A Validator field is neither required nor unknown there, and a
target read the selector's `kwargs` provider fills is not required, as in
dispatch, so a GET carrying the route's arguments resolves as a POST carrying the whole form
does.

```python
--8<--
docs/examples/dispatching.py:resolve_target
--8<--
```

It returns `(target, grant)`: the row, the set, or `None` for a create, and a
grant covering the spec and the principal with `target_checked` set. Both go
to `dispatch(..., target=, grant=)`, which then looks nothing up and asks no
object-level or scope check again. The grant is honoured only with the
target it was resolved for: handed on without `target=`, dispatch looks the
row up itself and runs the checks on it. A missing row that `allow_none` does not
let through comes back as `DispatchResult(kind="not_found")`, so it is never
mistaken for the `None` it lets through. A read, whose selector is its run,
raises `TypeError`, and a `many` write, which has no target,
`ImproperlyConfigured`. It is sync; an async caller hops once with
`sync_to_async`.

`target=` on `dispatch` and `adispatch` takes any target the caller resolved -
what an HTTP view's `get_object()` found, too - and stands in for step three.
Step four still runs on it unless the grant says `target_checked`; without
`target=` step four always runs. `None` is a
missing row, not-found unless the instance selector says `allow_none`; a
create takes `None` and refuses anything else. **Dispatch trusts it**: the
target's `reads` are still checked as declared, and keeping them and the
target in agreement is the caller's.

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
the refusal does not wait for them: `resolve_principal` refuses one at lookup,
and `dispatch` refuses one it is handed, by the same rule.

## Binding without dispatching

Some transports bind input themselves: an MCP server answering a malformed call
before it opens a transaction, a queue validating a task in the worker.
[`bind_arguments`][django_service_specs.dispatch.bind_arguments.bind_arguments]
runs the same two steps dispatch does - the shape check over
`spec.parameters()`, relaxing what dispatch relaxes for `partial` and for a provider's
filled keys, then the Validator on its own arguments - so a
transport that binds for itself cannot drift from the gate dispatch applies.
It runs no provider: a field an `input_data` provider would fill passes the
shape check and, left out, is the Validator's to refuse; a read a `kwargs`
provider would fill passes too.

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
`extend_queryset`, `filter_set`, an affordance's condition, the providers, the
preconditions, a seed's resolver - each refused with `ImproperlyConfigured`
naming its seat if declared `async def`, when the spec is built - because each may query, and because a spec
is written once for both entry points: a check written `async def` could not
be called from `dispatch`. The run is the one callable no step shares.

Most of them are refused when they are declared `async def`, with
`ImproperlyConfigured` naming the seat: a permission check's methods,
`extend_queryset`, `filter_set`, the providers and the preconditions when the
spec is built, an affordance's condition when it is declared, and a seed's
resolver when `PoolSeeds` is built. Each is called from sync code and never
awaited, and its unawaited answer is truthy, so a check would allow every
call and a condition would read as met. An answer still to be awaited from a
plain `def` is refused where it is read, for a permission check, a condition,
a seed and `extend_queryset` alike, so the call fails closed: a lambda calling
an `async def` from `extend_queryset` would otherwise hand dispatch a coroutine
for the queryset, and a list's value would be that coroutine.

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

Every refusal before the run is made inside that hop, an affordance included:
a condition on the row is a query.

```python
--8<--
docs/examples/async_dispatch.py:async
--8<--
```

`adispatch` takes exactly one of `principal` and `principal_id`. An identifier
is resolved with `resolve_principal` inside the hop, since resolving it is a
query. A grant never covers a principal resolved there, because a grant is
bound to the principal object it was made for. A deactivated row is refused
there, with its identifier in the message.

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
steer one by naming an argument after something its resolver reads. A resolver
is sync-only: an `async def` one is refused with `ImproperlyConfigured` when
it is registered, and a plain `def` handing back an awaitable is refused where
it is resolved.

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

### Progress

`progress=` on `dispatch` and `adispatch` takes the transport's own
[`ProgressReporter`][django_service_specs.types.progress_reporter.ProgressReporter]:
a callable taking how far along, and optionally `total`, `message` and
`meta`. It is seeded under the reserved name `progress`, as it is, into the
pool of the call's run - the service, or a read's own selector - and of that
spec's callable affordance conditions. A reporter must not raise, because nothing
between it and the service catches it. Under `adispatch` a sync run calls it
on the executor thread, and an `async def` run on an event loop.

```python
--8<--
docs/examples/dispatching.py:progress
--8<--
```

With no reporter the pool carries
[`null_progress`][django_service_specs.pool.null_progress.null_progress], so a
service that declares `progress` runs unchanged on every transport and in
tests. A spec's own `progress_reporter` provider adds a sink of the author's
beside the transport's - a task record, an audit trail - for the run alone,
and only for a run that takes `progress`: called on its first report, or
before an `async def` run once nothing before the run can refuse the call. A
call refused before its run never calls it, a selector spec's whose selector
is refused a read the caller left out included. A selector spec's selector is
its run, though, and its object check, scope check and preconditions answer
what the run returned, so a selector spec refused at one of those may already
have called it. The selector spec's affordance conditions, `extend_queryset`
and preconditions read the transport's reporter, as a service spec's do. A target or output selector always gets `null_progress`: a lookup has
nothing to report, and one reporting after the service finished would read to
a watching client as the work restarting.
