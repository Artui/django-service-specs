# Relation writes

A write that creates or updates a row often writes its related rows in the
same call: an author and its books, a post and its tags. The mutation helpers
do that inside the service's transaction, reconciling the rows that arrived
against the rows that exist, and report what changed.

The helpers are ordinary functions a service calls. Dispatch knows nothing
about them: the spec's Validator checks the nested rows before the service
runs, and the helpers own persistence only.

## The helpers

- [`create_from_input(model, data, ...)`][django_service_specs.mutations.create_from_input.create_from_input]
  builds a row from `data`, saves it, then writes its relations.
- [`update_from_input(instance, data, ...)`][django_service_specs.mutations.update_from_input.update_from_input]
  writes only the fields whose value changed, with a minimal
  `save(update_fields=...)` (`auto_now` fields are added to it), then
  reconciles its relations. `update_fields=False` makes it a full save, and a
  list names the columns exactly.
- [`apply_input(instance, data)`][django_service_specs.mutations.apply_input.apply_input]
  sets the changed fields without saving, for a service that wants to see what
  the input would change before deciding to persist.
- [`delete_relations(instance, relations=...)`][django_service_specs.mutations.delete_relations.delete_relations]
  disposes of the rows `instance` owns, before a delete service removes
  `instance` itself. See [Deleting](#deleting).
- [`acreate_from_input`][django_service_specs.mutations.acreate_from_input.acreate_from_input],
  [`aupdate_from_input`][django_service_specs.mutations.aupdate_from_input.aupdate_from_input]
  and [`adelete_relations`][django_service_specs.mutations.adelete_relations.adelete_relations]
  are the async forms, for an `async def` service.

`data` is a dataclass, a mapping, or an object with a `__dict__` - usually the
validated values dispatch passes the service as `data`. A field holding
[`UNSET`][django_service_specs.types.unset.UNSET] is left alone, which is what
makes a partial update's omitted fields omitted. `field_map` renames input keys
onto model fields and `exclude_fields` drops keys. `m2m={name: rows}` assigns
many-to-many rows **that already exist**; writing the target rows from the
payload is a `ManyToManySpec`, and naming one relation in both is refused.

`relations={name: spec}` declares the related rows, one spec per relation,
and is the one map for every kind of relation.

## A worked example

An author and their books. `Author` has a `name`; `Book` has a `title`, a
decimal `price`, a `status` and a non-nullable foreign key `author`, whose
reverse accessor is `Author.books`. The input dataclasses are the ones
[Declaring an operation](declaring.md#the-dataclass-adapter) builds.

```python
--8<--
docs/examples/relations.py:write
--8<--
```

What each call does:

- **Create** with `{"name": "Ursula", "books": [{"title": "The Dispossessed",
  "price": "9.99"}, {"title": "Lathe", "price": 12.5}]}` writes the author,
  then both books pointing at it. The service's `ChangeResult` reports
  `ChildCollectionChange(relation="books", created=(1, 2))`, and the presented
  result is the author with both books, the prices rendered as `"9.99"` and
  `"12.50"`.
- **Update** with `{"pk": 1, "books": [{"pk": 1, "title": "The Dispossessed",
  "price": "10.99"}, {"title": "Always Coming Home", "price": "8"}]}` matches
  the first row to book 1 by its `pk` and updates it, creates the row with no
  `pk`, and removes book 2, which the input left out: `ChildSpec`'s default
  mode is `"replace"`, and because `Book.author` is not nullable the orphan is
  deleted. The report is `created=(3,), updated=(1,), deleted=(2,)`. The
  author's `name` was not sent, so `AuthorPatch` delivered it as `UNSET` and
  it was not written.
- **Update without `books`** leaves every book alone: the relation arrives as
  `UNSET`, and a relation the input omits is untouched. An explicit
  `"books": []` would have removed them all.
- **A row naming a book the author does not have** -
  `{"pk": 1, "books": [{"pk": 4, ...}]}` where book 4 is someone else's - is
  refused with `ServiceValidationError`, at
  `{"books": {0: {"non_field_errors": ["references Book [4], which this write did not match. ..."]}}}`.
  Saving a new row under a primary key it did not match would overwrite the
  row that holds it, so the write refuses rather than creating.
- **A malformed row** - a `status` of `"lost"` in the second book - is refused
  by the Validator before the service runs, as `InvalidArguments` at
  `{"books": {1: {"status": ["Select a valid choice. lost is not one of the available choices."]}}}`.

## The five relation specs

| Spec | Writes | Named by | Written |
| --- | --- | --- | --- |
| [`ChildSpec`][django_service_specs.relations.child_spec.ChildSpec] | A reverse foreign-key collection: rows whose `fk` points at the parent | The reverse accessor (`"books"` for `Author.books`) | After the parent's `save()` |
| [`ForwardRelationSpec`][django_service_specs.relations.forward_relation_spec.ForwardRelationSpec] | A `ForeignKey` or `OneToOneField` declared on the parent | The parent's field (`"author"` for `Post.author`) | Before the parent's `save()` |
| [`ReverseOneToOneSpec`][django_service_specs.relations.reverse_one_to_one_spec.ReverseOneToOneSpec] | The one row whose `OneToOneField` points back at the parent | The reverse accessor (`"profile"` for `Author.profile`) | After the parent's `save()` |
| [`GenericRelationSpec`][django_service_specs.relations.generic_relation_spec.GenericRelationSpec] | A `GenericRelation`: rows linked by content type and id | The `GenericRelation` on the parent | After the reverse kinds |
| [`ManyToManySpec`][django_service_specs.relations.many_to_many_spec.ManyToManySpec] | Target rows from payloads, then the membership | Either side's accessor (`"tags"` for `Post.tags`) | Last |

Each spec takes its required fields positionally and every option by keyword:
`ChildSpec(Book, "author", mode="merge")`.

The order is a property of the kind, not of how the `relations=` mapping is
spelled: a forward target has to exist before the parent is saved, and a
membership needs both rows saved.
[`RelationPhase`][django_service_specs.relations.relation_phase.RelationPhase]
names the sequence. Within one phase, relations are written in the order they
are declared.

How each kind reads its value:

- **Omitted** leaves the relation untouched, for every kind.
- **A forward relation set to `None`** clears the parent's column and leaves
  the row it pointed at alone: a forward target is not the parent's, and may be
  shared. A mapping writes the target row - creating one, or with a
  `match_key`, updating the row it names.
- **A reverse one-to-one set to `None`** removes the related row by the
  `orphan` rule below, because that row *is* the parent's. A mapping updates
  the existing row, or creates and links one.
- **A collection** (child, generic, many-to-many) is reconciled: incoming rows
  are matched to existing ones by `match_key` (`"pk"` by default), matched rows
  are updated, the rest are created, and in `"replace"` mode the existing rows
  the input left out are removed. `"merge"` mode only upserts. A `null` row
  is refused, every one of them and before any row is written, with
  `"This field cannot be null."` under the row's `non_field_errors`: a
  declaration may let one through (`list[Row | None]`), and nothing in a
  relation spec says what it stands for.

### Matching, scope and orphans

A child collection, a generic relation and a reverse one-to-one match inside
the parent's own rows, so a key that matches nothing there cannot name anyone
else's row. A forward relation and a many-to-many match against rows the
parent does not own, so they take a **`scope`**: a queryset, or a callable
resolved from `context` (`lambda user: Author.objects.filter(owner=user)`),
of the rows this caller may write. Without a scope the spec is create-only,
and a payload carrying a `match_key` raises `ImproperlyConfigured` rather than
letting any caller write any row of that model by guessing a key. A key
outside the scope is refused with `ServiceValidationError`, at the row.

What removing a row *does* is the **`orphan`** setting of a child collection,
a reverse one-to-one or a generic relation. `"auto"`, the default, reads the
schema: a nullable link is set to `None` (**unlinked**, like
`on_delete=SET_NULL`), a non-nullable one is **deleted** (like `CASCADE`).
`"unlink"` and `"delete"` say it outright, for a spec that means one of them:
under `"auto"`, a later migration adding `null=True` would turn a destructive
`"replace"` into a non-destructive one with nothing in the spec changing. A
many-to-many target is shared, so a dropped member only loses its membership,
and is reported as `unlinked`.

A many-to-many with a custom `through` model is not covered: the helpers let
Django write the through row, which cannot carry the extra columns a custom
through model exists for.

### Row services

A row whose write has behaviour of its own - side effects, derived columns, an
external call - takes a `create_service`, an `update_service` and, where rows
are removed, a `delete_service`. The spec keeps what it never delegates: which
rows exist, which incoming row matches which existing one, and what happens to
the ones left over. The service is called once per row the helper has already
decided about, with `data`, the `parent` (except on a forward relation, whose
target is written before the parent exists), the `instance` for an update, and
any keys of the helper's `context=` mapping it declares. That mapping is how a
row service or a `scope` callable sees the acting user: the operation's service
declares `user` and passes `context={"user": user}` on to the helper.

Row services run with `atomic=False`, inside the transaction the operation
already holds. Declaring one beside the shaping options it replaces
(`field_map`, `exclude_fields`, `m2m`, nested `relations`) is
refused at construction, because they would configure nothing. A
`delete_service` owns the disposal, so its rows are reported as `removed`
rather than guessed into `deleted` or `unlinked`. In the async helpers, a row
service must be `async def`.

## What changed

Every helper returns a
[`ChangeResult`][django_service_specs.mutations.change_result.ChangeResult]:

- `instance` and `created`.
- `changes`: a [`FieldChange`][django_service_specs.mutations.field_change.FieldChange]
  with `old` and `new` for every field whose value differed, `old` being
  `UNSET` on a create. `changed_fields` lists their names.
- `children`: a
  [`ChildCollectionChange`][django_service_specs.mutations.child_collection_change.ChildCollectionChange]
  per collection - a child, generic or many-to-many relation - holding the
  primary keys `created`, `updated`, `deleted`, `unlinked` and `removed`.
  `get_child_change(name)` finds one.
- `relations`: a
  [`RelatedObjectChange`][django_service_specs.mutations.related_object_change.RelatedObjectChange]
  per one-row relation - a forward relation or a reverse one-to-one - holding
  one
  [`RelationOutcome`][django_service_specs.mutations.relation_outcome.RelationOutcome]
  and the `pk` it is about. `get_relation_change(name)` finds one.

A `ChangeResult` is falsy when nothing changed.

## Deleting

A delete service that has to take a row's related rows with it calls
`delete_relations` with the same map the writes use, then deletes the row:

```python
--8<--
docs/examples/deleting.py:delete
--8<--
```

The database's own cascade would remove these books as well, and report
nothing. The helper matters where the database will not cascade, or should
not be the one to:

- **A `PROTECT` foreign key**, which refuses the parent's delete while a child
  row exists.
- **A soft delete**, which removes no row, so Django never cascades through it.
  The instance outlives its cascade, and its cached relations are brought in
  line with the removal, so it renders without the rows it lost.
- **A row service**: a spec's `delete_service` sees each row go, which a
  database cascade never calls.
- **A report**: the returned `ChangeResult` names every row disposed of, as the
  example returns them.

The rule is the one a write follows when it removes a row, applied to every
row the instance owns. A child, generic or reverse one-to-one row is disposed
of after its own declared relations, so a non-nullable grandchild goes first,
and each is deleted, unlinked or handed to its `delete_service` by the spec's
`orphan` setting. A many-to-many loses its membership and its target rows
survive. A forward relation is reported `untouched`: the row it points at is
not the instance's, and refusing it would make a map that is right for writing
impossible to cascade.

## Errors from a nested write

A refusal inside a row is **re-rooted under the row's address**, in the tree
[Arguments and refusals](arguments.md#the-refusal-tree) describes, and keeps
its class: a `ServiceValidationError` from a row stays one, an
`InvalidArguments` stays one, because the class says who refused. A grandchild's
refusal carries both addresses.

Django's own failures to write a row's data - a value a field cannot coerce, a
key the model has no field for - carry no detail and would otherwise escape as
an unhandled error naming no row. They become `InvalidArguments` at the row.

Code the caller wrote is treated differently. Any other error a row service, a
`scope` callable or an `m2m` callable raises passes through **untouched**, at
any depth: reading its `TypeError` as a refusal of the arguments would report
the caller's own bug as the client's mistake. An `IntegrityError` is left alone
too: a constraint is a conflict with rows that exist rather than a shape, and
the backend's message can quote another row's values.
