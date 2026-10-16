"""``apply_server_arguments`` - a caller's arguments with the server's values in place."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django_service_specs.dispatch.utils import checked_server_values
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource
from django_service_specs.types.server_arguments import ServerArguments


def apply_server_arguments(
    spec: ServiceSpec | SelectorSpec | SpecSource,
    arguments: Mapping[str, Any],
    server: ServerArguments,
) -> dict[str, Any]:
    """``arguments`` as dispatch should receive them under ``server``: a new dict, the input untouched.

    For a transport to call on every call, before
    [`dispatch`][django_service_specs.dispatch.dispatch.dispatch] or
    [`adispatch`][django_service_specs.dispatch.adispatch.adispatch], which
    take the result as their ``arguments``; both run the same prelude over
    it, so one applied mapping answers the same through either. Dispatch
    takes no binding of its own: this is the whole of the rule, and a
    transport path that does not call it is unbound.

    1. **The caller's value for every bound or withheld name is dropped**,
       before anything reads it. A value the caller sends for a name it was
       never offered - ``"null"`` for an integer it could not see - therefore
       never reaches the shape check and cannot refuse the call. Held by
       test_a_malformed_value_for_a_withheld_name_never_reaches_the_shape_check.
    2. **The bound values are laid over what is left**, so a bound name
       holds the server's value whatever the caller sent, and a withheld one
       is absent. Held by test_a_bound_value_outranks_the_caller_s, which
       fails if the two steps swap.

    Every other key is left as sent, for the shape check to read under the
    transport's ``unknown_arguments``, so a name nobody declared is still
    refused under ``REJECT``.

    The bound values are checked against their own parameters, as
    ``check_server_arguments`` checked them when the transport was built, and
    handed on as the shape check reads them: a ``uuid`` in its canonical
    spelling, an integral float declared an integer as the int. **One that fails is the server's mistake**,
    raised as ``ImproperlyConfigured`` with the refusal as its cause, never
    as ``InvalidArguments``: a client refusal would ask the caller to fix a
    value it neither sent nor can see. This is where the rule parts from
    [`route_arguments`][django_service_specs.http.route_arguments.route_arguments],
    whose bad value is a client's 400, because a client chose the URL and
    nobody but the server chose a bound value. A bound name the spec does not
    declare, which
    [`check_server_arguments`][django_service_specs.dispatch.check_server_arguments.check_server_arguments]
    refuses when the transport is built, is refused here the same way.

    Every refusal names the spec's kind and its callable, so a transport
    binding many tools can say which one is misconfigured.

    Raises:
        ImproperlyConfigured: a bound value that fails its declaration, or a
            bound name the spec does not declare.
    """
    names = server.names()
    applied = {key: value for key, value in arguments.items() if key not in names}
    if server.values:
        spec = kernel_spec(spec)
        applied.update(checked_server_values(spec, spec.parameters(), server.values))
    return applied
