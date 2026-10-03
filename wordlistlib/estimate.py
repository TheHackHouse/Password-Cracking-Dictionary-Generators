"""Candidate counting, output-size estimation and the 'are you sure' prompt.

These three things used to exist only inside ``leetspeak-generator.py`` while
the other generators -- which are just as capable of filling a disk -- had
nothing at all. Every generator now calls :func:`confirm_or_exit`.
"""

from __future__ import annotations

import sys

from . import cli

#: Refuse to generate more than this many candidates without --force.
DEFAULT_MAX_CANDIDATES = 50_000_000


def format_count(count: int) -> str:
    return f"{count:,}"


def format_size(size_bytes: int | float) -> str:
    """Format a byte count in B/KB/MB/GB/TB."""
    for unit, threshold in (
        ("TB", 1024 ** 4),
        ("GB", 1024 ** 3),
        ("MB", 1024 ** 2),
        ("KB", 1024),
    ):
        if size_bytes >= threshold:
            return f"{size_bytes / threshold:.2f} {unit}"
    return f"{int(size_bytes)} Bytes"


def estimate_size(count: int, avg_length: float) -> int:
    """Bytes needed for ``count`` candidates of ``avg_length`` plus newlines."""
    return int(count * (avg_length + 1))


def confirm_or_exit(
    count: int,
    *,
    avg_length: float | None = None,
    exact_bytes: int | None = None,
    force: bool = False,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
    label: str = "candidates",
) -> None:
    """Report the size of a job and get the go-ahead before doing the work.

    Pass ``exact_bytes`` when the tool can compute the real output size (the
    leetspeak generator can, because it knows every substitution length);
    otherwise pass ``avg_length`` for an estimate.

    ``--force`` skips the prompt entirely. Without a terminal attached and
    without ``--force``, anything over ``max_candidates`` is refused rather
    than silently filling the disk.
    """
    if exact_bytes is None:
        exact_bytes = estimate_size(count, avg_length or 0)
        qualifier = "~"
    else:
        qualifier = ""

    cli.log(f"Total {label}: {format_count(count)}")
    cli.log(f"Output size: {qualifier}{format_size(exact_bytes)}")

    if force:
        return

    if count <= max_candidates and not sys.stdin.isatty():
        # Small job in a script: just run it.
        return

    if not sys.stdin.isatty():
        cli.die(
            f"{format_count(count)} {label} exceeds the safety limit of "
            f"{format_count(max_candidates)} and there is no terminal to confirm on. "
            f"Re-run with --force to proceed anyway."
        )

    try:
        answer = input("Do you want to continue? (y/N): ").strip().lower()
    except EOFError:
        answer = ""
    if answer not in ("y", "yes"):
        cli.log("Aborted.")
        raise SystemExit(0)
