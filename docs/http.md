# Serving over HTTP

`django_service_specs.http` serves an operation from a Django view with
nothing between the request and [`dispatch`](dispatching.md): no API
framework, no serializer, no router. A view reads the principal and the
arguments off the request, dispatches, and answers the result or the refusal
as JSON.

```python
from django_service_specs import AsyncSpecView, SpecView, adispatch_request, dispatch_request
```

It is the plumbing, not the pages: a view here answers JSON to a script, a
`fetch()` or an htmx request. A form a person fills in and reads back is a page
of its own.

## A function view

[`dispatch_request`][django_service_specs.http.dispatch_request.dispatch_request]
is the whole of what a hand-written view calls:

```python
--8<--
docs/examples/http.py:function_view
--8<--
```

It reads the principal and the arguments, dispatches with the `grant`,
`pool_seeds` and `unknown_arguments` it is given, and answers:

- **A not-found result** is 404, `{"detail": "Not found."}`.
- **A success** is the presented value, bare, with no envelope around it. The
  status is the caller's `success_status`, or else 204 for a service with
  nothing to present and 200 for everything else. A 204 has no body. A read
  whose value is `None` (an `allow_none` retrieve that found nothing) answers
  `null` at 200, since `None` is its value.
- **A refusal of either family** is
  [`error_response`](#refusals)'s answer. Anything else propagates, a
  configuration error included: it is wrong for every caller, so it belongs to
  the host's error handling rather than to one client's response.

[`adispatch_request`][django_service_specs.http.adispatch_request.adispatch_request]
does the same from an async view, through `adispatch` and `apresent`. It reads
the request in an executor hop of its own, because touching `request.user` is
a session query and Django refuses one on the event loop.

## The class form

[`SpecView`][django_service_specs.http.spec_view.SpecView] is one spec as a
view, and every attribute can be passed to `as_view()` or set on a subclass:
`spec`, `success_status`, `unknown_arguments`, `pool_seeds` and `methods`.

```python
--8<--
docs/examples/http.py:urls
--8<--
```

**The methods follow the spec.** A `SelectorSpec` answers GET and HEAD, a
`ServiceSpec` POST. `methods` replaces that with the ones it names, from GET,
HEAD, POST, PUT, PATCH and DELETE, in either case. Any other method is Django's
own 405, with an `Allow` header listing exactly the methods served, and
OPTIONS is Django's own answer.

`as_view()` checks the spec and the methods when the view is built, so a view
with no spec, or one naming a method it cannot serve, fails when the URLconf is
imported rather than on its first request.

[`AsyncSpecView`][django_service_specs.http.async_spec_view.AsyncSpecView] is
the same view with every handler async, through `adispatch_request`. Django
serves a class async only when all of its handlers are, which is why it is a
class of its own rather than a setting.

## Arguments

[`request_arguments`][django_service_specs.http.request_arguments.request_arguments]
reads them, by method and body:

| Request | Read from | Coerced |
| --- | --- | --- |
| GET, HEAD | the query string | yes, with `coerce_flat` |
| any other method, `application/json` body | the body, which must be an object | no |
| any other method, form or multipart body | the form fields | yes, with `coerce_flat` |
| any other method, no body | nothing | - |
| any other method, any other body | refused, 415 | - |

**A flat source is read by the declaration.** An `array` parameter takes every
value its key was sent with (`?ids=1&ids=2`), and anything else takes the last.
A blank value is absent unless `""` is one the parameter can take: a plain
string can, and a number, a boolean, a date, a decimal, or a string whose
`choices` leave the blank out cannot. A flat wire has no other spelling of
"left blank", and an empty `?count=` or `?since=` from a filter form is not a
refusal to count or a malformed date. Django's `csrfmiddlewaretoken` is never an argument. Then
[`coerce_flat`](arguments.md#flat-transports) types the strings, and leaves an
undeclared key for the closed argument set to refuse under the caller's policy.

**A JSON body is read as it is.** Its values are not coerced, because a JSON
caller that sends `"5"` for an integer has sent a string, and the shape check
says so. A body that does not parse, or is not an object, is refused as
`InvalidArguments` under `non_field_errors`. An empty body is no arguments.

**A body in any other format is refused** as
[`UnsupportedMediaType`][django_service_specs.http.unsupported_media_type.UnsupportedMediaType],
answered 415, rather than read as no arguments: a PATCH sent as `text/plain`
or `application/merge-patch+json` to an operation whose parameters are all
optional would otherwise run with nothing and answer success. A request with
no body carries no arguments whatever its `Content-Type` says, so a
`fetch(url, {method: "POST"})` for an operation its route names is served.

Django parses a form body into `request.POST` for POST alone, so a PUT, PATCH
or DELETE form is parsed here the same way rather than arriving empty. **Files
are not arguments**: a parameter has no file type, so an upload is left in
`request.FILES` for the view.

**The URL kwargs are arguments too**, merged last so the route wins a clash, as
it does in djangorestframework-services. A client-supplied value must not move
the route's scope: a POST to `/notes/4/rename/` whose body says `"pk": 9`
renames note 4 or nothing. A path segment with no converter arrives as a
string and goes through `coerce_flat` like a query value. Every URL kwarg is
an argument, so the spec declares each one. A route capturing a kwarg its spec
does not declare raises `ImproperlyConfigured` on the first request it
serves, under either `unknown_arguments` policy: the mismatch is the host's,
wrong for every request, and a 400 would tell the client it had sent
something wrong. A host scoping by a kwarg its spec does not take (an `org`
read by middleware, say) calls
[`dispatch_request`][django_service_specs.http.dispatch_request.dispatch_request]
from its own view and passes the `url_kwargs` the spec declares.

## The principal

The principal is `request.user`, **anonymous included**: the spec's permission
check is what decides whether anonymous may act, so it is handed the anonymous
user rather than being pre-empted.

**A deactivated account is refused**, as `PrincipalUnavailable` (403), before
anything else is read. Django's `ModelBackend` never logs one in, but
`AllowAllUsersModelBackend` and a project's own backend may, and a deactivated
principal never acts, on HTTP or off it.

## Refusals

[`error_response`][django_service_specs.http.error_response.error_response]
answers both [families](arguments.md#two-families-of-error), with the statuses
djangorestframework-services uses, so a client of both reads one answer:

| Refusal | Status | Body |
| --- | --- | --- |
| `InvalidArguments` | 400 | the error tree |
| `ServiceValidationError` | 400 | its detail, as a field map |
| `NotPermitted`, `PrincipalUnavailable` | 403 | `{"detail": message}` |
| `ServiceNotFound` | 404 | `{"detail": message}` |
| `ServiceConflict` | 409 | `{"detail": message}` |
| `ServiceError` | 422 | `{"detail": message}` |
| `UnsupportedMediaType` | 415 | `{"detail": message}` |
| `DispatchError` | 400 | `{"detail": message}` |

A row is read top to bottom and the first match answers, so a subclass is
matched before its base. **Every 400 body is a field map**: a
`ServiceValidationError`'s string or list detail goes under
`non_field_errors`, where a message about the input as a whole sits in the
tree too, and the tree's integer row keys are strings on the wire. Messages
render in the active language, lazy ones included.

**Never 401.** A session has no challenge to answer, and a 401 tells a client
to start an authentication flow it has no way to finish. An anonymous caller
a permission check refuses is a 403, like any other refused principal.

## CSRF

**CSRF is the host's middleware**, as it is for any Django view. Nothing in the
package is exempted: a POST from a session-authenticated browser carries the
token, in the `X-CSRFToken` header for a `fetch()` or in the form for an HTML
form, and `CsrfViewMiddleware` refuses one that does not. A route that needs no
token is the host's decision, and one line:

```python
--8<--
docs/examples/http.py:csrf
--8<--
```
