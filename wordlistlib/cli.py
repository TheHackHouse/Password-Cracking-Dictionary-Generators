"""Input/output conventions shared by every tool in this repository.

The rules, applied everywhere:

* ``-i/--input`` defaults to stdin and ``-o/--output`` defaults to stdout, so
  the tools compose in a pipeline.
* Anything that is not a wordlist candidate -- progress, counts, warnings,
  confirmation prompts -- goes to **stderr**, so ``tool ... > list.txt`` always
  produces a clean file.
* Every stream is UTF-8 with ``\\n`` line endings on every platform, whether it
  is a file or a pipe, so ``-o list.txt`` and ``> list.txt`` give the same
  bytes. Bytes that are not valid UTF-8 (real-world wordlists are full of
  them) pass through unchanged instead of being replaced.
"""

from __future__ import annotations

import argparse
import contextlib
import errno
import gzip
import heapq
import io
import itertools
import operator
import os
import re
import shutil
import subprocess
import sys
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import NoReturn

#: Candidates buffered before one joined write. Writing per candidate costs
#: roughly a third of the runtime of a generator; joining blocks recovers it.
DEFAULT_CHUNK_SIZE = 8192

#: Buffer for sequential file reads and writes. The default 8 KB means a
#: system call every few hundred words on a multi-gigabyte list.
IO_BUFFER = 1 << 20

#: Undecodable bytes are carried through as lone surrogates and written back
#: as the original bytes, so a latin-1 entry in a UTF-8 list survives intact.
ENCODING_ERRORS = "surrogateescape"

#: Python's gzip default is 9, which is several times slower than 6 for a
#: few percent of size. 6 is what the gzip command line uses.
GZIP_LEVEL = 6

#: Lines read per run by the in-process sort fallback (bytes of input).
SORT_RUN_BYTES = 128 * 1024 * 1024

_QUIET = False


def _reconfigure(stream, **options) -> None:
    try:
        stream.reconfigure(**options)
    except (AttributeError, ValueError, io.UnsupportedOperation):
        pass                      # replaced stream (tests) or already in use


def stdin():
    """``sys.stdin`` as UTF-8, whatever the platform's locale says.

    ``newline=None`` asks for universal newlines, which is what a file opened
    for reading gets. Without it stdin on Linux and macOS only splits on
    ``\\n``, so a list with old Mac line endings would read differently
    piped in than it does given with ``-i``.
    """
    _reconfigure(sys.stdin, encoding="utf-8", errors=ENCODING_ERRORS, newline=None)
    return sys.stdin


def stdout():
    """``sys.stdout`` as UTF-8 with ``\\n`` endings (no CRLF on Windows)."""
    _reconfigure(sys.stdout, encoding="utf-8", errors=ENCODING_ERRORS, newline="\n")
    return sys.stdout


def set_quiet(quiet: bool) -> None:
    """Suppress :func:`log` output (warnings and errors still get through)."""
    global _QUIET
    _QUIET = bool(quiet)
    # A message quoting an odd filename or word must not be able to crash the
    # run on a console that cannot encode it.
    _reconfigure(sys.stderr, errors="backslashreplace")


def log(message: str = "") -> None:
    """Write an informational message to stderr, never to the wordlist."""
    if not _QUIET:
        print(message, file=sys.stderr)


def warn(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr)


def die(message: str, code: int = 1) -> NoReturn:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(code)


def prompt(message: str) -> str:
    """Ask a question on stderr and read the answer from stdin.

    ``input()`` writes its prompt to stdout, which puts it in the wordlist
    and leaves the terminal looking hung whenever stdout is redirected.
    """
    sys.stderr.write(message)
    sys.stderr.flush()
    return sys.stdin.readline().strip()


def _is_broken_pipe(exc: OSError) -> bool:
    if isinstance(exc, BrokenPipeError):
        return True
    # Windows reports a closed pipe as EINVAL on the write or the flush.
    return (
        sys.platform == "win32"
        and exc.errno in (errno.EPIPE, errno.EINVAL)
        and exc.filename is None
    )


