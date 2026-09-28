# django-service-specs

Guidance for working in this repository.

## What this package is

A service contract for Django. An operation is declared once - what it takes,
who may run it, how its arguments are validated, what it returns - and any
transport dispatches it: an HTTP view, an MCP tool, an agent tool, a management
command, a background task.

Two positions shape everything else, and both read as limitations:

- **Django is the base, and the only one.** There is no pure-Python protocol
  layer beneath the kernel and no Django-free subpackage inside it. A principal
  is a Django user, a target is a model row, a transaction is Django's.
- **DRF is an adapter, never a dependency.** The package exists so a Django
  project with business logic and no API framework can hand its operations to
  an agent, a command or a queue. Nothing in `django_service_specs` imports
  `rest_framework`, and nothing in the test environment installs it.

`djangorestframework-services` will depend on this package rather than the
other way round, with its own `ServiceSpec` becoming the DRF adapter over this
kernel. Until that release, the two share concepts and no code.

## Commands

| Command | Does |
| --- | --- |
| `make init` | Sync all dependency groups and install the pre-commit hooks |
| `make test` | pytest with the 100% line+branch coverage gate |
| `make lint` | `ruff check` plus `ty check` |
| `make format-check` | `ruff format --check --diff` (CI runs this; `make lint` does not) |
| `make docs-build` | `mkdocs build --strict` |
| `make release-bump VERSION=X.Y.Z` | Rewrite the version and promote the changelog section |

## Structural rules

Non-negotiable. They keep the package navigable.

1. **One exported class or function per file.** The file is named after the
   exported symbol in `snake_case`.
2. **Private helpers used only in one file** stay in that file with a `_name`
   prefix.
3. **Non-exported helpers shared across files** go in that package's `utils.py`.
4. **Top-level imports only.** Lazy or function-local imports are forbidden
   unless a circular import is proven, or the import targets a declared optional
   dependency gated behind an opt-in. Document the reason inline.
5. **Full type annotations on every function and method signature.** `Any` is
   allowed only at the Django boundary where the type genuinely is `Any`.
6. **`__init__.py` is the only re-export point.** Each `__init__.py` lists the
   public surface in `__all__`. Internal modules import from leaf paths, never
   from the package's `__init__`.
7. **The package root is a table of contents, not a drawer.** It holds
   `__init__.py`, `version.py`, `settings.py`, `apps.py`, `checks.py` and nothing
   else; everything the package does lives in a subpackage. A subpackage is named
   for a **concern** (`parameters/`, `dispatch/`, `authorization/`) and never for
   a kind of thing - `helpers/`, `core/`, `common/` and `misc/` name nothing and
   become a flat root one level down. Three modules on one concern earn a
   directory. `types/` is the one standing subpackage, for value-shape carriers.
   There is no `exceptions/`: an exception lives in the subpackage that raises
   it.
8. **`types/` imports nothing else in the package, and that is load-bearing.**
   Any import of a submodule runs its package's `__init__` first, and a
   subpackage's `__init__` re-exports its whole surface. So a module that
   every subpackage imports must sit in a package whose `__init__` pulls in
   nothing: put it anywhere else and the first leaf to import it loads a
   pipeline that imports that leaf back, half-initialized. That is why
   `DispatchError` - the base every refusal before the run shares, and raised
   by nobody directly - lives in `types/` rather than `dispatch/`: there, the
   first `NotPermitted` to load pulled in `dispatch()`, which needs
   `authorize`, which needs `NotPermitted`. A function-local import would
   hide that cycle rather than remove it.

## Naming the concepts

**No public name that Django, DRF or pydantic already uses for something else,
and Python's own vocabulary where it has one.** The package sits between all
three, so a borrowed name is read as theirs by everyone who knows them:

| Name | Not | Because |
| --- | --- | --- |
| `DispatchError` | a subclass of any service error | The pair with a service's own refusals says who refused: dispatch, before the operation ran, or the operation itself |
| `InvalidArguments` | `InvalidInput` | Parameters are declared, arguments are supplied, and this refuses the arguments |
| `NotPermitted` | `PermissionDenied` | Django and DRF both own that name |
| `PermissionCheck` | `Permission` | Django owns `Permission`: the auth model |
| `Output`, `OutputField` | `Result` | A dispatch result is a *value*; this is the declaration of what comes out, paired with `Parameters` for what goes in |

**One spelling each, so a rename is a replace.** No aliases, no
backwards-compatible second name, no re-export under an old spelling. The same
holds for the distribution and import names: `django-service-specs` and
`django_service_specs` appear verbatim and nowhere derived, so renaming the
package before its first release is a search-and-replace plus a directory move.

## Constraints that look like tidy-ups

Each of these reads as an oversight and is not.

- **Dispatch errors are siblings of a service's own refusals, never
  subclasses.** Every consumer's exception ladder reads a service refusal as
  something the caller adapts to: an agent reads it and routes around it while
  the run continues. A denial declared as one becomes a tool result the model
  retries. And `InvalidArguments` is not a service validation error, because
  an MCP server tells a malformed argument shape from a business rule on
  well-shaped arguments by exactly that type difference.
