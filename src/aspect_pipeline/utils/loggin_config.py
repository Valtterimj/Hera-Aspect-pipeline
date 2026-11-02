import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, Literal

from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table
from rich.text import Text


Log_level = Literal["DEBUG", "INFO", "WARNING", "ERROR"]

PACKAGE_LOGGER = "aspect_pipeline"

# One console shared by the log handler, section rules and the summary so their output stays in order
console = Console(stderr=True)


class _RecordCollector(logging.Handler):
    """Logging handler that keeps every WARNING-or-worse record for the end-of-run summary."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@dataclass(frozen=True)
class SectionResult:
    title: str
    seconds: float
    warnings: int
    errors: int
    failed: bool


_collector = _RecordCollector()
_sections: list[SectionResult] = []


def setup_logging(level: Log_level = "INFO") -> None:
    """
    Configure global logging for the pipeline.

    Args:
        level: Log level for the pipeline's own loggers. Third-party libraries are
            capped at INFO so that DEBUG does not flood the console with their output.
    """
    handler = RichHandler(
        console=console,
        show_path=True,
        rich_tracebacks=True,
        log_time_format="[%H:%M:%S]",
    )
    root_level = logging.INFO if level == "DEBUG" else getattr(logging, level)
    logging.basicConfig(
        level=root_level,
        format="%(message)s",
        handlers=[handler, _collector],
    )
    logging.getLogger(PACKAGE_LOGGER).setLevel(getattr(logging, level))


def _rules_enabled() -> bool:
    return logging.getLogger(PACKAGE_LOGGER).isEnabledFor(logging.INFO)


def _count(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


@contextmanager
def log_section(title: str) -> Iterator[None]:
    """
    Print a titled divider around a block of work and record its outcome for the summary.

    Args:
        title: Section title, e.g. "Level 0 · Vis".

    Raises:
        Re-raises any exception from the block after recording the section as failed.
    """
    start_index = len(_collector.records)
    start = time.perf_counter()
    if _rules_enabled():
        console.rule(Text(title, style="bold cyan"))

    failed = False
    try:
        yield
    except BaseException:
        failed = True
        raise
    finally:
        seconds = time.perf_counter() - start
        new_records = _collector.records[start_index:]
        warnings = sum(r.levelno == logging.WARNING for r in new_records)
        errors = sum(r.levelno >= logging.ERROR for r in new_records)
        _sections.append(SectionResult(title, seconds, warnings, errors, failed))

        if _rules_enabled():
            parts = [title, "failed" if failed else "done", f"{seconds:.1f} s", _count(warnings, "warning")]
            if errors:
                parts.append(_count(errors, "error"))
            style = "red" if failed or errors else "yellow" if warnings else "dim"
            console.rule(Text(" · ".join(parts), style=style), style=style)
            console.print()


def print_summary() -> None:
    """Print a table of every section run and every warning or error logged so far."""
    console.print()
    console.rule(Text("Summary", style="bold"))

    if _sections:
        sections = Table(show_edge=False, header_style="bold")
        sections.add_column("Section")
        sections.add_column("Status")
        sections.add_column("Time", justify="right")
        sections.add_column("Warnings", justify="right")
        sections.add_column("Errors", justify="right")
        for s in _sections:
            if s.failed:
                status = Text("failed", style="bold red")
            elif s.errors:
                status = Text("errors", style="red")
            elif s.warnings:
                status = Text("warnings", style="yellow")
            else:
                status = Text("ok", style="green")
            sections.add_row(s.title, status, f"{s.seconds:.1f} s", str(s.warnings), str(s.errors))
        console.print(sections)

    records = _collector.records
    if not records:
        console.print(Text("No warnings or errors.", style="green"))
        return

    issues = Table(show_edge=False, header_style="bold", title=f"{_count(len(records), 'issue')}")
    issues.add_column("Level")
    issues.add_column("Source", style="dim")
    issues.add_column("Message")
    for r in records:
        style = "yellow" if r.levelno == logging.WARNING else "red"
        source = r.name.removeprefix(f"{PACKAGE_LOGGER}.")
        issues.add_row(Text(r.levelname, style=style), source, r.getMessage())
    console.print(issues)
