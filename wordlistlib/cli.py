"""Input/output conventions shared by every tool in this repository.

The rules, applied everywhere:

* ``-i/--input`` defaults to stdin and ``-o/--output`` defaults to stdout, so
  the tools compose in a pipeline.
* Anything that is not a wordlist candidate -- progress, counts, warnings,
  confirmation prompts -- goes to **stderr**, so ``tool ... > list.txt`` always
  produces a clean file.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

_QUIET = False


def set_quiet(quiet: bool) -> None:
    """Suppress :func:`log` output (warnings and errors still get through)."""
    global _QUIET
    _QUIET = bool(quiet)


def log(message: str = "") -> None:
    """Write an informational message to stderr, never to the wordlist."""
    if not _QUIET:
        print(message, file=sys.stderr)


def warn(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr)


def die(message: str, code: int = 1) -> NoReturn:  # noqa: F821
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(code)


@contextlib.contextmanager
def open_input(path: str | None, encoding: str = "utf-8"):
    """Open ``path`` for reading; stdin when it is ``None`` or ``'-'``."""
    if path is None or path == "-":
        yield sys.stdin
        return
    try:
        handle = open(path, encoding=encoding, errors="replace")
    except OSError as exc:
        die(f"cannot read {path}: {exc}")
    try:
        yield handle
    finally:
        handle.close()


@contextlib.contextmanager
def open_output(path: str | None, encoding: str = "utf-8"):
    """Open ``path`` for writing; stdout when it is ``None`` or ``'-'``."""
    if path is None or path == "-":
        yield sys.stdout
        return
    try:
        handle = open(path, "w", encoding=encoding, newline="\n")
    except OSError as exc:
        die(f"cannot write {path}: {exc}")
    try:
        yield handle
    finally:
        handle.close()


def iter_lines(handle, *, strip: bool = True, skip_empty: bool = True):
    """Iterate a file handle lazily, so multi-GB inputs stay streamable."""
    for line in handle:
        if strip:
            line = line.strip()
        else:
            line = line.rstrip("\n")
        if skip_empty and not line:
            continue
        yield line


def load_wordlist(path: str, *, dedupe: bool = True) -> list[str]:
    """Read a one-word-per-line file, preserving order, optionally deduped."""
    words: list[str] = []
    seen: set[str] = set()
    with open_input(path) as handle:
        for word in iter_lines(handle):
            if dedupe:
                if word in seen:
                    continue
                seen.add(word)
            words.append(word)
    if not words:
        die(f"{path} contains no usable words")
    return words


def sort_unique_file(path: str | Path) -> None:
    """Sort a file in place, dropping duplicates.

    Uses ``sort -u`` when it is available because it handles files larger than
    memory; falls back to an in-process sort (Windows, stripped containers)
    rather than failing outright, which the original scripts did.
    """
    path = str(path)
    sort_bin = shutil.which("sort")
    if sort_bin:
        result = subprocess.run(
            [sort_bin, "-u", path, "-o", path],
            capture_output=True,
            text=True,
            env={**os.environ, "LC_ALL": "C"},
        )
        if result.returncode == 0:
            return
        warn(f"sort -u failed on {path} ({result.stderr.strip()}); sorting in memory")
    with open(path, encoding="utf-8", errors="replace") as handle:
        lines = sorted({line.rstrip("\n") for line in handle})
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        for line in lines:
            handle.write(line + "\n")


def add_common_args(parser, *, quiet: bool = True, force: bool = True) -> None:
    """Attach the flags every tool shares."""
    if quiet:
        parser.add_argument(
            "-q", "--quiet", action="store_true",
            help="Suppress progress and statistics on stderr.",
        )
    if force:
        parser.add_argument(
            "--force", action="store_true",
            help="Skip the size confirmation prompt (for scripted runs).",
        )
