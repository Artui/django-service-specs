from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS
from django_service_specs.pool.utils import (
    deferred_progress,
    only_seeds,
    pool_kwargs,
    resolve_progress,
    resolve_provider,
)
from django_service_specs.types.unset import UNSET


class Recorder:
    """A progress sink that keeps every report it is handed."""

    def __init__(self) -> None:
        self.reports: list[tuple[Any, ...]] = []

    def __call__(
        self,
        progress: float,
        *,
        total: float | None = None,
        message: str | None = None,
        meta: Mapping[str, Any] | None = None,
    ) -> None:
        self.reports.append((progress, total, message, meta))


class TestResolveProvider:
    def test_no_provider_provides_nothing(self) -> None:
        assert resolve_provider(None, {"user": 1}, label="ServiceSpec.kwargs") == {}

    def test_the_provider_is_bound_from_the_pool_by_the_names_it_declares(self) -> None:
        def scope(user: int, project_pk: int) -> dict[str, Any]:
            return {"tenant": user, "project": project_pk}

        pool = {"user": 7, "project_pk": 3, "data": {}}
        assert resolve_provider(scope, pool, label="ServiceSpec.kwargs") == {
            "tenant": 7,
            "project": 3,
        }

    def test_a_key_answered_unset_is_declined_rather_than_set(self) -> None:
        def scope() -> dict[str, Any]:
            return {"tenant": 1, "region": UNSET}

        assert resolve_provider(scope, {}, label="ServiceSpec.kwargs") == {"tenant": 1}

    def test_a_provider_returning_no_mapping_is_refused_by_its_field(self) -> None:
        with pytest.raises(ImproperlyConfigured) as refused:
            resolve_provider(lambda: [("tenant", 1)], {}, label="SelectorSpec.kwargs")
        assert str(refused.value) == (
            "SelectorSpec.kwargs returned list; a provider returns a mapping of pool entries."
        )


@pytest.mark.parametrize("resolve", [deferred_progress, resolve_progress])
def test_no_provider_leaves_the_transport_s_reporter_as_it_is(resolve: Any) -> None:
    transport = Recorder()
    assert resolve(None, {}, transport=transport) is transport
    assert resolve(None, {}, transport=None) is None


class TestDeferredProgress:
    def test_the_provider_is_not_called_until_the_first_report(self) -> None:
        # A call refused before its run never reports, so it never resolves
        # the provider - a task record is not created for a call that was not made.
        calls: list[Any] = []

        def provider(user: Any) -> Recorder:
            calls.append(user)
            return Recorder()

        deferred_progress(provider, {"user": "ada"}, transport=None)
        assert calls == []

    def test_both_sinks_hear_every_report_and_the_provider_runs_once(self) -> None:
        transport, own = Recorder(), Recorder()
        calls: list[Any] = []

        def provider(user: Any) -> Recorder:
            calls.append(user)
            return own

        report = deferred_progress(provider, {"user": "ada", "data": {}}, transport=transport)
        assert report is not None
        report(1, total=2, message="first")
        report(2, total=2, meta={"stage": "done"})
        expected = [(1, 2, "first", None), (2, 2, None, {"stage": "done"})]
        assert transport.reports == expected
        assert own.reports == expected
        assert calls == ["ada"]

    def test_a_provider_returning_none_declines_and_the_transport_still_hears(self) -> None:
        transport = Recorder()
        calls: list[int] = []

        def provider() -> None:
            calls.append(1)

        report = deferred_progress(provider, {}, transport=transport)
        assert report is not None
        report(1)
        report(2)
        assert transport.reports == [(1, None, None, None), (2, None, None, None)]
        assert calls == [1]

    def test_the_spec_s_sink_alone_hears_when_the_transport_has_none(self) -> None:
        own = Recorder()
        report = deferred_progress(lambda: own, {}, transport=None)
        assert report is not None
        report(5, message="alone")
        assert own.reports == [(5, None, "alone", None)]


class TestResolveProgress:
    def test_the_provider_is_called_at_once_from_the_pool_and_both_sinks_hear(self) -> None:
        transport, own = Recorder(), Recorder()
        calls: list[Any] = []

        def provider(user: Any) -> Recorder:
            calls.append(user)
            return own

        report = resolve_progress(provider, {"user": "ada"}, transport=transport)
        assert calls == ["ada"]
        assert report is not None
        report(1, total=3)
        assert transport.reports == own.reports == [(1, 3, None, None)]

    def test_a_provider_returning_none_declines_and_the_transport_still_hears(self) -> None:
        transport = Recorder()
        report = resolve_progress(lambda: None, {}, transport=transport)
        assert report is not None
        report(1, message="only the transport")
        assert transport.reports == [(1, None, "only the transport", None)]


class TestOnlySeeds:
    """A registry narrowed to the names asked for."""

    def test_only_seeds_keeps_registration_order(self) -> None:
        pool_seeds = DEFAULT_POOL_SEEDS.extend(a=lambda: 1, b=lambda: 2, c=lambda: 3)
        assert list(only_seeds(pool_seeds, frozenset({"c", "a"})).resolvers()) == ["a", "c"]


class TestPoolKwargs:
    """The kernel's binder: the public one, with the call's two read off a pool's context."""

    def test_a_named_parameter_is_handed_the_context_s_and_none_for_an_absent_key(self) -> None:
        request = object()

        def fn(*, request: Any, view: Any, user: Any) -> None: ...

        pool = {"user": "u", "call_context": {"request": request}}
        assert pool_kwargs(fn, pool) == {"request": request, "view": None, "user": "u"}

    def test_a_context_of_none_hands_none(self) -> None:
        def fn(*, request: Any) -> None: ...

        assert pool_kwargs(fn, {"call_context": None}) == {"request": None}

    def test_a_pool_with_no_call_context_binds_as_published(self) -> None:
        """Nothing to read the two off, so a callable naming one is handed what the pool has."""

        def fn(*, request: Any = "default", user: Any) -> None: ...

        assert pool_kwargs(fn, {"user": "u"}) == {"user": "u"}

    def test_a_catch_all_is_handed_neither_and_a_pool_entry_outranks(self) -> None:
        def catch_all(**kwargs: Any) -> None: ...

        def named(*, request: Any) -> None: ...

        pool = {"user": "u", "call_context": {"request": "context", "view": "context"}}
        assert pool_kwargs(catch_all, pool) == {"user": "u"}
        assert pool_kwargs(named, {**pool, "request": "seed"}) == {"request": "seed"}

    def test_a_positional_only_name_is_never_handed(self) -> None:
        """Only a name a keyword can fill, as the public binder reads a signature."""

        def fn(request: Any, /) -> None: ...

        assert pool_kwargs(fn, {"call_context": {"request": "r"}}) == {}
