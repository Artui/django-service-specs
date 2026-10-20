# Running operations from the command line

The management command that serves a [registry](registry.md)'s specs, one
subcommand per spec, is
[django-spec-cli](https://artui.github.io/django-spec-cli/), a distribution of
its own:

```bash
pip install django-spec-cli
```

It runs each operation through [`dispatch`](dispatching.md) as every other
transport does, and its documentation covers declaring a command, the user a
run is made as, the output formats, the exit codes, and the report of open
specs. This package no longer ships a command.

## Open specs: `--explain` and the system check { #open-specs-explain }

Both are django-spec-cli's, in
[its documentation](https://artui.github.io/django-spec-cli/#open-specs-explain).
The registry fact they report is this package's:
[open specs, reported](registry.md#open-specs-reported).
