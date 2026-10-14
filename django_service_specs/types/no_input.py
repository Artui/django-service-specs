"""``NoInput`` - the input type of a service that takes none."""

from __future__ import annotations


class NoInput:
    """Binds a Protocol's ``InputT`` for a service that reads no input.

    Pair it with [`DeleteService`][django_service_specs.services.delete_service.DeleteService],
    whose ``data`` has a default, so the service leaves ``data`` out:

        @implements(DeleteService[NoInput, Note, None])
        def delete_note(*, instance: Note, **extras: Any) -> None: ...

    Never instantiated. It exists to fill the type variable with a name that
    says why it is empty, which ``None`` or ``Any`` would not.
    """
