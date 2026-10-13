from __future__ import annotations

import copy
import json
import pickle
from collections.abc import Callable

import pytest

from django_service_specs.parameters.coded_message import CodedMessage

MESSAGE = "This field is required."


def test_it_is_its_message_to_everything_that_reads_a_string() -> None:
    message = CodedMessage(MESSAGE, "required")
    assert message == MESSAGE
    assert hash(message) == hash(MESSAGE)
    assert message in {MESSAGE}
    assert {MESSAGE: 1}[message] == 1
    assert json.dumps([message]) == json.dumps([MESSAGE])
    assert f"{message}" == MESSAGE
    assert type(str(message)) is str


def test_its_code_never_takes_part_in_equality() -> None:
    # Two codes on one message are still one message: a tree compared with a
    # plain one, or with a library's, compares what a caller reads.
    assert CodedMessage(MESSAGE, "required") == CodedMessage(MESSAGE, "invalid")


def test_it_carries_its_code() -> None:
    assert CodedMessage(MESSAGE, code="required").code == "required"


def test_its_repr_is_its_message_s() -> None:
    # So the text of a printed tree is the text a tree of plain strings makes.
    assert repr(CodedMessage(MESSAGE, "required")) == repr(MESSAGE)
    assert str({"n": [CodedMessage(MESSAGE, "required")]}) == "{'n': ['This field is required.']}"


@pytest.mark.parametrize("protocol", range(pickle.HIGHEST_PROTOCOL + 1))
def test_a_pickled_message_keeps_its_code(protocol: int) -> None:
    restored = pickle.loads(pickle.dumps(CodedMessage(MESSAGE, "required"), protocol))
    assert type(restored) is CodedMessage
    assert (restored, restored.code) == (MESSAGE, "required")


@pytest.mark.parametrize("duplicate", [copy.copy, copy.deepcopy])
def test_a_copied_message_keeps_its_code(duplicate: Callable[[CodedMessage], CodedMessage]) -> None:
    restored = duplicate(CodedMessage(MESSAGE, "required"))
    assert type(restored) is CodedMessage
    assert (restored, restored.code) == (MESSAGE, "required")
