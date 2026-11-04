"""Tests for console log coloring in the TUI."""

from __future__ import annotations

import pytest

from slime.tui.screens.server import _colorize_log_line, slime_message


@pytest.mark.parametrize(
    "line",
    [
        "[12:36:55 ERROR]: Unable to load the world",
        "java.lang.IllegalStateException: broken",
        "org.bukkit.craftbukkit.v1_12_R1.SomeException: failed",
        "\tat net.minecraft.server.Main.main(Main.java:123)",
        "Caused by: java.io.IOException: nope",
        "Suppressed: java.lang.RuntimeException: hidden",
        "... 12 more",
        'Exception in thread "main" java.lang.NullPointerException',
        "OutOfMemoryError: Java heap space",
    ],
)
def test_exception_lines_are_red(line: str) -> None:
    assert _colorize_log_line(line).style == "red"


def test_info_line_keeps_info_color() -> None:
    assert _colorize_log_line("[12:00:00 INFO]: Ready").style == "white"


def test_plain_line_is_not_colored() -> None:
    assert _colorize_log_line("a normal plugin message").style in (None, "")


def test_slime_prefix_is_bold_bright_green() -> None:
    text = _colorize_log_line(slime_message("Stopping server..."))
    assert text.plain == "[slime] Stopping server..."
    assert text.spans[0].start == 0
    assert text.spans[0].end == len("[slime]")
    assert text.spans[0].style == "bold bright_green"


def test_done_word_is_bright_green() -> None:
    text = _colorize_log_line("[12:00:00 INFO]: Done (1.234s)! For help, type help")
    assert text.style == "white"
    assert any(
        text.plain[span.start : span.end].startswith("Done")
        and span.style == "bold bright_green"
        for span in text.spans
    )
