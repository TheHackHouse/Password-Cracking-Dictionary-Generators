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
import gzip
import io
import os
import shutil
import subprocess
import sys
from pathlib import Path

#: Candidates buffered before one joined write. Writing per candidate costs
#: roughly a third of the runtime of a generator; joining blocks recovers it.
DEFAULT_CHUNK_SIZE = 8192

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
    """Open ``path`` for reading; stdin when it is ``None`` or ``'-'``.

    A ``.gz`` path is decompressed transparently, so a gzipped dictionary can
    be fed straight in.
    """
    if path is None or path == "-":
        yield sys.stdin
        return
    try:
        if path.endswith(".gz"):
            handle = gzip.open(path, "rt", encoding=encoding, errors="replace")
        else:
            handle = open(path, encoding=encoding, errors="replace")
    except OSError as exc:
        die(f"cannot read {path}: {exc}")
    try:
        yield handle
    finally:
        handle.close()


@contextlib.contextmanager
def open_output(path: str | None, encoding: str = "utf-8", compress: bool = False):
    """Open ``path`` for writing; stdout when it is ``None`` or ``'-'``.

    ``compress`` (or a ``.gz`` path) writes a gzip stream. hashcat 6.2.4 and
    later read gzipped wordlists directly, which trades CPU for disk and is
    usually a win on network or spinning storage.
    """
    use_gzip = compress or (path or "").endswith(".gz")

    if path is None or path == "-":
        if not use_gzip:
            yield sys.stdout
            return
        raw = gzip.GzipFile(fileobj=sys.stdout.buffer, mode="wb")
        handle = io.TextIOWrapper(raw, encoding=encoding, newline="\n")
        try:
            yield handle
        finally:
            handle.flush()
            handle.detach()
            raw.close()
        return

    try:
        if use_gzip:
            handle = gzip.open(path, "wt", encoding=encoding, newline="\n")
        else:
            handle = open(path, "w", encoding=encoding, newline="\n")
    except OSError as exc:
        die(f"cannot write {path}: {exc}")
    try:
        yield handle
    finally:
        handle.close()


class CandidateWriter:
    """Buffered, filtering sink for generated candidates.

    Every generator routes its output through this, which gives all of them
    the same three things at once:

    * **chunked writes** -- candidates are joined in blocks of
      ``chunk_size`` instead of one ``write()`` call each
    * **length filtering** -- candidates outside the target's password policy
      are dropped before they cost any I/O
    * **skip/limit** -- a slice of the candidate stream, mirroring hashcat's
      ``-s``/``-l``, so one job can be split across machines

    ``feed`` stops consuming the generator once ``limit`` is reached, so a
    limited run does not pay for candidates it will not write.
    """

    def __init__(
        self,
        handle,
        *,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        min_length: int = 0,
        max_length: int | None = None,
        skip: int = 0,
        limit: int | None = None,
    ):
        self._handle = handle
        self._chunk_size = max(1, chunk_size)
        self._min_length = min_length
        self._max_length = max_length
        self._skip = skip
        self._limit = limit
        self._buffer: list[str] = []
        self.written = 0
        self.filtered = 0
        self.skipped = 0

    def feed(self, candidates) -> int:
        """Write every candidate that passes the filters. Returns the count."""
        buffer = self._buffer
        append = buffer.append
        chunk_size = self._chunk_size
        min_length, max_length = self._min_length, self._max_length
        skip, limit = self._skip, self._limit
        filtering = min_length > 0 or max_length is not None

        for candidate in candidates:
            if filtering:
                length = len(candidate)
                if length < min_length or (max_length is not None and length > max_length):
                    self.filtered += 1
                    continue
            if self.skipped < skip:
                self.skipped += 1
                continue
            append(candidate)
            self.written += 1
            if len(buffer) >= chunk_size:
                self._flush()
            if limit is not None and self.written >= limit:
                break

        self._flush()
        return self.written

    def _flush(self) -> None:
        if self._buffer:
            self._handle.write("\n".join(self._buffer))
            self._handle.write("\n")
            self._buffer.clear()

    def close(self) -> None:
        self._flush()

    def report(self) -> str:
        parts = [f"{self.written:,} written"]
        if self.filtered:
            parts.append(f"{self.filtered:,} outside the length range")
        if self.skipped:
            parts.append(f"{self.skipped:,} skipped")
        return ", ".join(parts)


def add_output_args(parser) -> None:
    """Attach the shared candidate-stream flags."""
    group = parser.add_argument_group("candidate stream")
    group.add_argument(
        "--min-length", type=int, default=0, metavar="N",
        help="Drop candidates shorter than N characters before writing them.",
    )
    group.add_argument(
        "--max-length", type=int, default=None, metavar="N",
        help="Drop candidates longer than N characters before writing them.",
    )
    group.add_argument(
        "--skip", type=int, default=0, metavar="N",
        help="Skip the first N candidates, like hashcat's -s. Use with "
             "--limit to split one job across machines.",
    )
    group.add_argument(
        "--limit", type=int, default=None, metavar="N",
        help="Stop after writing N candidates, like hashcat's -l.",
    )
    group.add_argument(
        "--gzip", action="store_true",
        help="Write a gzip stream. hashcat 6.2.4+ reads gzipped wordlists "
             "directly. Implied by a .gz output path.",
    )


def sliced_total(total: int, args) -> int:
    """Adjust a predicted candidate count for --skip/--limit.

    Length filtering cannot be predicted without generating, so a run using
    --min-length/--max-length writes no more than this, usually fewer.
    """
    remaining = max(0, total - (getattr(args, "skip", 0) or 0))
    limit = getattr(args, "limit", None)
    return min(remaining, limit) if limit is not None else remaining


def writer_for(handle, args) -> CandidateWriter:
    """Build a :class:`CandidateWriter` from parsed --min-length/--skip/... args."""
    return CandidateWriter(
        handle,
        min_length=getattr(args, "min_length", 0) or 0,
        max_length=getattr(args, "max_length", None),
        skip=getattr(args, "skip", 0) or 0,
        limit=getattr(args, "limit", None),
    )


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
