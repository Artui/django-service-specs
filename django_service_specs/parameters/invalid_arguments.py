"""``InvalidArguments`` - the supplied arguments do not fit the declared parameters."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

from django_service_specs.parameters.non_field_errors import NON_FIELD_ERRORS
from django_service_specs.types.dispatch_error import DispatchError


class InvalidArguments(DispatchError):
    """The arguments were refused: their shape, or the Validator's verdict on them.

    Parameters are declared and arguments are supplied, and this refuses the
    arguments. It is raised by the shape check, the closed argument set,
    ``coerce_flat``, a Validator and the relation writes, so every refusal of
    input reaches a transport as one type.

    **Not a service validation error**, and not a subclass of one. A service
    raising
    [`ServiceValidationError`][django_service_specs.services.service_validation_error.ServiceValidationError]
    is stating a business rule about well-shaped input; this says the input was
    not well-shaped, or did not validate. An MCP server answers the two
    differently on purpose.

    ``detail`` is a tree addressed by path, because nested arguments fail inside
    rows:

    - a field: ``{"title": ["..."]}``
    - a nested object: ``{"author": {"name": ["..."]}}``
    - rows, keyed by their ``int`` index, only the rows that failed:
      ``{"books": {1: {"title": ["..."]}}}``
    - a message about a row itself, under ``non_field_errors`` inside the row
    - a message about a ``many`` call's list as a whole, under
      ``non_field_errors`` beside the failing rows' indices, after them

    Every leaf is a list of ``str``, so the whole tree is JSON-serializable once
    the integer keys are written as strings, which is what ``json.dumps`` does.
    A ``many`` call's node that carries the list's own message mixes ``int``
    indices with ``non_field_errors``, so ``json.dumps(..., sort_keys=True)``
    over it raises ``TypeError``: it is already in reading order, and is
    written as it stands.

    ``missing`` names the arguments the call left out, read off the tree
    rather than parsed from its words, so a transport wording "you did not
    send ``title``" has one reading to ask and not its own walk of ``detail``.

    ``after_authorize`` marks that
    [`check_call`][django_service_specs.dispatch.check_call.check_call] raised
    this after its class-level permission check passed, which it does for one
    refusal only: the rows of a ``many`` call, raised after its fourth step. A
    transport that called ``check_call`` before charging a rate limit reads it
    to tell a refused row, where the call was admitted and only its rows are
    wrong, from a refused call, which was not admitted; it need not ask the
    checks again to find out. Every other refusal leaves it ``False``,
    ``dispatch``'s own refusal of the same rows included, though that one too
    is raised after its authorization: the mark is ``check_call``'s statement
    about its own order of steps, not a general account of where in a run the
    error arose.
    """

    default_message: ClassVar[str] = "Invalid arguments."

    def __init__(self, detail: Mapping[Any, Any], *, after_authorize: bool = False) -> None:
        super().__init__()
        self.detail: dict[Any, Any] = dict(detail)
        self.after_authorize: bool = after_authorize

    @property
    def missing(self) -> tuple[str, ...]:
        """The top-level arguments the call left out, sorted: those with a message coded ``"required"``.

        Any refusal coded ``"required"`` counts - the shape check, a selector
        refusing a read nothing filled, and the Validator adapters (dataclass,
        pydantic, forms), which code it too - and it is the code DRF gives
        the same mistake. An argument that was sent and was wrong is not here, nor is
        one whose only messages carry another code or none (a Validator's own
        plain ``str``). **Top level only**: a nested object's field and a
        ``many`` call's row field are not arguments of the call, so they are
        never listed, and neither is ``non_field_errors``, which is a message
        about the call and not a name in it
        (test_missing_is_not_the_node_s_own_message fails without that
        exclusion). A nested node is a dict, whose iteration yields keys and
        never a message with a code, which is why a row or a nested object
        lists nothing (test_missing_does_not_reach_into_a_nested_object_or_a_row).
        The code is read and not the words
        (test_missing_reads_the_code_and_not_the_words fails if the words are).
        """
        return tuple(
            sorted(
                name
                for name, messages in self.detail.items()
                if name != NON_FIELD_ERRORS
                and any(getattr(message, "code", None) == "required" for message in messages)
            )
        )
