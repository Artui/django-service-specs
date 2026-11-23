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

## Which route captures are arguments { #which-route-captures-are-arguments }

A URL converter hands a view its `to_python()` value, while a Validator field
reads what the caller sent, so a capture named like a field cannot fill it: a
converter that changes the value (a hashid, say) would hand the field `42` where
it reads `"h42"`. The rule an HTTP edge splits a route's captures by is
[`route_captures`][django_service_specs.specs.route_captures.route_captures]:

```python
from django_service_specs import route_captures

arguments, namesakes = route_captures(spec, view.kwargs)
route = {name: view.kwargs[name] for name in arguments}
```

- A capture naming a read, a target selector's read or a shape is an argument.
- A capture named like a Validator field is a namesake and no argument. The
  field stays the caller's, sent in the body; a target selector wanting the
  route's value reads `view.kwargs` through its `kwargs` provider, as a
  provider's key named like a field is a namesake too.
- A capture naming neither keeps each edge's own rule: dropped, or refused as
  the host's misconfiguration.

An edge that renames its captures hands its mapping as `mapped`; mapping a
capture onto a Validator field is refused, naming both, since no rename makes a
URL value the caller's. To fill a field from the route, declare the capture as
a read and set the field in the service.

## A refusal, placed on a form { #a-refusal-placed-on-a-form }

django-spec-html's, in
[its documentation](https://artui.github.io/django-spec-html/http/#a-refusal-placed-on-a-form).
