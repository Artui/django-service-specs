from __future__ import annotations

from django_service_specs.services.service_conflict import ServiceConflict


class ActionUnavailable(ServiceConflict):
    """The operation is not possible right now, for a reason with a stable name.

    Raised when one of a spec's
    [`Affordance`][django_service_specs.types.affordance.Affordance] conditions
    is not met, carrying that affordance's ``code`` and its ``reason`` as the
    message. Over HTTP it is a ``409`` whose body is
    ``{"detail": <reason>, "code": <code>}``.

    A [`ServiceConflict`][django_service_specs.services.service_conflict.ServiceConflict]
    subclass rather than a ``code=`` argument on its parent, for three reasons. The
    ``409`` answer needs no new status, because a subclass is matched by its
    parent's arm. A transport that wants the code matches this class ahead of its
    generic conflict handler, and one that has never heard of it still reports a
    conflict. And a ``ServiceConflict`` a service raises by hand genuinely has no
    code and never will, so a nullable ``code`` on the parent would be a field
    that lies at every other call site.

    ``code`` names the rule and is what a transport or client branches on; the
    message is the affordance's ``reason``, the sentence a person or a model is
    shown when the call is refused. A transport serving an agent should pass on
    both: the model can say the sentence, and the code is what stays stable when
    the sentence is reworded.

    Like every member, it must be matched **before** a generic ``ServiceConflict``
    or ``ServiceError`` handler, or the subclass check swallows it.
    """

    default_message: str = "This action is not available right now."

    def __init__(self, message: str | None = None, *, code: str) -> None:
        super().__init__(message)
        self.code: str = code
