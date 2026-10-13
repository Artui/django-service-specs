"""``ProviderKeys`` — the names a ``kwargs=`` provider fills, and those it may decline."""

from __future__ import annotations

from typing import NamedTuple


class ProviderKeys(NamedTuple):
    """What
    [`provider_keys`][django_service_specs.pool.provider_keys.provider_keys]
    read off a ``kwargs=`` provider, before it runs.

    Two disjoint sets of key names that together are every key of the
    ``TypedDict`` the provider is annotated to return.

    A ``NamedTuple`` so that it reads both ways its consumers read it. It still
    unpacks as ``filled, declinable = provider_keys(spec.kwargs)``, which is how
    the MCP server's call site reads it, and it answers ``.filled`` and
    ``.declinable``, which is what the Pydantic-AI toolset's private dataclass
    offered before this replaced it. Both are held by
    ``test_the_answer_names_its_two_sets_and_still_unpacks``.

    Attributes:
        filled: The keys the provider always answers for, ``NotRequired`` ones
            included, since the provider owns them. A transport need not ask
            its caller for any of them.
        declinable: The keys whose value admits ``UnsetType``
            (``tenant: str | UnsetType``). The provider may return ``UNSET`` for
            one, which dispatch removes from the pool, so the caller's value is
            the one the callable receives. Such a key stays the caller's: a
            transport keeps asking for it, and dispatch holds it to its
            declaration, so a required one is required of the caller even
            though the provider may fill it. A ``filled`` key is relaxed where
            the provider's values reach it - a selector's ``kwargs`` that
            selector's reads, a service spec's ``kwargs`` the spec's
            ``reads``, and ``input_data`` the Validator's parameters, at the
            top level or, on a ``many`` spec, inside each row - and a
            ``ServiceSpec`` whose provider fills a parameter declared
            anywhere else is refused.
    """

    filled: frozenset[str]
    declinable: frozenset[str]