def _discard_stdout() -> None:
    """Point stdout at the null device so the exit-time flush cannot fail."""
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
    except (OSError, ValueError, io.UnsupportedOperation):
        pass


def run(main) -> None:
    """Run a tool's ``main``, exiting quietly on a closed pipe or Ctrl-C.

    ``tool ... | head`` closes the pipe early; that is not an error worth a
    traceback.
    """
    try:
        main()
        sys.stdout.flush()
    except KeyboardInterrupt:
        _discard_stdout()
        print("\nInterrupted.", file=sys.stderr)
        raise SystemExit(130) from None
    except OSError as exc:
        if not _is_broken_pipe(exc):
            raise
        _discard_stdout()
        raise SystemExit(141) from None


@contextlib.contextmanager
def open_input(path: str | None, encoding: str = "utf-8"):
    """Open ``path`` for reading; stdin when it is ``None`` or ``'-'``.

    A ``.gz`` path is decompressed transparently, so a gzipped dictionary can
    be fed straight in.
    """
    if path is None or path == "-":
        yield stdin()
        return
    path = str(path)
    try:
        if path.endswith(".gz"):
            handle = gzip.open(path, "rt", encoding=encoding, errors=ENCODING_ERRORS)
        else:
            handle = open(path, encoding=encoding, errors=ENCODING_ERRORS,
                          buffering=IO_BUFFER)
    except OSError as exc:
        die(f"cannot read {path}: {exc}")
    try:
        yield handle
    finally:
        handle.close()


def create_text_file(path: str):
    """Open ``path`` for writing with the conventions above; raises OSError.

    For the tools that write several files at once and so cannot use the
    single-output :func:`open_output` context manager.
    """
    return open(str(path), "w", encoding="utf-8", errors=ENCODING_ERRORS,
                newline="\n", buffering=IO_BUFFER)


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
            yield stdout()
            return
        raw = gzip.GzipFile(fileobj=sys.stdout.buffer, mode="wb",
                            compresslevel=GZIP_LEVEL)
        handle = io.TextIOWrapper(raw, encoding=encoding, errors=ENCODING_ERRORS,
                                  newline="\n")
        try:
            yield handle
        finally:
            handle.flush()
            handle.detach()
            raw.close()
        return

    path = str(path)
    try:
        if use_gzip:
            handle = gzip.open(path, "wt", compresslevel=GZIP_LEVEL,
                               encoding=encoding, errors=ENCODING_ERRORS, newline="\n")
        else:
            handle = open(path, "w", encoding=encoding, errors=ENCODING_ERRORS,
                          newline="\n", buffering=IO_BUFFER)
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

    * **chunked writes** -- candidates are pulled from the generator and
      joined in blocks of ``chunk_size``, so the per-candidate work happens
      in C rather than in a Python loop
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
        self._min_length = max(0, min_length)
        self._max_length = max_length
        self._skip = max(0, skip)
        self._limit = None if limit is None else max(0, limit)
        self.written = 0
        self.filtered = 0
        self.skipped = 0

    def feed(self, candidates) -> int:
        """Write every candidate that passes the filters. Returns the count."""
        write = self._handle.write
        chunk_size = self._chunk_size
        min_length, max_length = self._min_length, self._max_length
        limit = self._limit
        filtering = min_length > 0 or max_length is not None
        islice = itertools.islice
        source = iter(candidates)

        while True:
            # Never pull more than could still be written, so a limited run
            # stops the generator exactly where the output stops.
            want = chunk_size if limit is None else min(chunk_size, limit - self.written)
            if want <= 0:
                break
            batch = list(islice(source, want))
            if not batch:
                break

            if filtering:
                pulled = len(batch)
                if max_length is None:
                    batch = [c for c in batch if len(c) >= min_length]
                else:
                    batch = [c for c in batch if min_length <= len(c) <= max_length]
                self.filtered += pulled - len(batch)

            if self.skipped < self._skip:
                drop = min(self._skip - self.skipped, len(batch))
                self.skipped += drop
                batch = batch[drop:]

            if batch:
                write("\n".join(batch))
                write("\n")
                self.written += len(batch)

        return self.written

    def close(self) -> None:
        """Kept for callers; ``feed`` leaves nothing buffered."""

    def report(self) -> str:
        parts = [f"{self.written:,} written"]
        if self.filtered:
            parts.append(f"{self.filtered:,} outside the length range")
        if self.skipped:
            parts.append(f"{self.skipped:,} skipped")
        return ", ".join(parts)


