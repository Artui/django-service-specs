"""``refusal_messages``: a refusal tree read as paths to messages."""

from __future__ import annotations

from django.utils.translation import gettext_lazy

from django_service_specs.parameters.refusal_messages import refusal_messages


def test_a_refusal_tree_is_read_as_paths_to_messages() -> None:
    tree = {
        "non_field_errors": ["Check the shelf."],
        "title": ["Too long.", gettext_lazy("Twice.")],
        "books": {"1": {"__all__": ["Missing."], "isbn": ["Malformed."]}},
    }
    assert list(refusal_messages(tree)) == [
        ((), "Check the shelf."),
        (("title",), "Too long."),
        (("title",), "Twice."),
        (("books", "1"), "Missing."),
        (("books", "1", "isbn"), "Malformed."),
    ]


def test_a_message_that_is_no_list_is_one_message_not_its_characters() -> None:
    ((path, text),) = refusal_messages(gettext_lazy("Whole."))
    # A lazy proxy equals its string, so only the type shows it was rendered:
    # a join over the messages raises on a proxy.
    assert (path, type(text)) == ((), str)
    assert text == "Whole."
