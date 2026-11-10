from __future__ import annotations


class CodedMessage(str):
    """A message in an
    [`InvalidArguments`][django_service_specs.parameters.invalid_arguments.InvalidArguments]
    tree, carrying the code of the mistake it names."""

    code: str
    """The mistake, as DRF's codes name it. Never translated."""

    def __new__(cls, message: str, code: str) -> CodedMessage:
        instance = super().__new__(cls, message)
        instance.code = code
        return instance

    def __reduce__(self) -> tuple[type[CodedMessage], tuple[str, str]]:
        # One hook for pickle, ``copy`` and ``deepcopy``, so the code survives each.
        return (type(self), (str(self), self.code))

    # No ``__repr__`` of its own, on purpose: ``str``'s, so the text ``str``
    # makes of a tree - a log line, a ``BadRequest`` -
    # reads ``{'n': ['This field is required.']}``, as a tree of plain strings
    # does, rather than naming this class in every message
    # (test_its_repr_is_its_message_s).
