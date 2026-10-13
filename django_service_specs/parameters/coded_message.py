"""``CodedMessage`` - a refusal's message, with a code a program reads beside the words a person does."""

from __future__ import annotations


class CodedMessage(str):
    """A message in an [`InvalidArguments`][django_service_specs.parameters.invalid_arguments.InvalidArguments] tree, carrying the code of the mistake it names.

    The words are for a person and are translated; the ``code`` is for a
    program and is not. Every refusal the kernel and its shipped adapters
    make carries one - the shape check, ``coerce_flat``, ``request_arguments``,
    a selector or ``extend_queryset`` refusing a read nothing filled, a
    FilterSet refusing its data, a relation write refusing a row, and
    ``DataclassValidator``, ``FormValidator`` and ``PydanticValidator`` - and
    the code is the one a
    DRF field gives the same mistake (``"required"``, ``"null"``,
    ``"invalid"``, ``"not_a_list"``, ``"max_length"`` and the rest), so an
    adapter building DRF's error details maps each one across unchanged.
    Where Django or pydantic refused, their own code comes through: Django's
    as it raised it, and pydantic's error type as DRF's code for the same
    mistake. The arguments page lists them, refusal by refusal.

    **It is its message to everything that reads a string.** Equality,
    hashing, ``json.dumps``, ``%``-formatting and ``repr`` all see the plain
    ``str``, and the code takes no part in any of them: a tree with codes
    compares equal to the same tree written with plain strings, the body a
    transport writes is unchanged by them, and so is the text ``str`` makes of
    a tree, which a log line or Django's ``BadRequest`` carries. That is the difference from DRF's ``ErrorDetail``,
    whose equality reads the code too, and why this is not one. Read the code
    with ``getattr(message, "code", None)``, since a Validator's own messages
    reach the same tree as it raised them, a plain ``str`` among them.

    A copy, a deep copy and a pickle each keep the code.
    """

    code: str
    """The mistake, as DRF's codes name it. Never translated."""

    def __new__(cls, message: str, code: str) -> CodedMessage:
        instance = super().__new__(cls, message)
        instance.code = code
        return instance

    def __reduce__(self) -> tuple[type[CodedMessage], tuple[str, str]]:
        # ``str`` pickles by its value alone, which would rebuild this with no
        # code; one hook serves pickle at every protocol, ``copy`` and ``deepcopy``.
        return (type(self), (str(self), self.code))

    # No ``__repr__`` of its own, on purpose: ``str``'s, so the text ``str``
    # makes of a tree - a log line, the ``BadRequest`` SpecFormView raises -
    # reads ``{'n': ['This field is required.']}``, as it did before messages
    # carried codes, rather than naming this class in every message
    # (test_its_repr_is_its_message_s).
