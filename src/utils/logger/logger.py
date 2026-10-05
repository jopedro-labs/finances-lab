from __future__ import annotations

import sys
from datetime import datetime
from typing import Final


class Logger:
    """
    Standardized ANSI-colored logger for automation pipelines.
    Provides clean, professional terminal output without file persistence.
    """

    # ANSI Escape Sequences for Terminal Formatting
    _HEADER: Final[str] = "\033[95m"
    _BLUE: Final[str] = "\033[94m"
    _GREEN: Final[str] = "\033[92m"
    _WARNING: Final[str] = "\033[93m"
    _FAIL: Final[str] = "\033[91m"
    _ENDC: Final[str] = "\033[0m"
    _BOLD: Final[str] = "\033[1m"

    def __init__(self) -> None:
        """Initializes the logger instance. No file I/O setup."""
        self._colors_enabled: bool = sys.stdout.isatty()

    @staticmethod
    def _get_timestamp() -> str:
        """Returns current timestamp in YYYY-MM-DD HH:MM:SS format."""
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _c(self, code: str) -> str:
        """Returns the ANSI code only when stdout is a TTY."""
        return code if self._colors_enabled else ""

    def info(self, message: str) -> None:
        """Standard informational message."""
        print(f"[INFO {self._get_timestamp()}] {message}")

    def success(self, message: str) -> None:
        """Success message highlighted in green."""
        g, end = self._c(self._GREEN), self._c(self._ENDC)
        print(f"[{g}SUCCESS {self._get_timestamp()}]{end} {message}")

    def warning(self, message: str) -> None:
        """Warning alert highlighted in yellow."""
        y, end = self._c(self._WARNING), self._c(self._ENDC)
        print(f"[{y}WARNING {self._get_timestamp()}]{end} {message}")

    def error(self, message: str, exception: Exception | None = None) -> None:
        """Error message in red to stderr. Optionally logs the exception details."""
        error_msg: str = f"{message} | Error: {exception}" if exception else message
        r, end = self._c(self._FAIL), self._c(self._ENDC)
        print(f"[{r}ERROR {self._get_timestamp()}]{end} {error_msg}", file=sys.stderr)

    def section(self, title: str) -> None:
        """Major structural header for the log output."""
        b, h, end = self._c(self._BOLD), self._c(self._HEADER), self._c(self._ENDC)
        print(f"[{self._get_timestamp()}] {b}{h}{title.upper()}{end}")

    def subsection(self, message: str) -> None:
        """Bold informational message to distinguish sub-tasks within a section."""
        b, end = self._c(self._BOLD), self._c(self._ENDC)
        print(f"[{self._get_timestamp()}] {b}{message}{end}")

    def print(self, message: str, color: str | None = None) -> None:
        """Direct replacement for the built-in print command."""
        c: str = self._c(color) if color else ""
        end: str = self._c(self._ENDC) if color else ""
        print(f"{c}{message}{end}")


# Global instance for project-wide use
logger: Logger = Logger()
