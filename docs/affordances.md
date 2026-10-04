# Affordances

Some operations are impossible right now as a fact about the world rather than
about the caller: an archived note cannot be renamed, refunds are closed while
the books are. An **affordance** says so on the operation, once, so every
transport reads the same rule. A call is refused with a stable code beside the
sentence, and a transport listing operations before anyone calls them can leave
out one that no call could pass.

```python
--8<--
docs/examples/affordances.py:declare
--8<--
```

[`ServiceSpec`][django_service_specs.specs.service_spec.ServiceSpec]'s
`affordances` takes a sequence of conditions, each an
[`Affordance`][django_service_specs.types.affordance.Affordance]
with three fields:

- **`code`** names the rule, never the state that tripped it, and does not
  change when the sentence is reworded. It is what a transport or a client
  branches on.
- **`reason`** is the sentence people and models both read, and the message
  of the refusal. Say what is not possible and, where it helps, what would
  make it possible.
- **`when`** is true when the operation **is** available.

Not a fact about the caller: that is `permissions`, which is always checked
first, so a principal who may not see a row is never told what state it is in.

## Two kinds of condition

`when`'s type decides which kind it is. It is derived, never declared, so it
cannot drift from what it describes:

- **An ORM boolean expression** - a `Q`, an `Exists`, a lookup - is a
  condition on the row. It reads exactly as `Note.objects.filter(when)` does,
  relations included, and is answered in SQL: every condition on the row in
  one query, however many are declared. A `NULL` is not true.
- **A callable** is a condition on nothing in particular. It is called with
  the pool seeds it names - `user`, `progress` and any registered
  [pool seed][django_service_specs.pool.pool_seeds.PoolSeeds], like
  `read_only` above - and never with the call's target, its validated values
  or a client's argument: the caller does not get to decide whether the
  operation is available. Its result is read for truth, so a callable that
  returns nothing means unavailable.

**A Python callable over the row is refused.** A rule that has to run once per
row turns every list reporting availability into a query per row, and
prefetching does not fix it. A rule the ORM cannot express is not an
affordance: it stays in the service, which raises a
[`ServiceConflict`][django_service_specs.services.service_conflict.ServiceConflict]
and advertises nothing.

## Refused where it is written

Every mistake below raises `ImproperlyConfigured` when the spec is built, so it
fails at import rather than on the first call through a transport that never
asked:

- a `code` or `reason` that is not a non-empty string;
- an ORM expression that is not boolean, such as `F("title")`;
- a callable naming `data`, `instance`, `collection`, `result` or `queryset`,
  the names dispatch seeds per call;
- a `when` that is neither an expression nor a callable;
- `affordances` that is not a sequence - a single `Affordance`, a set whose
  order would decide which refusal a caller sees, a generator the first call
  would exhaust;
- an entry that is not an `Affordance`, or a code declared twice;
- a condition on the row on an operation with a `collection_selector_spec`,
  which has no single row to answer it against.

## Offering an operation

A transport that lists operations before anyone calls them - an MCP server
building its tool list, an agent assembling its next toolset - asks
[`unmet_operation_affordance`][django_service_specs.affordances.unmet_operation_affordance.unmet_operation_affordance]
for the first callable condition not met now, or `None`.

```python
--8<--
docs/examples/affordances.py:offer
--8<--
```

Conditions on the row are skipped without a query, because at list time there
is no row; they go on being answered at the call. A
[`SelectorSpec`][django_service_specs.specs.selector_spec.SelectorSpec]
answers `None`.
[`operation_affordances`][django_service_specs.affordances.operation_affordances.operation_affordances]
returns the conditions that would be asked, so a transport can skip building a
pool when there are none.

**Build the pool the way the call's would be**:
[`base_pool`][django_service_specs.pool.base_pool.base_pool] with the same
`seeds=`, and `reserved=seeds.reserved` beside it, or a condition reading a
registered seed is asked without it. A condition that raises propagates: one
that cannot be answered is not a no.

**The answer is advisory.** An operation listed a moment before a condition
flips is refused when it is called, with the code this would answer if asked
again then. A condition driven by a clock has no event, so nothing announces
the moment it flips.

## Enforcing at the call

[`dispatch`][django_service_specs.dispatch.dispatch.dispatch] and
[`adispatch`][django_service_specs.dispatch.adispatch.adispatch] answer a
service spec's affordances themselves, after object-level authorization and
the Validator and before the run's transaction opens. The first one not met
refuses the call with
[`ActionUnavailable`][django_service_specs.services.action_unavailable.ActionUnavailable],
carrying its `reason` as the message and its `code`, and the service never
runs. A callable condition sees every registered seed, an HTTP adapter's
`request` among them. A selector spec's `affordances` refuse nothing: they are
answers about each row.

```python
--8<--
docs/examples/affordances.py:dispatch
--8<--
```

[`enforce_affordances`][django_service_specs.affordances.enforce_affordances.enforce_affordances]
is that step, exported for a transport that runs a service itself. It calls it
after authorization and validation and before the service, with the pool
seeds' `reserved` set, or a condition the direct path refuses is skipped on
that one:

```python
--8<--
docs/examples/affordances.py:enforce
--8<--
```

Declaration order decides which refusal a caller sees, and nothing after the
first unmet condition runs. A condition on the row is read from the table, not
from the instance in hand. Two other answers come from the row: one that
vanished since it was resolved is
[`ServiceNotFound`][django_service_specs.services.service_not_found.ServiceNotFound],
and a condition on the row reached with no model instance to answer it for is
`ImproperlyConfigured`.

