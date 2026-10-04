# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `Affordance(code, reason, when)` and `ServiceSpec.affordances`: when an
  operation is possible right now, as a fact about the world rather than about
  the caller. `when` is an ORM boolean expression, a condition on the row
  answered in SQL with every one in a single query, or a callable over the
  pool's seeds, which never sees the call's target, input or arguments. A
  Python callable over the row, a non-boolean expression, a code declared twice
  and a condition on the row beside a `collection_selector_spec` are refused at
  construction.
- `enforce_affordances`, `unmet_operation_affordance` and
  `operation_affordances`, in the new `affordances` subpackage, with
  djangorestframework-services' signatures. The first refuses a call with
  `ActionUnavailable`, in declaration order, and a row that vanished since it
  was resolved with `ServiceNotFound`. The other two tell a transport listing
  operations which ones no call could pass right now, skipping conditions on
  the row without a query.
- `ActionUnavailable`, a `ServiceConflict` carrying the unmet affordance's
  `code`. `error_response` answers it at 409 with `code` beside `detail`.
- `AdditionalInputRequired(message, *, schema=None)`, a `ServiceError` a
  service raises when it needs one more value, with `schema` keyed by the
  argument it expects back. `error_response` answers it at 422, with `schema`
  beside `detail` when there is one.
- `ServiceSpec.idempotent`: whether repeating the call leaves the state making
  it once did. Declaration-only, and `None`, the default, means undeclared, so
  a declared `False` is told apart from silence.
- `SelectorSpec.affordances`: a mapping from a name to the `ServiceSpec` whose
  affordances a list's rows are answered for. Each answer is named
  `affordance__<name>__<code>`, and a name colliding with an `annotations` key
  or with another entry's is refused at construction. `dispatch` and
  `adispatch` answer them wherever the selector runs, a service spec's output
  selector included, and a target lookup's too, though nothing presents
  those: on a queryset in the one `.annotate()` call shaping
  makes, before `extend_queryset` and before `paginate_output` slices it, so
  the list costs no extra query and a page's rows carry their answers; on
  instances a selector returns directly by one query per model class, and on
  mappings with the callable answers only. A callable condition is answered
  once per call, against the seeds alone. `present`, `apresent`,
  `present_for_audience` and the HTTP views then add an `affordances` object
  to every presented row: per name `{"available": true}`, or the first unmet
  condition's `code` and `reason`, or a bare `{"available": false}` for a row
  deleted before it was asked. `spec_output_schema` declares that object on
  the item, codes enumerated, with or without paging and a projection. A
  spec declaring `affordances` with no presenter, a presented row that is not
  an object or already has an `affordances` key, a row condition beside
  mapping rows, and a row that is neither an instance nor a mapping are
  refused as `ImproperlyConfigured`.
- `dispatch` and `adispatch` answer a service spec's `affordances`
  themselves: after object-level authorization and the Validator, and before
  the run's transaction opens, so a principal who may not see the row is
  never told what state it is in and a refusal never opens a transaction. The
  first one not met refuses the call with `ActionUnavailable` and the service
  never runs. A callable condition sees every registered seed. `adispatch`
  answers them inside its one executor hop. A selector spec's `affordances`
  refuse nothing.
- `progress=` on `dispatch` and `adispatch`: the transport's
  `ProgressReporter`, seeded under the reserved name `progress` into the pool
  of the call's run (the service, or a selector spec's own selector) and of
  that spec's callable affordance conditions, as it is; a falsy reporter is
  kept. `base_pool` takes the same keyword. With no reporter the pool carries
  `null_progress`, so a callable that declares `progress` runs on every
  transport; a target or output selector, and its affordance conditions,
  always get `null_progress`. `ProgressReporter` and `null_progress` keep
  djangorestframework-services' signatures.
- `paginate_output(rows, *, page=None, limit=None, max_page_size=None)`,
  `DEFAULT_PAGE_SIZE` and `OutputPage`: a list result's value sliced into the
  one page a transport serves, and `OutputPage.envelope(rendered)` wrapping the
  presented rows as `{items, page, totalPages, hasNext}`. Out-of-range values
  clamp at both ends and the envelope reports the page actually served; a
  queryset is counted before it is sliced, so a page past the end is never an
  unbounded `OFFSET`. A `Manager` is paged as its `.all()`. The names a
  caller pages by and the ceiling are the transport's, and `SpecView` does
  not page. All three keep djangorestframework-services' signatures.
