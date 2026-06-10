"""extract_json must survive the ways an LLM mangles JSON output: code fences,
chatty preamble, trailing commentary, and truncated arrays."""
import pytest

from agents.base import extract_json


def test_raw_object():
    assert extract_json('{"a": 1, "b": "two"}') == {"a": 1, "b": "two"}


def test_raw_array():
    assert extract_json('[1, 2, 3]') == [1, 2, 3]


def test_json_code_fence():
    text = 'Here you go:\n```json\n{"answer": "hi"}\n```\nHope that helps!'
    assert extract_json(text) == {"answer": "hi"}


def test_bare_code_fence():
    text = '```\n[{"x": 1}]\n```'
    assert extract_json(text) == [{"x": 1}]


def test_leading_prose_and_trailing_commentary():
    text = 'Sure! The result is {"key": "value"} — let me know if you need more.'
    assert extract_json(text) == {"key": "value"}


def test_salvages_truncated_array():
    # Model hit max_tokens mid-array; the salvage path keeps complete objects.
    text = '[{"a": 1}, {"b": 2}, {"c":'
    assert extract_json(text) == [{"a": 1}, {"b": 2}]


def test_empty_string_raises():
    with pytest.raises(ValueError):
        extract_json("")


def test_unparseable_raises():
    with pytest.raises(ValueError):
        extract_json("there is absolutely no json here")