`ActionUnavailable` is a `ServiceConflict`, so a transport that has never heard
of it still answers a conflict. One that wants the code matches it before its
generic conflict and service-error handlers.

[`error_response`][django_service_specs.http.error_response.error_response]
answers it at 409, with the code beside the detail a client already reads:

```json
{"detail": "An archived note cannot be renamed. Restore it first.", "code": "note_archived"}
```

## Asking for one more value

A service that gets far enough to discover it needs something else - usually
because of what it found - raises
[`AdditionalInputRequired`][django_service_specs.services.additional_input_required.AdditionalInputRequired]
with a message and a `schema`. It is not a validation error, because what was sent is not
wrong, and it is a
[`ServiceError`][django_service_specs.services.service_error.ServiceError], so
a transport that has never heard of it still reports why the operation did not
complete.

```python
--8<--
docs/examples/affordances.py:confirm
--8<--
```

`schema` describes what is missing, keyed by the argument the service expects
it back under. The answer comes back as an ordinary argument on the next call,
so the operation declares it like any other, and there is no session to
resume. `error_response` answers 422, with the schema beside the detail when
there is one:

```json
{"detail": "2 archived notes will be deleted. Confirm to proceed.", "schema": {"confirmed": {"type": "boolean"}}}
```

## Declaring idempotency

`ServiceSpec(idempotent=True)` states that repeating the call with the same
arguments leaves the state making it once did. Nothing in this package reads
it, because idempotency is a property of the service the author writes, not
something a dispatcher can arrange; it is stated once so that a retry policy, a
queue's redelivery handling and an agent tool annotation all read the same
answer. `None`, the default, means undeclared, so a transport can tell "nothing
was said" from a declared `False`. `atomic` answers a different question: a
single call is all-or-nothing, not that a second one is a no-op.

## Answers for each row of a list

A `SelectorSpec` declares which operations' affordances each of its rows is
answered for, keyed by a name the caller chooses:

```python
--8<--
docs/examples/affordances.py:selector
--8<--
```

The values are the `ServiceSpec`s themselves rather than registry names, so a
read takes no registry dependency and the declaration is the one the operation
enforces. Each answer is named `affordance__<name>__<code>` - here
`affordance__rename__notes_read_only` and `affordance__rename__note_archived`.
A name colliding with a key of the selector's `annotations`, or two entries
generating one name, is refused when the spec is built, because a generated
answer silently replacing a project's own annotation is the worst way for this
to fail.

Dispatch answers them wherever the selector runs: a selector spec's own, or a
service spec's output selector. On a queryset, every answer joins the spec's
`annotations` in the one `.annotate()` call shaping makes, before
`extend_queryset` and before a transport pages the rows, so the list still
costs one query and a page's rows carry what the whole list would have. A
condition on the row is the same correlated `EXISTS` the call is refused by,
so the list and the call agree about every row; a callable condition is
answered once per call, against the seeds alone, as it is at the call. Rows a
selector returns directly are answered too: instances by one query per model
class, mappings with their callable answers only, because a mapping has no row
to find.

[`present`][django_service_specs.dispatch.present.present] then adds an
`affordances` object to every row it presents, and so does every response the
HTTP views serve and every payload
[`render_for_audience`][django_service_specs.dispatch.render_for_audience.render_for_audience]
hands an agent, `reason` included:

```python
--8<--
docs/examples/affordances.py:rows
--8<--
```

```json
[
  {"id": 1, "title": "Draft", "affordances": {"rename": {"available": true}}},
  {
    "id": 2,
    "title": "Old",
    "affordances": {
      "rename": {
        "available": false,
        "code": "note_archived",
        "reason": "An archived note cannot be renamed. Restore it first."
      }
    }
  }
]
```

Each name answers with the first condition its row does not meet, in
declaration order, as the call would refuse. A row deleted between the selector
returning it and its answers being asked is `{"available": false}` with no
`code` and no `reason`, because no condition's sentence is true of a row that
no longer exists. A selector spec's `affordances` refuse nothing: the archived
note is still listed, and says why it cannot be renamed.

[`spec_output_schema`][django_service_specs.schema.spec_output_schema.spec_output_schema]
describes the object on each item, with or without a projection, and with each
name's codes enumerated so a client can switch on them:

```json
{
  "type": "object",
  "properties": {
    "rename": {
      "type": "object",
      "properties": {
        "available": {"type": "boolean"},
        "code": {"type": "string", "enum": ["notes_read_only", "note_archived"]},
        "reason": {"type": "string"}
      },
      "required": ["available"]
    }
  },
  "required": ["rename"]
}
```

Presenting refuses what would lose or garble the answers: a spec declaring
`affordances` with no presenter, a presented row that is not an object or
already has an `affordances` key, and a row that did not come through the
selector declaring them. Dispatch refuses a condition on the row beside mapping
rows, and a row that is neither a model instance nor a mapping.

A target lookup - a service spec's `instance_selector_spec` or
`collection_selector_spec` - that declares `affordances` has its rows answered
too, as djangorestframework-services' dispatch answers them, and nothing
presents them: a service spec presents only its output selector's answers. The
declaration costs a subquery, or a query of its own when the lookup returns a
bare row, and buys nothing. Declare the answers on the read that lists the
rows, or on the output selector.

[`shape_queryset`][django_service_specs.selectors.shape_queryset.shape_queryset]
answers none: a transport that shapes a selector's rows itself, rather than
through dispatch, hands `present` rows with no answers on them, and is refused.
