"""``DispatchError`` - what dispatch refuses before an operation runs."""

from __future__ import annotations

from typing import ClassVar

from django.utils.translation import gettext

# The settings-free marker, the same identity ``global_settings`` defines for
# itself: ``django.utils.translation.gettext_noop`` reads ``USE_I18N`` when it
# is called, and it is called here at import, so importing the package would
# need settings configured first. The marker only names a msgid for
# ``makemessages``; the lookup is ``gettext``, made when a refusal is built.
from django.utils.translation.trans_null import gettext_noop


class DispatchError(Exception):
    """A refusal made by dispatch rather than by the operation.

    Deliberately **not** a subclass of
    [`ServiceError`][django_service_specs.services.service_error.ServiceError], and
    none of its children is one. Every consumer's exception ladder reads a
    service error as a refusal the caller adapts to: an agent transport turns
    one into a result the model reads and routes around while its run goes on.
    A denial declared that way becomes something the model retries, and an
    invalid argument set declared as a service validation error moves an MCP
    server's answer from "invalid arguments" to a business-rule failure, which
    is exactly the distinction that server draws by type.

    So the pair says who refused: dispatch, before the operation ran, or the
    operation itself.

    ``default_message`` is a msgid in the package's catalog, as each child's
    is, and is looked up in the active language each time a refusal is built
    with no message of its own. A ``message`` the caller passes is used as
    given.
    """

    default_message: ClassVar[str] = gettext_noop("The operation could not be dispatched.")

    def __init__(self, message: str | None = None) -> None:
        self.message = message if message is not None else gettext(self.default_message)
        super().__init__(self.message)
