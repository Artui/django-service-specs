# Serving over HTTP

The plain-Django HTTP transport, which serves a spec from a Django view with no
API framework between the request and [`dispatch`](dispatching.md), is
[django-spec-html](https://artui.github.io/django-spec-html/), a distribution of
its own:

```bash
pip install django-spec-html
```

Its JSON views and the functions they are built from keep their names, and are
imported from `django_spec_html` rather than from this package:

```python
from django_spec_html import AsyncSpecView, SpecView, adispatch_request, dispatch_request
```

The same holds for `request_arguments`, `request_principal`, `route_arguments`,
`error_response`, `add_argument_errors` and `UnsupportedMediaType`. Each runs
the operation through [`dispatch`](dispatching.md) as every other transport
does, and its documentation covers the views, the arguments read off a request,
the principal, the refusals and their statuses, and CSRF. It also serves a spec
whose Validator is a [Django form](forms.md) as a page. This package no longer
ships an HTTP view.

## A refusal, placed on a form { #a-refusal-placed-on-a-form }

django-spec-html's, in
[its documentation](https://artui.github.io/django-spec-html/http/#a-refusal-placed-on-a-form).
