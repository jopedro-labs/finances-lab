"""Unit tests for src/utils/logger/logger.py."""

from __future__ import annotations

from src.utils.logger.logger import Logger, logger


def test_info_prints_to_stdout(capsys: object) -> None:
    """Validates info() writes an INFO-prefixed line to stdout."""
    log = Logger()
    log.info("hello info")
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert "INFO" in captured.out
    assert "hello info" in captured.out


def test_success_prints_to_stdout(capsys: object) -> None:
    """Validates success() writes a SUCCESS-prefixed line to stdout."""
    log = Logger()
    log.success("all good")
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert "SUCCESS" in captured.out
    assert "all good" in captured.out


def test_warning_prints_to_stdout(capsys: object) -> None:
    """Validates warning() writes a WARNING-prefixed line to stdout."""
    log = Logger()
    log.warning("heads up")
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert "WARNING" in captured.out
    assert "heads up" in captured.out


def test_error_prints_to_stderr(capsys: object) -> None:
    """Validates error() writes an ERROR-prefixed line to stderr."""
    log = Logger()
    log.error("something broke")
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert "ERROR" in captured.err
    assert "something broke" in captured.err


def test_error_with_exception_includes_details(capsys: object) -> None:
    """Validates error() includes the exception message when provided."""
    log = Logger()
    log.error("failed", exception=ValueError("bad value"))
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert "bad value" in captured.err


def test_section_prints_uppercase_title(capsys: object) -> None:
    """Validates section() uppercases the title."""
    log = Logger()
    log.section("my section")
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert "MY SECTION" in captured.out


def test_subsection_prints_message(capsys: object) -> None:
    """Validates subsection() outputs the message to stdout."""
    log = Logger()
    log.subsection("sub task")
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert "sub task" in captured.out


def test_print_without_color(capsys: object) -> None:
    """Validates print() outputs the raw message without ANSI codes."""
    log = Logger()
    log.print("raw output")
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert "raw output" in captured.out


def test_print_with_color_no_tty(capsys: object) -> None:
    """Validates print() suppresses ANSI codes when not a TTY (default in tests)."""
    log = Logger()
    log.print("colored output", color="\033[92m")
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert "colored output" in captured.out
    assert "\033[0m" not in captured.out


def test_print_with_color_tty_enabled(capsys: object) -> None:
    """Validates print() emits ANSI codes when colors are explicitly enabled."""
    log = Logger()
    log._colors_enabled = True
    log.print("colored output", color="\033[92m")
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert "colored output" in captured.out
    assert "\033[0m" in captured.out


def test_global_logger_instance_is_logger() -> None:
    """Validates that the module-level logger is a Logger instance."""
    assert isinstance(logger, Logger)
