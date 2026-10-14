"""``unguarded_specs`` - the specs in a registry that authorize nothing."""

from __future__ import annotations

from django_service_specs.authorization.unrestricted import Unrestricted
from django_service_specs.commands.unguarded_reason import UnguardedReason
from django_service_specs.commands.unguarded_spec import UnguardedSpec
from django_service_specs.registry.spec_registry import SpecRegistry
from django_service_specs.specs.kernel_spec import kernel_spec


def unguarded_specs(registry: SpecRegistry) -> tuple[UnguardedSpec, ...]:
    """The entries of ``registry`` that any principal may run, in registry order.

    Each entry is judged by the spec it compiles to, through
    [`kernel_spec`][django_service_specs.specs.kernel_spec.kernel_spec]: that
    is the object dispatch hands its permission checks, so a source object
    declaring checks of its own is judged by what runs rather than by what it
    says.

    ``authorize`` runs every check in order, and the first refusal stops the
    call, so a spec is unguarded only when **every** check it declares is an
    ``Unrestricted`` - one real check beside one guards it
    (test_a_real_check_beside_unrestricted_is_guarded). A subclass of
    ``Unrestricted`` counts as one: it is a project's own name for the same
    decision. Nothing else can leave a registered spec open, since a registry
    refuses ``permissions=None`` and a spec refuses an empty sequence when it
    is built; the report reads only what a registry can hold.

    This says what the declaration allows, not whether a call succeeds:
    dispatch still refuses a deactivated principal, whatever the checks say.

    The function is the one report behind the system check and the command's
    own listing, so the two cannot disagree.
    """
    return tuple(
        UnguardedSpec(entry.name, UnguardedReason.UNRESTRICTED)
        for entry in registry
        # ``permissions`` is typed optional, but a registry refuses ``None``
        # when the entry is added, so ``or ()`` only satisfies the type; and
        # every spec a registry holds declares at least one check, so ``all``
        # is never vacuously true here. ``all`` rather than ``any`` is held by
        # test_a_real_check_beside_unrestricted_is_guarded, ``isinstance``
        # rather than an exact type by
        # test_a_subclass_of_unrestricted_is_still_unrestricted, and reading
        # the compiled spec by test_the_source_s_own_permissions_are_not_what_is_read.
        if all(
            isinstance(check, Unrestricted) for check in kernel_spec(entry.spec).permissions or ()
        )
    )
