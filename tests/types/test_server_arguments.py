from __future__ import annotations

import copy
import dataclasses
import pickle

import pytest

from django_service_specs.types.server_arguments import ServerArguments


def test_nothing_is_supplied_by_default() -> None:
    server = ServerArguments()
    assert dict(server.values) == {}
    assert server.withheld == frozenset()
    assert server.names() == frozenset()


def test_names_are_the_bound_and_the_withheld_together() -> None:
    server = ServerArguments(
        values={"project_pk": 7, "account_pk": 3},
        withheld=frozenset({"draw_request_pk", "invoice_pk"}),
    )
    assert server.names() == {"project_pk", "account_pk", "draw_request_pk", "invoice_pk"}
    assert isinstance(server.names(), frozenset)


def test_the_values_are_copied_so_a_later_change_to_the_mapping_reaches_nothing() -> None:
    # A transport checks the binding once, at construction, and applies it on
    # every call after: a value added to the caller's dict afterwards would
    # bypass that check, so the binding holds its own copy.
    given = {"project_pk": 7}
    server = ServerArguments(values=given)
    given["draw_request_pk"] = 9
    assert server.values == {"project_pk": 7}
    assert server.values is not given


def test_the_values_cannot_be_changed_after_the_check() -> None:
    # The same hole from the other side: a key set on the binding itself
    # after the check ran would reach every call unchecked.
    server = ServerArguments(values={"project_pk": 7})
    with pytest.raises(TypeError):
        server.values["tenant_pk"] = 1  # the mapping refuses assignment
    assert server.values == {"project_pk": 7}


def test_it_copies_and_pickles_like_any_value_a_transport_holds() -> None:
    # A toolset deep-copies its per-tool map, and a queue pickles what it
    # carries; a copy is read-only too.
    server = ServerArguments(values={"project_pk": 7}, withheld=frozenset({"draw_request_pk"}))
    for copied in (copy.deepcopy(server), copy.copy(server), pickle.loads(pickle.dumps(server))):
        assert copied == server
        with pytest.raises(TypeError):
            copied.values["tenant_pk"] = 1


def test_a_set_of_withheld_names_is_held_as_a_frozenset() -> None:
    server = ServerArguments(withheld={"draw_request_pk"})
    assert server.withheld == frozenset({"draw_request_pk"})
    assert isinstance(server.withheld, frozenset)


def test_a_bare_string_is_refused_as_the_withheld_names() -> None:
    # ``frozenset("pk")`` is ``{"p", "k"}``: a set of characters no parameter is
    # named, which the static check would refuse letter by letter.
    with pytest.raises(TypeError, match="a collection of names, not one string"):
        ServerArguments(withheld="draw_request_pk")


def test_it_is_frozen_equal_by_value_and_hashable() -> None:
    one = ServerArguments(values={"project_pk": 7}, withheld=frozenset({"draw_request_pk"}))
    other = ServerArguments(values={"project_pk": 7}, withheld=frozenset({"draw_request_pk"}))
    assert one == other
    assert hash(one) == hash(other)
    assert one != ServerArguments(values={"project_pk": 8}, withheld=frozenset({"draw_request_pk"}))
    with pytest.raises(dataclasses.FrozenInstanceError):
        one.withheld = frozenset()
