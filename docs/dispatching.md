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
   or the [grant](#grants) a transport passed instead. A seed a check names
   is resolved just before it, and only such a seed
   ([permissions](#permissions)).
3. **Target resolution**: a read's own selector, or a write's instance or
   collection selector, called with the arguments its `reads` declare and
   what its `kwargs` provider returns, then shaped. A retrieve that finds
   nothing is `kind="not_found"`, unless the selector allows `None`; a
   selector raising `Http404`, as `get_object_or_404` does, is that missing
   row on a retrieve, and `kind="not_found"` on a list or a collection,
   whatever `allow_none` says (see [Declaring](declaring.md)). A
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
principal refused in step two learns nothing about the rows it sent. That
node reads in index order, then the list's own `non_field_errors`. Where it
carries that message it mixes `int` keys with a string one, so
`json.dumps(..., sort_keys=True)` over it raises `TypeError` - write it as it
stands.

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

## Per-call values beneath the provider

A transport sometimes knows a service keyword per call that the spec cannot
carry: what an HTTP view's per-request hook returns. `dispatch` and `adispatch`
take it as `extra_kwargs`, so the spec need not be rebuilt for the call:

```python
--8<--
docs/examples/dispatching.py:overlays
--8<--
```

`extra_kwargs` is the lowest of three tiers: beneath the spec's `kwargs`
provider, so **the spec's own provider wins on a clash**, and beneath what the
spec's Validator computed or bound. It is read as the provider's return is:

- an entry whose value is `UNSET` is dropped;
- a key the spec's provider is annotated to fill is the provider's alone, and
  the overlay's value for it is dropped, so a provider that leaves the key out
  leaves it absent; one annotated `UNSET`-able lets the overlay's value through
  when it declines;
- a key naming a seed, such as `user`, is refused as `ImproperlyConfigured`.

**A key naming a parameter the spec declares is refused**, as
`ImproperlyConfigured`, before the shape check, the way a seed's name is. A
declared parameter is anything `spec.parameters()` lists: the spec's `reads`,
its Validator's fields, its target selector's `reads`, and a `many` spec's
list. The caller's value for one is what the [permission checks](#permissions)
are handed and what the target selector looks the row up by, so an overlay
standing in for it would run the call on a value neither saw: the value
authorized is the value run. Two keys that name one are not refused: an `UNSET`
entry, which supplies nothing, and a parameter the spec's own typed `kwargs`
provider fills, whose caller's value is dropped before any check and whose
overlay value is dropped beneath the provider. To set such a value per call,
fill it from that provider.

**A key naming a value the spec's Validator computed is never the
overlay's**: a key of the `values` its `validated()` returned, or of the `pool`
it bound, is left to the Validator, and the overlay's entry is dropped for that
call rather than refused. Whether a Validator computes a key can turn on what
the caller sent - a `slug` derived from a `title` only when one arrives - so a
refusal there would let a request decide whether a misconfiguration error
fires. The overlay fills such a key on the calls where the Validator leaves it
out. Refusal is kept for what is static: a key naming a declared parameter, or
a seed, is refused on every call alike.

`extra_kwargs` reaches a read's own selector and a write's service, never a
target or output selector.

**There is no overlay for the Validator's input.** Every value one could carry
to the Validator is a field the caller sends, so an overlay would stand in for
a value the permission checks saw. A transport with per-request values for the
Validator merges them into the `arguments` it hands `dispatch`, where the
checks and the Validator read the same value.

## The result

A `DispatchResult` has a `kind` and a `value`:

| `kind` | When | `value` |
| --- | --- | --- |
| `"list"` | A `LIST` read, a write whose output selector is a `LIST`, or a `many` or `returns_many` write with no output selector whose service returned something | The rows, a queryset when the selector returned one, `[]` when a selector declaring `allow_none` returned `None` |
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
is `None` under `kind="instance"` instead, whether the re-read returned `None`
or raised `DoesNotExist` or `Http404`. A list output selector raising `Http404`
is a fault for the same reason, and raises a `RuntimeError` chained from it.

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
takes a principal and a spec, and nothing else by position: no request and no
view, because most transports have neither. A check that wants them declares
`request` or `view` by keyword and is handed what the call's context holds
under that key, `None` where it holds none
([the call's `request` and `view`](#the-calls-request-and-view)). Checks are **instances**, so a check can carry
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

**A check can read the call's arguments** by declaring a keyword `arguments`
on any of its three methods. Dispatch then hands that method the call's
shape-checked arguments as a read-only mapping - a route's captured `pk`, a
filter the caller sent - as an HTTP permission class reads the view's captured
kwargs. Only the mapping is read-only: its values are the call's own objects,
the ones the run receives, so a check must not mutate them.

```python
--8<--
docs/examples/dispatching.py:arguments_channel
--8<--
```

A method that does not declare the keyword is asked exactly as before, so no
existing check changes. The base methods do not declare it, which keeps every
check written without it a valid override under a type checker. Opt-in is by
name. What is read is what dispatch calls, `getattr(check, method)`: a
callable set on the instance, or a mock patched over the method, answers for
its own signature. Behind decorators, the `__wrapped__` chain
`functools.wraps` leaves is read one layer at a time, each by its own
signature, since each is called in turn: a layer naming `arguments` takes it,
a layer spreading `**kwargs` passes it to the layer beneath, and a layer with
neither would refuse it. So the keyword is handed only where a layer names it
before any layer without `**kwargs`: an ordinary forwarding decorator, or
several, keeps an opted-in check opted in, while a narrower layer anywhere in
the chain, or `**kwargs` with nothing beneath that asked, is handed nothing.
A callable with no signature to read, such as a builtin behind
`functools.partial`, is asked as a check that never opted in.
`arguments` is `None` where a transport calls `authorize()` without
`arguments=`, and a check that needs them decides for itself what that means:
the example above refuses. A [`many`](declaring.md#many-rows-in-one-call)
call's rows are not among the arguments: they are validated after every
check, so a check sees the call's `reads` alone. The
[`authorize`][django_service_specs.dispatch.authorize.authorize] functions
take the same mapping as `arguments=` for a transport that calls them itself.

A transport listing what a principal may run has no arguments to hand a check
that declares them.
[`checks_read_arguments`][django_service_specs.dispatch.checks_read_arguments.checks_read_arguments]
says whether any does, without calling a check: `True` when a check declares
`arguments` on the class question or, for a service spec with no target
selector (a create), the scope question. It answers what a check *declares*,
not what it does with `None`: a check declaring `arguments=None` reads `True`
though it answers when handed nothing. The object question and a target's scope
question are asked of a resolved row, which a listing has none of, so they are
not read. The declaration is read as `authorize` reads it - a forwarding
wrapper over a method naming `arguments` counts, a check taking only `**kwargs`
or naming `arguments` in a position the call fills does not - so the two cannot
disagree.

```python
--8<--
docs/examples/dispatching.py:checks_read_arguments
--8<--
```

**A check can read the call's context and a registered seed the same way.** A
keyword `call_context` is handed the one dict every stage of the call shares
([the call's context](#the-calls-context)), and a keyword named after a seed
the call's [`PoolSeeds`](#pool-seeds) register is handed that seed's value, at
whichever of the three questions declares it. A parameter the call fills by
position - the principal, the spec, the target or scope, whatever the method
calls them - is never an opt-in, whatever its name, so a DRF-style
`has_permission(self, request, spec)` under a transport registering a
`request` seed is asked as it always was. A seed named `arguments` is never
handed this way: a check declaring `arguments` gets the call's. Only the seeds
a spec's checks name are resolved early, before the class-level check, and
every pool after reuses those values, so each resolves once per call and the
check and the service see one object; every other seed resolves after the
class-level check, as it always has. A seed resolver raising
[`PrincipalUnavailable`][django_service_specs.authorization.principal_unavailable.PrincipalUnavailable]
there ends the call before any check is asked, as a refusal does. The
`authorize` functions take `call_context=` and `seeds=` to offer the same, or
`pool_seeds=` to resolve the seeds their checks name
([admitting a request before the form](#admitting-a-request-before-the-form)), and
with no `call_context` a check declaring it is handed a fresh dict.

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
[`Grant`][django_service_specs.dispatch.grant.Grant] rather than by
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
**On a selector spec the claim covers nothing**: a selector spec takes no
`target=`, so there is no row handed in to bind the claim to, and the row
the arguments make the selector find may be one the transport never
checked. Dispatch runs the check on the row the call returns, shaped and
annotated, and the scope check on the list it returns, whatever the grant
says, as djangorestframework-services checks the row its selector returned.
A grant stands in for neither
check that is not about permission: a deactivated principal is refused with
one, and a write's affordances are still answered. And **a grant cannot be
serialized**: pickling one raises `TypeError`, so it cannot ride a queue into a
worker. A task runs later, against state that may have moved, and
re-authorizes by construction.

[`authorize`][django_service_specs.dispatch.authorize.authorize],
[`authorize_target`][django_service_specs.dispatch.authorize_target.authorize_target]
and [`authorize_scope`][django_service_specs.dispatch.authorize_scope.authorize_scope]
are the three checks dispatch runs, exported for a transport that runs them
itself; `authorize` returns the grant it honoured or a new one covering the
spec and principal, and dispatch skips the other two under `target_checked`
only where a service spec's target was handed in as `target=`.

### Admitting a request before the form

A page asks the class-level check before it shows anything, so a principal
the check refuses never sees the form. Where that check names a seed - the
club a route captured, a tenant read off the request - the transport has the
registry it would hand dispatch rather than the seed's value, and hands that
to `authorize` as `pool_seeds=`:

```python
--8<--
docs/examples/dispatching.py:admit_check
--8<--
```

```python
--8<--
docs/examples/dispatching.py:admit
--8<--
```

Only the seeds the spec's `has_permission` checks name are resolved, once in
the `authorize` call, for the principal as `user`, exactly as dispatch
resolves them before its own class-level check; a seed no check names there is
never resolved, and neither is any seed when a covering grant answers first.
The values are not carried on the grant, so the `dispatch` that follows
resolves the seeds its checks name again, for its own call: the check
`authorize` asked and the service may see two objects from one resolver. `authorize_target`
and `authorize_scope` take `pool_seeds=` the same way, for the seeds their own
question names. `seeds=` is the alternative for a caller holding resolved
values, and handing both raises `TypeError`, since one would silently outrank
the other, whether or not a grant would have answered the call first. A
deactivated principal handed with `pool_seeds=` raises
[`PrincipalUnavailable`][django_service_specs.authorization.principal_unavailable.PrincipalUnavailable]
before any seed resolves, as dispatch refuses one before anything else, grant
or no grant; without `pool_seeds=` nothing is resolved and the call is asked as
it always was. A check naming a seed the registry does not hold is asked without
it, as under `seeds=`, so its own signature decides.

### Building the form before the call

The page above builds its form itself, to show it, and the form's `__init__`
takes a keyword of its own, which the spec's
[`FormValidator`](forms.md#a-form-with-keywords-of-its-own) supplies through
`form_kwargs` on dispatch:

```python
--8<--
docs/examples/dispatching.py:club_form
--8<--
```

[`form_keywords`][django_service_specs.adapters.forms.form_keywords.form_keywords]
returns what that `form_kwargs` returns, off dispatch, so the page's GET
builds the form as the POST's dispatch will: `ClubNoteForm(**extra)` in the
page above, and the POST that fails validation shows it again, bound to what was
posted, built the same way. It binds `form_kwargs` from the pool dispatch would - the
principal as `user`, the no-op reporter as `progress`, the call's context
and the target under the name the service receives it by (`instance` or
`collection`, nothing for a create) - and resolves only the seeds of
`pool_seeds=` that `form_kwargs` would be handed: those it names, or every
one for a callable taking `**kwargs`. A page hands it the `call_context=` it
hands dispatch, so the failed POST's re-rendered form reads the dict that
dispatch ran with, and the row
[`resolve_target`](#a-target-resolved-ahead-of-the-call) found as `target=`.
Its answer is checked as the Validator checks it: anything but a mapping,
or a mapping returning `data`, `files` or `instance`, is refused with
`ImproperlyConfigured`. A spec whose Validator is not a `FormValidator` is
refused with `TypeError`, and a `FormValidator` with no `form_kwargs`
returns `{}`. Where it would resolve a seed for a deactivated principal it
raises `PrincipalUnavailable` first, as dispatch does, and a call that resolves
none is not refused. It neither authorizes nor looks the target up, and it is sync:
an async caller hops once with `sync_to_async`.

### A target resolved ahead of the call

A page that shows the row before the call acts on it - the form in front of
an update, the confirmation in front of a delete - must show the row dispatch
would find, refused where dispatch would refuse it.
[`resolve_target`][django_service_specs.dispatch.resolve_target.resolve_target]
runs dispatch's own steps for a write's target and nothing else: the
deactivated principal, the shape check over **the target selector's
parameters alone**, class-level authorization, then the very lookup and checks
dispatch runs. A Validator field is neither required nor unknown there, and a
target read the selector's `kwargs` provider fills or may fill is not required, as in
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
mistaken for the `None` it lets through, and so does a collection selector
raising `Http404`. A read, whose selector is its run,
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
or deactivated one, or a key past its integer column's range, an infinite
one included, with
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

## Checking a call before it runs

A transport that accepts a call now and runs it later - a task queue - can
refuse at enqueue what the worker's `dispatch` would refuse before it resolves
anything.
[`check_call`][django_service_specs.dispatch.check_call.check_call] runs
dispatch's prelude alone, through the same function, in dispatch's order: a
deactivated principal, an unmarked read or a shape a registered seed occupies, the shape check,
then the class-level permission check. Its keywords are dispatch's, less what
only a run reads. Nothing after the prelude runs - no lookup, object or scope
check, Validator, affordance or precondition - so a call it passes may still
be refused when it runs.

```python
--8<--
docs/examples/dispatching.py:check_call
--8<--
```

It returns the checked arguments and the grant, which `dispatch` honours for
the same spec and principal in the same process; a grant is not serializable,
so it never crosses a queue. The kernel's own steps run no query. It is
`bind_arguments`' complement: `check_call` authorizes and does not validate,
`bind_arguments` validates and does not authorize, and neither resolves a
target. A `many` call's refused rows are raised by it, after the permission
check, in the tree dispatch raises them in.

That one refusal is marked: its
[`after_authorize`][django_service_specs.parameters.invalid_arguments.InvalidArguments]
is `True`, and it is `False` on every refusal before the permission check and on
`dispatch`'s own refusal of the same rows. A transport that checks a call before
charging a rate limit reads it to tell a refused row, where the caller was
admitted and only its rows are wrong, from a refused call, without asking the
checks a second time.

```python
--8<--
docs/examples/dispatching.py:after_authorize
--8<--
```

## Arguments the server supplies

A transport sometimes knows a declared parameter's value better than its
caller does: an agent's toolset scoped to one project, a mount that serves
one account. The caller must not choose it, and should not be asked for it.
[`ServerArguments`][django_service_specs.types.server_arguments.ServerArguments]
says so for one spec, in two parts:

- **`values`** are the server's, and outrank the caller's. A bound value
  satisfies a `required` parameter and replaces a declared default. It takes
  the wire's spelling, as a caller's value would: a UUID's, a date's or a
  decimal's string rather than a `uuid.UUID`, a `date` or a `Decimal`.
- **`withheld`** names are taken from no one. The parameter is absent, so
  the callable's own default answers, as for any argument nobody sent.

Each name is a parameter the spec declares, so every reader of the call sees
the one value: the permission checks, the selector or service, and a `kwargs`
provider. The binding is a value, and a transport puts it to work at three points:

```python
--8<--
docs/examples/dispatching.py:server_arguments
--8<--
```

1. **Where the transport is built**,
   [`check_server_arguments`][django_service_specs.dispatch.check_server_arguments.check_server_arguments]
   refuses a binding that cannot mean what it says, with
   `ImproperlyConfigured`, naming the spec's callable: a name that is no
   top-level parameter, so not a field inside a `many` spec's rows; one both
   bound and withheld; one a pool seed occupies; a `reflected` read a seed
   fills, which binding or withholding would do nothing for; one a typed
   provider fills or may fill, whose answer dispatch would keep over the bound value on any
   call where it gives one; a withheld name no call could then do without;
   and a bound value its own parameter refuses, such as a `uuid.UUID` for a
   `format="uuid"` string. A withheld name cannot be done without when the
   shape check demands it (required, with no declared default, its
   Validator parameters relaxed on a `partial` spec as dispatch relaxes
   them) or when it is a read the callable receiving it declares with no default
   of its own. Dispatch applies no declared default, so the callable's is the
   one that answers, and a call without one would be refused as missing.
   Two limits of what it can see. The callable it reads a default off is the
   one the read is handed to - the selector, the service, or the target's
   selector - and not any other callable that also declares the read, such as
   a `kwargs` provider; a Validator parameter is judged by the shape check
   alone. And a provider whose return annotation names no keys may fill any
   name, so, as for `server_owned_keys`, it names none and a binding beside it
   is not refused.
2. **On each call**,
   [`apply_server_arguments`][django_service_specs.dispatch.apply_server_arguments.apply_server_arguments]
   returns a new mapping for `dispatch` or `adispatch`. It first drops the
   caller's value for every bound or withheld name, before anything reads
   it, so a value the caller sends for a name it was never offered cannot
   refuse the call, `"null"` for an integer included. It then lays the bound
   values over the rest, as the shape check hands them on: a UUID in its
   canonical spelling. Every other key is left for the shape check, so
   `REJECT` still refuses a name nobody declared.
3. **In the input schema the transport advertises**, it subtracts
   `names()` - the bound and the withheld together - from the properties
   and from `required`, beside
   [`server_owned_keys`][django_service_specs.specs.server_owned_keys.server_owned_keys].
   The kernel's own
   [`spec_input_schema`][django_service_specs.schema.spec_input_schema.spec_input_schema]
   takes no binding: the transports build their schemas themselves, and the
   subtraction belongs where the schema is built.

Dispatch itself takes no binding. The helpers are synchronous and pure, and
the applied mapping is ordinary arguments, so `dispatch` and `adispatch`
answer it alike and the permission checks read the bound values from the
first step. A transport path that skips `apply_server_arguments` is unbound.

**A bound value that fails its own declaration is the server's mistake**, so
`apply_server_arguments` raises it as `ImproperlyConfigured`, with the shape
check's refusal as its cause, never as `InvalidArguments`. A client refusal
would ask the caller to fix a value it neither sent nor can see. That is
where this parts from a route's captured kwargs, which are a client's 400:
the client chose the URL, and nobody but the server chose a bound value.

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

### The call's `request` and `view`

`dispatch` and `adispatch` hand two values to every callable they bind that
names one, read off the call's context:
[`CALL_SEEDS`][django_service_specs.pool.call_seeds.CALL_SEEDS], `request` and
`view`. Each is the very object the transport put in `call_context` under that
key, and `None` where it put none, so a spec callable written for HTTP binds on
every route and learns from a `None` that the call came from no request. Every
stage is handed them by declaring them: a seed's resolver, the selectors (the
target selector on every route, `resolve_target` included), `extend_queryset`,
a FilterSet, the providers, a `FormValidator`'s `form_kwargs`, the affordance
conditions, the preconditions, the run's `progress_reporter`, the service, the
output selector, and the row services and callable scopes of a nested write.

They are handed **by name only**, as `call_context` itself is: a `**kwargs`
catch-all is handed neither, and neither is a pool entry, so the Validator's
`ambient` holds neither and a Validator reads them off its context's
`call_context`. A seed's resolver may declare them; the commonest seed, a tenant
read off the request, is `tenant=lambda *, request: request.tenant`. The three
`authorize` functions offer both to a permission check that declares one, and
[`form_keywords`][django_service_specs.adapters.forms.form_keywords.form_keywords]
and the affordance functions read them off the `call_context` they are handed,
so a page or a listing asks what dispatch would.

A spec declaring a parameter named `request` or `view` is refused at dispatch
with `ImproperlyConfigured`, on every route, and so is a `kwargs` provider or an
`extra_kwargs` key of either name. A read reflected off a selector's own
signature is not refused: the call's value fills it, as a registered seed fills
one named like it. A top-level Validator field of either name is the caller's: it takes a registered seed's seat, as below, validating into
`data` while a service naming it reads the call's own. Neither name is in
`RESERVED_POOL_SEEDS` or `PoolSeeds.reserved`, so **a mount may still register
either** through `PoolSeeds`, by the constructor or `extend()`, as transports
released before dispatch supplied them do. Such a mount keeps its own: the
registered seed is a pool entry, the value at every stage and every check, and a
`**kwargs` catch-all is handed it as any seed; another seed's resolver still
reads the call's.

Two declarations of a seed's name are not refused, because neither shares the
pool with an argument. A read marked `reflected=True` is one an adapter took off
a callable's signature rather than one an author wrote, such as a selector's
`signature` parameter a project's seed is meant to fill. The seed fills it on
every call: the read is no argument of the call, so a caller sending its name
is refused as unknown under `REJECT` and dropped under `IGNORE`, and its value
never reaches the pool. An unmarked read, or a shape, by that name is still
refused.

```python
--8<--
docs/examples/dispatching.py:reflected_seed
--8<--
```

A top-level Validator field by a registered seed's name, on a service spec that
is not `many`, stays the caller's argument. It is validated into `data` and
never spread into the service's pool, so the service reads the caller's value
on `data` and the seed's under its own name. A field named like one of the
dispatcher's own names is still refused when the spec's parameters are
assembled.

```python
--8<--
docs/examples/dispatching.py:seed_named_field
--8<--
```

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
tests. A transport with more than one sink of its own - its client
channel beside a task record - hands dispatch
[`combine_progress`][django_service_specs.pool.combine_progress.combine_progress]
of them: every sink hears each report, and one that raises neither silences
the rest nor reaches the service. A spec's own `progress_reporter` provider adds a sink of the author's
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

### The call's shapes

`shapes` is a reserved seed, as `progress` is: what the caller sent for the
spec's declared [`shapes`](declaring.md#a-read), keyed by shape name
and read-only. It is the mapping the presenter reads as
[`PresentationContext.shapes`][django_service_specs.output.presentation_context.PresentationContext],
so a selector that eager-loads by what the presenter will render, as
django-restql's `query` does, reads the value the presenter reads. Any
callable dispatch resolves receives it by naming it: a selector and its
`extend_queryset`, a `kwargs` or `input_data` provider, a precondition, the
run's `progress_reporter`, the service, and a service spec's output selector,
which is handed the write's shapes. Its target selector is the exception, and
is handed an empty mapping (see the last item below).

- **Always there.** A spec declaring no shapes hands an empty mapping, and a
  shape the caller left out is absent from it rather than `None`, as on the
  presenter's context. A reservation with no value would fail the callable
  that declares it.
- **By name only**, as `call_context` is: a callable taking `**kwargs` is never
  handed it, so a selector forwarding its keywords into `filter()` runs
  unchanged.
- **Never the caller's.** It is in
  [`server_owned_keys`][django_service_specs.specs.server_owned_keys.server_owned_keys],
  and a parameter, read, shape or `many` list named `shapes` is refused when
  the spec is built, a Validator field of that name when the spec's
  parameters are first read (a transport's registration, or the first
  dispatch). Each of those refusals carries the rename in its message: name
  the parameter for what it holds, such as `fields` or `query`, and have the
  callable that read it declare `shapes`. `PoolSeeds.extend()` refuses a seed
  of that name, and says to register it under another.
- **Not for an affordance condition or the Validator.** A condition naming
  `shapes` is refused when it is declared, because what the caller sent would
  decide whether the operation is available, and the Validator, which is no
  pool callable, reads only its own arguments. Neither context's `ambient`
  holds it.
- **Empty for a target selector.** A write's target lookup is handed no
  shapes, on every route. `resolve_target` checks the target selector's own
  parameters alone, so a shape sent there is no argument of the lookup, and a
  lookup that read the shapes under `dispatch` would find a different row from
  the one `resolve_target` found. A target selector that names `shapes` is not
  refused, since it is often a read's own selector reused: it
  receives an empty mapping, and the row it finds is the row dispatch finds.

A selector joining only what the caller chose is shown under
[shaping each row by the call](paging-and-projection.md#shaping-each-row-by-the-call).

## The call's context

A call's stages often want one value more than once: a lookup the Validator
makes and the presenter needs again, a count across the rows of a list. A
[seed](#pool-seeds) is resolved from the principal before the stages run; the
call's context is for what a stage computes as it goes. It is one plain `dict`, the
transport's, created for its natural scope - a request, an agent run - and
carried as `call_context` on both
[`ValidationContext`][django_service_specs.validation.validation_context.ValidationContext]
and
[`PresentationContext`][django_service_specs.output.presentation_context.PresentationContext].

- **One object, never copied.** The Validator and the presenter are handed
  the same dict, as are every row of a `"list"` result and a nested presenter
  a presenter hands its context on to, so a later stage reads what an earlier
  one put there.
- **The stages', to read and write**, as a DRF serializer's `context` is. The
  kernel writes nothing to it, and unlike `ambient` it is not read-only.
- **A context built by hand gets an empty dict of its own**, never one shared
  with another context, so a stage that writes to it needs no guard for a
  call that was handed none.
- **It takes no part in equality or the hash**, as `ambient` does not, and it
  comes after the fields each context had before it, so an existing
  construction is unchanged.

Every stage shares the one dict, so key what a stage keeps by something of
its own, and cache a computed value under `setdefault`: it hands back what an
earlier stage put there, or puts the default and hands that back. The default
is evaluated either way, so make it a container to fill rather than the
computation itself, as the
[forms adapter's example](forms.md#the-calls-context) does.

### Handing dispatch the call's context

`dispatch`, `adispatch`, `check_call`, `bind_arguments` and
[`resolve_target`][django_service_specs.dispatch.resolve_target.resolve_target]
take the transport's dict as `call_context=`, and make a fresh one for the
call when none is passed:

```python
--8<--
docs/examples/dispatching.py:call_context
--8<--
```

The same object, never a copy, reaches every callable that names
`call_context`: a `kwargs` or `input_data` provider, a selector of any role
and its `extend_queryset`, an affordance condition, a precondition, the service, the run's
`progress_reporter`, `FormValidator`'s `form_kwargs`, a permission check's
methods, the Validator's and the presenter's contexts, and a
`PydanticValidator`'s field validators, on pydantic's `info.context` beside
`principal` and `target`. So the back office's dict above comes back holding
what the service left there.

- **By name only.** A callable taking `**kwargs` for the rest of the pool is
  never handed it, so a catch-all forwarding what it gets runs as it did
  before the name existed. One that wants it names it.
- **A reserved name**, in
  [`RESERVED_POOL_SEEDS`][django_service_specs.pool.reserved_pool_seeds.RESERVED_POOL_SEEDS]:
  a seed, a provider's key, an overlay or an argument named `call_context` is
  refused. Seed resolvers do not see it, since a seed is resolved before
  anything the call adds.
- **The kernel pre-fills nothing.** What goes in is the transport's
  convention: a transport over DRF is expected to put DRF's `request` there,
  and a key such as `request`, `view` or `format` means what the transport
  that wrote it says.
  The kernel writes nothing and keeps nothing across calls. It reads two
  keys, `request` and `view`, for a callable naming one
  ([the call's `request` and `view`](#the-calls-request-and-view)).
- **`transport` names the transport, across the family.** One key is reserved
  for every transport rather than left to each: a transport sets
  `call_context["transport"]` to name itself, so a stage that answers one
  transport differently from another - a condition, a provider, a presenter -
  reads one key whichever transport it runs under. The values are `"agent"`,
  which django-spec-agents sets on every call, and `"http"` and `"mcp"`, kept
  for an HTTP and an MCP transport. The transport serving the call sets it,
  replacing an entry already there: an agent run that arrived over HTTP and
  carries its request is still an agent's call when the agent's tools serve it.
  It is a convention, not a check: the kernel neither sets nor reads it, no
  name is refused for it, and a dict built by hand or handed to `dispatch`
  directly has none, so read it with `call_context.get("transport")`.
- **Calls sharing one dict.** The stages of one call run in sequence. A
  transport handing one dict to calls on several threads should have them
  write by compute-if-absent: read with `get`, and on a miss compute the value
  and store it with `call_context.setdefault(key, value)`, so the first write
  wins and every call reads one value. Fit for a value any of them would
  compute the same.

The affordance functions a transport calls ahead of the call or in place of
dispatch -
[`unmet_operation_affordance`][django_service_specs.affordances.unmet_operation_affordance.unmet_operation_affordance],
[`enforce_affordances`][django_service_specs.affordances.enforce_affordances.enforce_affordances]
and their async twins - take `call_context=` too, for a condition that names
it: the dict passed, else the one the pool carries, else a fresh one. Handed
one dict as the parameter and a different one in the pool, they refuse with
`ImproperlyConfigured` rather than choose.

## Answering every refusal

Dispatch refuses in two families, and a transport answers each refusal in its
own vocabulary: an exit code, an HTTP status, the state a background run ends
in. Those vocabularies stay the transport's, and one check is shared:
[`unanswered_refusals`][django_service_specs.dispatch.unanswered_refusals.unanswered_refusals]
says what a map leaves unanswered of
[`REFUSALS`][django_service_specs.dispatch.refusals.REFUSALS], every refusal the
kernel defines, so a transport holds its map total from its own test suite:

```python
--8<--
docs/examples/refusal_outcomes.py:outcomes
--8<--
```

It takes the map as it is written. An ordered table of `(refusal class,
outcome)` rows is read the way an `isinstance` ladder reads it, top to bottom
with the first match winning, so a row for a base answers every refusal under
it. A row whose outcome is the `unanswered=` value is no answer: a refusal it
catches first stays unanswered whatever a later row says. A callable written
as branches is passed as it is, with `unanswered=` naming the value it falls
back to; a mapping looked up by an error's exact class is a callable too,
`lambda error: table.get(type(error))`, since reading its keys as ordered rows
would let a base answer for a subclass the lookup never reaches.

Each finding is a
[`RefusalFinding`][django_service_specs.types.refusal_finding.RefusalFinding]:
the refusal it is about, its
[`RefusalFindingKind`][django_service_specs.types.refusal_finding_kind.RefusalFindingKind]
(`UNANSWERED`, `BARE_BASE` or `SHADOWED_ROW`), and for a shadowed row the row
above it. A transport that leaves a gap on purpose filters the findings by
refusal or kind, as the queue above does with `NO_QUESTIONS`, and never by
their words: `str()` of a finding is the sentence quoted below, and the
wording is free to change.

Two traps make a map look complete when it is not, and each has its own
finding. **Either base may be raised bare**: the kernel raises neither a plain
`DispatchError` nor a plain `ServiceError` itself, but both are public classes a
project's own code may raise, so a map with a row for every refusal under a
base and none for the base leaves it unanswered:

```text
nothing in the map answers DispatchError itself, though it answers every refusal under it, and DispatchError may be raised bare
```

**A subclass below its base never answers**: in an ordered table, the base's
row catches it first, so the subclass's row is dead and the subclass takes
the base's outcome:

```text
the row for ServiceConflict never answers: the row for ServiceError above it answers every ServiceConflict first
```

The second is reported for a table only. A callable written as branches
orders them in code, and a branch for a subclass below its base's is a body
that never runs, which the transport's own branch coverage reports; a table's order is data, which
coverage reads as one expression.

A refusal a transport defines itself, such as
[django-spec-html](https://artui.github.io/django-spec-html/)'s `UnsupportedMediaType`,
is not in `REFUSALS`: that transport maps it and tests it. Its row is still
read for the precedence trap, since a row nothing reaches is dead whoever's
refusal it names.
