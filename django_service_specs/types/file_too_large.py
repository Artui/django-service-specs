from __future__ import annotations


class FileTooLarge(Exception):
    """A ``FileResult`` read past the ceiling a transport set; ``max_bytes`` names it.

    Not a ``DispatchError``: the operation ran and produced the file. Each
    transport answers it in its own terms, as it answers a not-found.
    """

    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max_bytes
        super().__init__(f"The file is larger than the {max_bytes}-byte ceiling.")