- `spec_output_schema(spec, *, paginate=False, projection=None,
  handle_description=None)`: `paginate=True` describes a list as the page
  envelope and changes nothing that is not a list, which stays a bare array by
  default; `projection=` describes the projected payload, applied to the item
  and never to the array or the envelope.
- `AudienceProjection`, `audience_projection_for_spec`, `project_payload`,
  `annotate_output_schema` and `present_for_audience`: the `FieldMarking`s an
  `Output` declares, applied to the presented value and to the output schema
  for a caller that names an audience. A hidden field is dropped from both, a
  choice is spoken by its display with its schema's stated `type` restated to
  match, a display two choices share is listed once, and a handle keeps its
  value and takes the transport's `handle_description`. djangorestframework-services
  states neither the restated `type` nor the single listing, so its projected
  schema refuses rows its own payload serves. A mount's `overrides=` are layered over the
  declaration, and two fields left marked as the label are refused, naming
  both. `present`, and so every HTTP response, applies no marking.
  `present_for_audience` is `present` plus the projection, as
  djangorestframework-services' `render_for_audience` is its serializer
  render plus the projection, and it is named apart because that one takes
  the view and request its serializer reads.
- `ValueFormatter(render, produces, schema=None)`, `FieldMarking.formatter`
  with the `FieldMarking.formatted()` and `FieldMarking.timestamp()`
  constructors, and `AudienceProjection.formatter(name)`, with
  djangorestframework-services' signatures. A formatter renders one field's
  value for an agent audience and declares the JSON type it produces:
  `project_payload` serves the rendered value, and `annotate_output_schema`
  restates the property as that type, keeping its `title` and `description`.
  It wins over a choice's display and never applies to a `HANDLE`. A null
  passes through unformatted, so a property whose type admits `"null"` keeps
  admitting it, which djangorestframework-services does not do.
  `ValueFormatter.timestamp()` renders a date-time in Django's active time
  zone.

### Changed
- An integral decimal is an integer. `coerce_flat` reads `"5.0"` and `"5."` as
  5, as Django's and DRF's `IntegerField` do, for a parameter and for each
  integer element of an array; `"5.5"` is still refused. The shape check
  accepts an integral float such as `5.0` for an `integer`, as JSON Schema
  does, and hands the Validator an `int` at every level the declaration
  reaches. `bool`, NaN and the infinities are refused as before, and a
  `number` keeps its float.
- A service with nothing to present, at a `success_status` other than 204,
  answers an empty body with no `Content-Type`, at the caller's status, from
  `SpecView`, `AsyncSpecView`, `dispatch_request` and `adispatch_request`.
  They wrote `null`. A read whose value is `None` still answers `null`. A 204
  no longer carries `Content-Type: text/html` either.
- Dispatch refuses a deactivated principal. `dispatch` and `adispatch` raise
  `PrincipalUnavailable` for an authenticated principal whose `is_active` is
  false, before the shape check and with or without a grant, by the rule the
  HTTP entry points and `resolve_principal` already applied: a principal with
  no `is_active` reads as active, and anonymous goes on to the permission
  check. A caller that hands dispatch such a user object reached the
  permission check in 0.3.0, and the stock permission classes pass one.
- Every pool dispatch builds carries `progress`, so a callable taking
  `**kwargs` receives it beside `user`.

### Fixed
- A `Parameter` with a list or dict default was unhashable, although a frozen
  declaration reads as hashable. `default` now takes no part in the hash, so
  `hash()` no longer raises `TypeError`; equality still compares it, and the
  reported value is unchanged.
- A list selector returning a `Manager`, such as `Note.objects`, could not be
  presented: `present` raised `TypeError`, on every transport, unless the spec
  declared shaping. Dispatch now takes the Manager's `.all()`, as a selector
  returning every row means.

## [0.3.0] — 2026-09-29

### Added
- `items_nullable` on `Parameter` and `OutputField`: whether a `null` may
  stand where an array's element would, as `list[int | None]` declares it.
  It is independent of `nullable`, which remains the array's own, and it
  needs a declared `items`. The dataclass and pydantic adapters set it from
  the element's annotation, the shape check keeps a null element where it is
  set, and both schemas state it on `items`, choices included.
