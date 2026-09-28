"""``bind_arguments`` - the shape check and the Validator, for a caller outside dispatch."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from django_service_specs.dispatch.utils import validate_arguments
from django_service_specs.parameters.check_arguments import check_arguments
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.validation.unknown_arguments import UnknownArguments

if TYPE_CHECKING:
    from django_service_specs.specs.service_spec import ServiceSpec


def bind_arguments(
    spec: ServiceSpec | SelectorSpec,
    arguments: Mapping[str, Any],
    *,
    principal: Any,
    target: Any = None,
    unknown_arguments: UnknownArguments = UnknownArguments.REJECT,
) -> dict[str, Any]:
    """Check ``arguments`` against the spec's parameters, then validate them.

    The bind a transport calls when it binds input itself rather than through
    ``dispatch`` - an MCP server answering a malformed call before it opens a
    transaction, a queue validating a task in the worker. It is the same two
    steps dispatch takes, so a transport that binds for itself cannot drift
    from the gate dispatch applies:

    1. [`check_arguments`][django_service_specs.parameters.check_arguments.check_arguments]
       over ``spec.parameters()``, under ``unknown_arguments``: the closed
       argument set and the shape check, at every level.
    2. For a [`ServiceSpec`][django_service_specs.specs.service_spec.ServiceSpec]
       with a Validator, ``validate()`` on only the arguments the Validator's
       own ``parameters()`` declare - never the target selector's ``reads`` -
       with ``ValidationContext(principal, target)``.

    Returns the Validator's values. A service spec with no Validator returns
    ``{}``, because every argument it takes is its target selector's and none
    reaches the service. A
    [`SelectorSpec`][django_service_specs.specs.selector_spec.SelectorSpec]
    has no Validator and returns the checked arguments, which are what its
    selector is called with.

    **It does not resolve or authorize.** Dispatch runs class-level
    authorization, target resolution and object-level authorization *between*
    these two steps, so the Validator sees the resolved row and a refused
    principal learns nothing about which rows exist. A caller of this function
    owns both: it authorizes before binding, and passes the row it resolved as
    ``target``, or ``None`` for a create.

    Raises:
        InvalidArguments: from either step. The shape check's tree carries every
            problem at once, and a Validator is only reached with well-shaped
            arguments.
    """
    checked = check_arguments(spec.parameters(), arguments, unknown_arguments=unknown_arguments)
    if isinstance(spec, SelectorSpec):
        return checked
    # The step dispatch takes, the same function: the two cannot drift apart.
    return validate_arguments(spec, checked, principal=principal, target=target)