def non_negative_int(text: str) -> int:
    """argparse type: a whole number that is zero or greater."""
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number") from None
    if value < 0:
        raise argparse.ArgumentTypeError(f"{value} is negative; it must be 0 or more")
    return value


def add_output_args(parser) -> None:
    """Attach the shared candidate-stream flags."""
    group = parser.add_argument_group("candidate stream")
    group.add_argument(
        "--min-length", type=non_negative_int, default=0, metavar="N",
        help="Drop candidates shorter than N characters before writing them.",
    )
    group.add_argument(
        "--max-length", type=non_negative_int, default=None, metavar="N",
        help="Drop candidates longer than N characters before writing them.",
    )
    group.add_argument(
        "--skip", type=non_negative_int, default=0, metavar="N",
        help="Skip the first N candidates, like hashcat's -s. Use with "
             "--limit to split one job across machines.",
    )
    group.add_argument(
        "--limit", type=non_negative_int, default=None, metavar="N",
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
    min_length = getattr(args, "min_length", 0) or 0
    max_length = getattr(args, "max_length", None)
    if max_length is not None and max_length < min_length:
        die("--max-length cannot be smaller than --min-length")
    return CandidateWriter(
        handle,
        min_length=min_length,
        max_length=max_length,
        skip=getattr(args, "skip", 0) or 0,
        limit=getattr(args, "limit", None),
    )


_chomp = operator.methodcaller("rstrip", "\r\n")


def iter_lines(handle, *, strip: bool = True, skip_empty: bool = True):
    """Iterate a file handle lazily, so multi-GB inputs stay streamable.

    ``strip=False`` removes only the line ending, for inputs where leading
    and trailing spaces are data (a pot file's plaintexts). The work is done
    by ``map``/``filter`` so there is no Python-level loop per line.
    """
    lines = map(str.strip, handle) if strip else map(_chomp, handle)
    return filter(None, lines) if skip_empty else lines


def unique(candidates):
    """Yield each distinct candidate once, in first-seen order."""
    seen: set[str] = set()
    add = seen.add
    for candidate in candidates:
        if candidate not in seen:
            add(candidate)
            yield candidate


_HEX_PLAINTEXT = re.compile(r"^\$HEX\[((?:[0-9A-Fa-f]{2})*)\]$")


def decode_pot_plaintext(text: str) -> str:
    """Decode hashcat's ``$HEX[...]`` form of a cracked plaintext.

    hashcat writes a plaintext that way when it contains a colon, a
    non-printable byte or anything outside ASCII. Bytes that are not UTF-8
    are carried through and written back out unchanged. A plaintext holding a
    line break cannot live in a one-per-line wordlist, so it is left encoded
    (hashcat decodes ``$HEX[]`` itself when it reads a wordlist).
    """
    match = _HEX_PLAINTEXT.match(text)
    if not match:
        return text
    decoded = bytes.fromhex(match.group(1)).decode("utf-8", ENCODING_ERRORS)
    if "\n" in decoded or "\r" in decoded:
        return text
    return decoded


def load_wordlist(path: str, *, dedupe: bool = True) -> list[str]:
    """Read a one-word-per-line file, preserving order, optionally deduped."""
    with open_input(path) as handle:
        words = list(iter_lines(handle))
    if dedupe:
        words = list(dict.fromkeys(words))
    if not words:
        die(f"{path} contains no usable words")
    return words


@lru_cache(maxsize=1)
def _posix_sort() -> str | None:
    """Path of a POSIX ``sort``, or None when there is not one to use.

    On Windows the first ``sort`` on PATH is usually System32's, which takes
    different options entirely; only a GNU one (Git Bash, MSYS, WSL) counts.
    """
    sort_bin = shutil.which("sort")
    if not sort_bin:
        return None
    if sys.platform == "win32":
        try:
            probe = subprocess.run(
                [sort_bin, "--version"], capture_output=True, text=True,
                stdin=subprocess.DEVNULL, timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if probe.returncode != 0 or "GNU" not in probe.stdout:
            return None
    return sort_bin


def _write_run(lines, directory: str) -> str:
    fd, name = tempfile.mkstemp(prefix="sort-run-", suffix=".tmp", dir=directory)
    with os.fdopen(fd, "wb", buffering=IO_BUFFER) as handle:
        handle.write(b"".join(lines))
    return name


def _external_sort_unique(path: str, run_bytes: int = SORT_RUN_BYTES) -> None:
    """Sort a file in place and drop duplicates without loading all of it.

    A classic external merge sort: the input is read in runs of about
    ``run_bytes``, each run is sorted and written to a temporary file next to
    the target, and the runs are merged. Memory is bounded by one run however
    large the file is. Ordering is by byte value, as ``LC_ALL=C sort`` does it.

    Lines keep their ``\\n`` while they are compared, in the runs and in the
    merge alike, so both stages agree on the order and equal lines always
    end up adjacent for the duplicate pass.
    """
    directory = os.path.dirname(os.path.abspath(path))
    runs: list[str] = []
    try:
        with open(path, "rb", buffering=IO_BUFFER) as source:
            while True:
                block = source.readlines(run_bytes)
                if not block:
                    break
                lines = sorted({line.rstrip(b"\r\n") + b"\n" for line in block})
                del block
                runs.append(_write_run(lines, directory))
                del lines

        fd, merged = tempfile.mkstemp(prefix="sort-out-", suffix=".tmp", dir=directory)
        runs.append(merged)
        with contextlib.ExitStack() as stack:
            out = stack.enter_context(os.fdopen(fd, "wb", buffering=IO_BUFFER))
            sources = [
                stack.enter_context(open(run, "rb", buffering=IO_BUFFER))
                for run in runs[:-1]
            ]
            # groupby collapses the duplicates that span runs.
            out.writelines(
                line for line, _ in itertools.groupby(heapq.merge(*sources))
            )
        os.replace(merged, path)
        runs.pop()
    finally:
        for run in runs:
            with contextlib.suppress(OSError):
                os.remove(run)


def sort_unique_file(path: str | Path) -> None:
    """Sort a file in place, dropping duplicates.

    Uses ``sort -u`` when a POSIX one is available: it is multi-threaded and
    several times faster. Otherwise (Windows without Git Bash, stripped
    containers) an in-process external merge sort does the same job, also
    without needing the file to fit in memory.
    """
    path = str(path)
    sort_bin = _posix_sort()
    if sort_bin:
        # -T keeps the temporary runs next to the output: /tmp is often far
        # smaller than the disk a 100 GB list is being written to.
        directory = os.path.dirname(os.path.abspath(path))
        result = subprocess.run(
            [sort_bin, "-u", "-T", directory, "-o", path, path],
            capture_output=True,
            text=True,
            env={**os.environ, "LC_ALL": "C"},
        )
        if result.returncode == 0:
            return
        warn(f"sort -u failed on {path} ({result.stderr.strip()}); sorting in-process")
    _external_sort_unique(path)


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