- `dispatch_request` and `adispatch_request`, in the new `http` subpackage: a
  spec served from a hand-written Django view, answered as JSON with no API
  framework in between. The principal is `request.user`, anonymous included,
  and an authenticated account with `is_active` false is refused as
  `PrincipalUnavailable`. A not-found result is 404; a success is the
  presented value, bare, at the caller's `success_status`, else 204 for a
  service with nothing to present and 200 otherwise. The async one reads the
  request off the event loop, since `request.user` is a session query.
- `SpecView` and `AsyncSpecView`: one spec as a class-based view. A selector
  spec answers GET and HEAD and a service spec POST, unless `methods` names
  others; any other method is Django's own 405 with a matching `Allow`. The
  URL kwargs are arguments, so a route capturing one its spec does not declare
  raises `ImproperlyConfigured` rather than answering the client 400, under
  either `unknown_arguments` policy: the route is the host's. A view with no
  spec is refused by `as_view()`.
  Nothing is exempted from CSRF: that is the host's middleware.
- `request_arguments`: a request read as arguments. GET and HEAD read the
  query string; any other method a JSON object body as it is, or a form or
  multipart body, which is parsed for PUT, PATCH and DELETE too rather than
  arriving empty. A flat source takes every value for an array parameter and
  the last otherwise, reads a blank value as absent unless `""` is one the
  parameter can take (a plain string, or one whose choices name it), drops
  `csrfmiddlewaretoken`, and goes through `coerce_flat`. URL kwargs are
  coerced and merged last, so the route wins a clash. A malformed JSON body,
  or one that is not an object, is `InvalidArguments` under
  `non_field_errors`; a body in any other format is `UnsupportedMediaType`
  rather than no arguments; files are not arguments.
- `error_response`: either family of refusal as JSON, at the statuses
  djangorestframework-services answers with. `InvalidArguments` and
  `ServiceValidationError` are 400 and both bodies are field maps, a service's
  string or list detail under `non_field_errors`; `NotPermitted` and
  `PrincipalUnavailable` are 403, `ServiceNotFound` 404, `ServiceConflict`
  409, any other `ServiceError` 422, `UnsupportedMediaType` 415, each as
  `{"detail": message}`. Never 401.
- `UnsupportedMediaType`, a `DispatchError`: a request body that is neither
  JSON nor a form, refused rather than read as no arguments, since an
  operation whose parameters are all optional would run with nothing and
  answer success.
- `SpecFormView`: a `ServiceSpec` whose Validator is a `FormValidator`, served
  as the page its form is. GET runs the spec's class-level permission check
  and renders `template_name` with an unbound `form`, `view` and `spec`. POST
  runs the same check before it builds the form from the post, since a
  refused post is answered with the page and dispatch's shape check comes
  before its own permission check, and hands dispatch the grant so the check
  runs once. It
  reads the post through the form's own widgets, so a checkbox is a boolean
  and a multi-select a list, and neither the CSRF token nor a submit button
  is an argument; a blank field is absent, and a number, date or date-time in
  one of the field's input formats is sent on in the form the shape check
  reads. A URL kwarg the spec does not declare raises `ImproperlyConfigured`
  under either `unknown_arguments` policy, since the route is the host's. A
  success redirects to `get_success_url(result)`, `success_url` by default;
  a refusal re-renders the bound form carrying that refusal and none of the
  form's own errors, at `error_response`'s status, since the page's form is
  bound to no row and its uniqueness check would call an update's unchanged
  value taken. A denial or a missing row is Django's own `PermissionDenied`
  or `Http404`.
  `as_view()` refuses a view with no `ServiceSpec`, no `FormValidator` or
  nowhere to redirect. Sync only.
- `add_argument_errors`: a refusal tree placed on a bound form with
  `form.add_error`, beside the form's own errors and never duplicating one. A
  field's key goes on the field; `non_field_errors`, Django's `"__all__"` and
  any key the form has no field for go to its non-field errors, the last
  prefixed with its dotted path.

### Fixed
- The shape check refuses NaN and the infinities for a `number` and for an
  element of an array with no `items`, with `"Enter a number."` at the
  value's address, as it already did for a decimal; every other type already
  refused one as the wrong type. JSON has no spelling for either, so they are
  outside the number type rather than a stricter check. Python's decoder
  reads an overflowing literal such as `1e400` as an infinity, so a JSON body
  carrying one reached the Validator, and so could a Python caller's. Inside
  a container nothing declares, the contents stay the Validator's, as for
  every other rule.