- **Dispatch enforces the permission check by default.** A transport that has
  already authorized says so with a `Grant`, bound to one operation and one
  principal and not serializable, so it cannot cross a queue. Enforcement by
  omission is how an off-HTTP runner skips authorization with nothing warning.
- **A deactivated principal is refused at lookup.** `resolve_principal` is the
  only thing that refuses `is_active=False`; the stock permission classes of
  the frameworks this adapts both pass one. Never fall back to an anonymous
  user.
- **An operation with no declared permission check is refused at
  registration.** Off HTTP there is no view to inherit a policy from, so an
  explicit allow exists for an operation that means it.
- **Target resolution runs before validation.** The validator's context
  carries the resolved row, because an update's uniqueness check has to
  exclude the row being updated. Class-level authorization runs before either,
  so a refused principal learns nothing about which rows exist.

## Adding a feature

Branch first, always. Three touchpoints per change: the source file, the
`__init__.py` re-export, and the mirrored test file.

## Tests

`tests/` mirrors the source tree, one file per source file with the same name.
`pytest-asyncio` runs in auto mode. The coverage gate is **100% line and
branch**.

Never `# pragma: no cover`. If a branch cannot be reached, that is a signal to
restructure the code, not to exempt it.

Rules specific to this package:

- **No DRF in any environment the suite runs in.** Not in the dependencies, not
  in a dependency group, not as a test double. A suite that could import it
  could not notice the kernel reaching for it, and the `floor` job's
  install-alone step asserts the same thing from outside.
- **A transport's behaviour is tested against the transport's real producer.**
  Where a test double stands in for a protocol - a DRF serializer, a pydantic
  model, a `django.tasks` backend - check its shape against the real one, or
  every test using it agrees with the bug.
- **Where several checks can answer one input, size the test so the one it
  names is the one that answers**, and assert which message came back. The
  shape check runs before the Validator by design, so a Validator test fed a
  malformed argument passes without exercising the Validator.

## Type checking

`ty`, scoped to `django_service_specs` via `[tool.ty.environment]`. The
package ships `py.typed`, so consumers get the annotations.

Never a mypy-style `# type: ignore` in the package - a pre-commit hook rejects
it, because nothing here reads that pragma and leaving one implies a checker
that is not running.

## Linting and formatting

`ruff` is the source of truth for both. Use `...` rather than `pass` for empty
bodies.

`make lint` does **not** run `ruff format --check`, and CI does. Run
`uv run ruff format --check` before pushing.

## Imports inside the package

Absolute and fully qualified, never relative - `ban-relative-imports = "all"` is
configured and enforced. isort order is stdlib, third party, first party.

`from __future__ import annotations` goes at the top of every annotated file.
`required-imports` in the isort config is what enforces it rather than leaving
it to memory, and the two exemptions are re-export `__init__.py` files and
Django's generated migrations.

## Compatibility floor

| | Minimum | Tested against |
| --- | --- | --- |
| Python | 3.10 | 3.10 through 3.14 |
| Django | 4.2 | 4.2, 5.0, 5.1, 5.2, 6.0, 6.1 |

Both floors match `djangorestframework-services`, which will depend on this
package. Raising either here raises it there, so a floor change is a decision
about both packages rather than a tidy-up of one.

The suite runs on SQLite. Nothing the kernel owns is backend-specific.

## CI and pre-commit

Seven jobs in `tests.yml`: `lint`, `docs`, `floor` (resolves every declared
dependency at the bottom of its window and runs the suite there), `test` (the
Python x Django matrix), `coverage-badge`, `secrets`, and the `tests-passed`
gate that branch protection points at.

Releases are **main-triggered**: `make release-bump`, edit the changelog, open a
PR, and merging to `main` runs the release. There is no tag to push - the
workflow creates the tag after PyPI accepts the upload, which is also why
`make release-publish-finalize` exists for the case where it does not.

Pre-commit runs gitleaks, the standard hygiene hooks, ruff, ty, four convention
guards (no local filesystem paths, no internal plan-step labels, no mypy-style
type-ignore, no emoji or marker glyphs in any committed file) and
`check-changelog`, which refuses a changelog a merge or rebase has silently
rearranged.

## Releasing

```
make release-bump VERSION=X.Y.Z   # rewrites version.py, promotes the changelog
# edit CHANGELOG.md to fill in the new section, review the diff
# open a PR, get it reviewed, merge to main
```

The release job on `main` short-circuits to a no-op when a `vX.Y.Z` tag for the
version in source already exists on origin, so an ordinary merge costs nothing.

That guard is why the scaffold sits at `0.0.0` with a matching `v0.0.0` tag. A
new repository has no tags at all, so without one the very first push to `main`
reads the scaffold version as unreleased and runs a real release attempt. The
first real release is `make release-bump VERSION=0.1.0`.

One-time setup that cannot be done from a checkout: a PyPI Trusted Publisher
pointing at this repo with workflow `release.yml` and environment `pypi`.
