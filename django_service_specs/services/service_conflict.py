from __future__ import annotations

from django_service_specs.services.service_error import ServiceError


class ServiceConflict(ServiceError):
    """The operation collides with the resource's current state.

    A slot already taken, a row someone else moved first, a name already used. The
    resource is there and the request is well-formed; the two are simply
    incompatible right now, and a caller can often resolve it by re-reading and
    trying again — distinct from a plain
    [`ServiceError`][django_service_specs.services.service_error.ServiceError],
    which says "understood, and still not doing it" with no such implication.

        def slot_is_free(*, user, data):
            if Event.objects.filter(owner=user, day=data["day"], hour=data["hour"]).exists():
                raise ServiceConflict(f"{data['day']} at {data['hour']}:00 is taken.")

    A transport that has never heard of this type still handles a
    ``ServiceError``, and one that wants to do better matches on the class. It
    must match **before** its generic ``ServiceError`` handler, or the subclass
    check swallows it.
    """

    default_message: str = "Conflict."