- `FormValidator` read a decimal argument with three places through the
  active locale when its field was localized, so under a locale whose
  thousands separator is a dot, `"1.500"` validated as 1500. A number
  field's string argument is now bound as the `Decimal` it spells, which
  no locale reinterprets. `SpecFormView` reached it from an ordinary form:
  `1,500` typed on a German page is sent on as `"1.500"`.
- `ServiceValidationError` raised with a lazy translation replaced it with
  its default `message`, since a lazy string is not a `str`. The lazy string
  is now the message, and renders in the language active where it is read.
- An operation declaring `list[X | None]` refused every null element before
  its Validator ran, although both adapters accept one: the declaration had
  no way to say the element was nullable, so the shape check read a gap as a
  wrong type. The output schema claimed the same elements were never null.
- A collection relation (child, generic or many-to-many) wrote a `null` row
  as a row with no fields, created or matched on nothing. It is now refused
  with `"This field cannot be null."` under that row's `non_field_errors`,
  every null row at once and before any row is written.
- The arguments page's HTTP-shaped ladder answered a `ServiceValidationError`
  422 and a plain `ServiceError` 400, the reverse of the statuses
  djangorestframework-services answers, and left `ServiceNotFound` and
  `PrincipalUnavailable` to fall through. It now answers as `error_response`
  does, and a test holds the two to each other.

## [0.2.0] — 2026-09-29

### Added
- `FormValidator`: a Django form class as a Validator. The form's fields become
  the operation's `Parameters`, with their JSON types, formats, choices and
  help, and validation is the form's own - its field validators,
  `clean_<field>()`, `clean()` and, on a `ModelForm`, the model's validation
  and uniqueness checks. A `ModelForm` is built on a copy of the resolved row,
  so an update's uniqueness check excludes that row without the form writing
  its cleaned values onto the row the service receives. A field the form
  cannot describe is refused where the Validator is built, by form, field and
  class. The form's own `__all__` errors come back under `non_field_errors`,
  like every other refusal.
- JSON Schema from the declarations: `spec_input_schema()` and
  `spec_output_schema()` describe an operation, and `parameters_schema()` and
  `output_schema()` a bare declaration. The schema is read from `Parameters`
  and `Output` alone, so it is one dialect whichever library declared the
  spec. The input schema closes every object the `UnknownArguments` policy
  closes and leaves a defaulted parameter out of `required`; the output schema
  is an array for a list, and nullable wherever the operation may return
  nothing. Each is flat, with no `$defs` or `$ref`.
- A pydantic adapter, with the `pydantic` extra: `PydanticValidator` and
  `PydanticPresenter` read a model into `Parameters` and `Output` from the
  same annotation table as the dataclass adapters, so a model and a dataclass
  declaring one field declare one parameter. Aliases are read as pydantic
  reads and writes them, and pydantic's refusals come back in the kernel's
  error tree, addressed by parameter name. A model that contains itself is
  described four levels deep and validated in full. The presenter reads rows,
  related managers, objects and mappings through `model_dump`. Both are
  exported from `django_service_specs.adapters.pydantic` alone: the package
  root never imports pydantic. Needs pydantic 2.11 or later.

### Changed
- `OutputField` refuses a `format` on anything but a string, as `Parameter`
  already did. Every format names what a string decodes into, and the JSON
  Schema states it beside the type, so a format on a number described a value
  the output never holds.

### Fixed
- The dataclass adapters declare a list of choices - `list[Literal[...]]`, a
  list of an `Enum` or of Django `Choices` - with its choices, which constrain
  each element. They declared a plain array of strings, so the shape check
  passed any string on to the Validator and a JSON Schema left the choices
  out.
- On Python 3.10, `DataclassValidator` names a refused parametrized generic
  as it was written, `set[int]` rather than `set`.
- The docs site no longer publishes the example sources and their bytecode
  beside its pages. `docs/` is also a Python package, so the suite can run
  every example, and MkDocs copied its `.py` files and `__pycache__` into the
  site. The pages are unchanged: they take the examples through snippets.

## [0.1.0] — 2026-09-29

