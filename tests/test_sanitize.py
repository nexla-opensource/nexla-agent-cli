from __future__ import annotations

from nexla_cli.sanitize import sanitize


def test_strips_ansi_escape_sequences() -> None:
    assert sanitize("hello\x1b[31mred\x1b[0mworld") == "helloredworld"


def test_strips_control_characters_except_newline_and_tab() -> None:
    assert sanitize("a\x00b\x07c\nd\te") == "abc\nd\te"


def test_strips_zero_width_and_bidi_characters() -> None:
    hidden = "hello" + chr(0x200B) + "world" + chr(0xFEFF) + chr(0x202E) + "x"
    assert sanitize(hidden) == "helloworldx"


def test_leaves_legitimate_unicode_untouched() -> None:
    text = "café 日本語 🎉 naïve"
    assert sanitize(text) == text


def test_recurses_through_dicts_and_lists() -> None:
    data = {
        "name": "s\x1b[31m1",
        "tags": ["a\x00", "b"],
        "nested": {"x": "y" + chr(0x200B) + "z"},
    }
    assert sanitize(data) == {
        "name": "s1",
        "tags": ["a", "b"],
        "nested": {"x": "yz"},
    }


def test_non_string_values_pass_through() -> None:
    assert sanitize({"id": 1, "active": True, "meta": None}) == {
        "id": 1,
        "active": True,
        "meta": None,
    }


def test_list_of_scalars() -> None:
    assert sanitize([1, "a\x00b", None, True]) == [1, "ab", None, True]
