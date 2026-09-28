from __future__ import annotations

from django_service_specs.parameters.utils import NON_FIELD_ERRORS, merge_detail, nest_detail


def test_non_field_errors_is_django_and_drfs_spelling() -> None:
    assert NON_FIELD_ERRORS == "non_field_errors"


def test_nest_detail_roots_a_child_under_its_path() -> None:
    assert nest_detail(("books", 1), {"title": ["taken"]}) == {"books": {1: {"title": ["taken"]}}}
    assert nest_detail(("title",), ["taken"]) == {"title": ["taken"]}


def test_nest_detail_with_no_path_keeps_a_tree_and_roots_messages_under_non_field_errors() -> None:
    tree = {"title": ["taken"]}
    nested = nest_detail((), tree)
    assert nested == tree
    assert nested is not tree
    assert nest_detail((), ("bad",)) == {NON_FIELD_ERRORS: ["bad"]}


def test_merge_detail_concatenates_messages_and_merges_subtrees() -> None:
    first = {"title": ["a"], "books": {0: {"title": ["b"]}}}
    second = {"title": ["c"], "books": {0: {"isbn": ["d"]}, 2: {"title": ["e"]}}, "pk": ["f"]}
    assert merge_detail(first, second) == {
        "title": ["a", "c"],
        "books": {0: {"title": ["b"], "isbn": ["d"]}, 2: {"title": ["e"]}},
        "pk": ["f"],
    }


def test_merge_detail_moves_a_message_list_meeting_a_subtree_under_non_field_errors() -> None:
    whole = {"author": ["Not allowed."]}
    inside = {"author": {"name": ["Required."], NON_FIELD_ERRORS: ["Stale."]}}
    assert merge_detail(whole, inside) == {
        "author": {NON_FIELD_ERRORS: ["Not allowed.", "Stale."], "name": ["Required."]}
    }
    # Either side may be the list; first's messages still come first.
    assert merge_detail(inside, whole) == {
        "author": {"name": ["Required."], NON_FIELD_ERRORS: ["Stale.", "Not allowed."]}
    }


def test_merge_detail_modifies_neither_input() -> None:
    first = {"books": {0: {"title": ["a"]}}, "title": ["b"]}
    second = {"books": {0: {"title": ["c"]}}, "title": ["d"]}
    merge_detail(first, second)
    assert first == {"books": {0: {"title": ["a"]}}, "title": ["b"]}
    assert second == {"books": {0: {"title": ["c"]}}, "title": ["d"]}