### Added
- The kernel, whole. An operation is declared once as a `ServiceSpec` (a write)
  or a `SelectorSpec` (a read), and `dispatch()` runs it from any transport in a
  fixed order: the shape check and the closed argument set, class-level
  authorization, target resolution, object-level authorization, validation with
  the resolved row in the Validator's context, the run, and the output
  selector. `adispatch()` does the same with one executor hop for the whole
  prelude; only the run may be `async def`.
- A missing row is **reported**, as `DispatchResult(kind="not_found")`, never
  raised, so each transport answers it in its own terms. `present()` refuses to
  render one as a success.
- `Parameter` and `Parameters`: what an operation takes, as JSON types with
  formats, choices, nullability, and nesting for an object's fields or an
  array's rows. `check_arguments()` refuses every problem in one
  `InvalidArguments` tree, at every level: `{"books": {1: {"title": [...]}}}`,
  with a row's own message under `non_field_errors`, as Django and DRF place
  it. `coerce_flat()` reads argv-shaped strings into what typed JSON gives, and
  refuses a nested parameter by name rather than guessing.
- `UnknownArguments.REJECT` by default: an argument nobody declared is refused
  at its own address. `IGNORE` drops it instead, at every level.
- `Validator` and `ValidationContext`, with `DataclassValidator` and
  `DataclassPresenter` as the reference adapters: plain dataclasses, nested
  ones and lists of them, `Decimal`, `datetime`, `date`, `Literal`, `Enum` and
  Django's `Choices`. With `USE_TZ` on, an offset-less date-time is made aware
  in the current time zone, as Django's forms do. `bind_arguments()` runs the
  shape check and the Validator for a transport that binds input itself.
- `PermissionCheck`, with `Unrestricted()` as the explicit allow. An operation
  that declares no permission check is refused at registration and at dispatch,
  because off HTTP there is no view whose policy it could inherit. A transport
  that has already authorized passes a `Grant`, bound by identity to one spec
  and one principal and refusing to be serialized, so it cannot cross a queue.
- `resolve_principal()` turns an identifier into a user who may act, and
  refuses a missing, malformed or deactivated one with `PrincipalUnavailable`.
  Never an anonymous user.
- Two error families that say who refused. `DispatchError` (`InvalidArguments`,
  `NotPermitted`, `PrincipalUnavailable`) is dispatch refusing before the
  operation ran; `ServiceError` (`ServiceValidationError`, `ServiceConflict`,
  `ServiceNotFound`) is the operation refusing. Neither subclasses the other.
- `Output`, `OutputField`, `FieldMarking` and `FieldAudience`: what an
  operation returns, declared beside what it takes, with a marking for each
  field's audience.
- `PoolSeeds`: a project's own values in every dispatched callable's keyword
  pool, such as a tenant or a clock. A seed's name is reserved, so a spec
  declaring an argument by that name is refused rather than left to meet the
  seed in one pool.
- Relation writes: `ChildSpec`, `ForwardRelationSpec`, `ReverseOneToOneSpec`,
  `ManyToManySpec` and `GenericRelationSpec`, declared in one `relations=` map
  and applied by `create_from_input()`, `update_from_input()` and their async
  forms, with a `ChangeResult` describing what changed. Each spec takes its
  required fields by position and everything else by keyword. `apply_input()`
  sets a row's changed fields without saving.
- `delete_relations()` and `adelete_relations()`: the cascade a delete service
  runs before removing a row, through the same map the writes use, where the
  database will not cascade or should not be the one to - a `PROTECT` key, a
  soft delete, a row service that must see each row go. Owned rows are
  disposed of by each spec's `orphan` rule, a many-to-many loses only its
  membership, and a forward relation is left alone.
- A relation write refuses at the row. A `ServiceValidationError` or an
  `InvalidArguments` from a row is re-rooted under the row's address and keeps
  its class, and Django's own write failures on a row become `InvalidArguments`
  there. Any other error raised by a row service, a `scope` or an `m2m`
  callable passes through untouched, at any depth, and so does an
  `IntegrityError`.
- `SpecRegistry`: a named, taggable set of specs for a project exposing
  operations over more than one transport.

[Unreleased]: https://github.com/Artui/django-service-specs/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/Artui/django-service-specs/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Artui/django-service-specs/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Artui/django-service-specs/compare/v0.0.0...v0.1.0
