"""Spread a job over several CPU cores without changing its output.

Every tool here is a pure function of its input lines, so the input can be
cut into blocks, each block handed to a worker process, and the results
written back in the order the blocks were cut. ``--jobs 8`` therefore
produces byte-for-byte what ``--jobs 1`` does, only sooner.

How the pieces fit:

* The input is cut on line boundaries into blocks of a few megabytes. A
  plain file is described to the workers as byte ranges, which they read
  themselves, so the reading is parallel too. stdin and ``.gz`` inputs
  cannot be read from the middle, so the parent reads them and ships the
  bytes.
* Results are collected through a sliding window: only a bounded number of
  blocks are in flight or waiting to be written at once. Memory stays flat
  however large the input is, and a slow disk slows the workers down rather
  than letting finished blocks pile up.
* Workers hand back encoded bytes, so the parent only has to write them.

What a tool supplies is one module-level function that turns the text of a
block into a result, plus an optional initializer for per-worker state (a
vocabulary, a pot file). Both must be importable by name, because worker
processes on Windows and macOS start from a fresh interpreter.
"""

from __future__ import annotations

import gzip
import os
import sys
from collections import deque
from concurrent.futures import ProcessPoolExecutor

from . import cli

#: Input bytes per block. Big enough that the per-block overhead (one task,
#: one result, one pickle each way) is noise; small enough that the blocks
#: in flight for a few dozen workers fit comfortably in memory. Measured on
#: a 2 GB list: 4 MB blocks were no faster than 1 MB and used twice the
#: memory.
DEFAULT_BLOCK_BYTES = 1 << 20

#: Aim for results of about this size from tools whose output is much
#: larger than their input, by shrinking the input block to match.
TARGET_RESULT_BYTES = 8 << 20

#: Refuse to parallelise a job in which one input line alone expands past
#: this: the whole expansion has to exist in a worker before it is shipped.
MAX_LINE_RESULT_BYTES = 64 << 20

#: Windows cannot wait on more than this many worker processes at once.
MAX_WINDOWS_WORKERS = 61

#: Override for the block size, in bytes. For tuning and for tests, which
#: need many blocks out of a small file.
BLOCK_BYTES_ENV = "WORDLISTLIB_BLOCK_BYTES"


def add_jobs_arg(parser) -> None:
    parser.add_argument(
        "-j", "--jobs", type=cli.non_negative_int, default=1, metavar="N",
        help="Worker processes to use (default: 1). 0 means one per CPU "
             "core. The output is the same, in the same order, whatever "
             "the value.",
    )


def resolve_jobs(requested: int) -> int:
    """Turn the ``--jobs`` value into a worker count (0 means every core)."""
    if requested == 0:
        try:
            requested = len(os.sched_getaffinity(0))      # honours taskset/cgroups
        except AttributeError:
            requested = os.cpu_count() or 1
    if sys.platform == "win32":
        requested = min(requested, MAX_WINDOWS_WORKERS)
    return max(1, requested)


def effective_jobs(requested: int, blocker: str | None = None) -> int:
    """The worker count to use, or 1 with a warning when the job cannot split.

    ``blocker`` says why this particular run has to stay in one process (it
    needs to see every line at once, say). Being told is better than
    silently getting a slower run than was asked for.
    """
    jobs = resolve_jobs(requested)
    if jobs > 1 and blocker:
        cli.warn(f"--jobs ignored: {blocker}")
        return 1
    return jobs


def block_bytes(default: int = DEFAULT_BLOCK_BYTES) -> int:
    """The input block size, honouring the environment override."""
    override = os.environ.get(BLOCK_BYTES_ENV)
    if override:
        try:
            return max(1, int(override))
        except ValueError:
            cli.die(f"{BLOCK_BYTES_ENV} must be a whole number of bytes, got {override!r}")
    return max(1, default)


def block_bytes_for_expansion(input_bytes: int, output_bytes: int) -> int:
    """A block size for a job that writes ``output_bytes`` from ``input_bytes``.

    Sized so one block's result is about :data:`TARGET_RESULT_BYTES`, which
    keeps memory bounded when every input word becomes thousands of
    candidates.
    """
    if input_bytes <= 0 or output_bytes <= input_bytes:
        return block_bytes()
    ratio = output_bytes / input_bytes
    return block_bytes(max(256, min(DEFAULT_BLOCK_BYTES, int(TARGET_RESULT_BYTES / ratio))))


# --------------------------------------------------------------------------
# Cutting the input into blocks
# --------------------------------------------------------------------------

def _read_range(path: str, start: int, end: int) -> bytes:
    """The lines of ``path`` that *begin* in ``[start, end)``.

    Ranges are cut at arbitrary byte offsets, so a line usually straddles
    two of them. Giving each line to the range its first byte falls in means
    every line is read exactly once: a range skips the line it starts in the
    middle of, and finishes the line it ends in the middle of.
    """
    with open(path, "rb") as handle:
        if start:
            handle.seek(start - 1)
            handle.readline()             # to the first line starting at >= start
        position = handle.tell()
        if position >= end:
            return b""
        data = handle.read(end - position)
        if not data.endswith(b"\n"):
            data += handle.readline()
        return data


def _stream_blocks(handle, size: int):
    """Cut a binary stream that cannot be seeked into whole-line blocks."""
    while True:
        data = handle.read(size)
        if not data:
            return
        if not data.endswith(b"\n"):
            data += handle.readline()
        yield ("data", data)


def input_tasks(path: str | None, size: int | None = None):
    """Yield the tasks that together cover every line of ``path``.

    ``None`` or ``'-'`` is stdin. Tasks are opaque; pass them to
    :func:`ordered`.
    """
    size = size or block_bytes()
    if path is None or path == "-":
        yield from _stream_blocks(sys.stdin.buffer, size)
        return
    path = str(path)
    try:
        if path.endswith(".gz"):
            with gzip.open(path, "rb") as handle:
                yield from _stream_blocks(handle, size)
            return
        total = os.path.getsize(path)
        with open(path, "rb"):
            pass                          # fail here, not inside a worker
    except OSError as exc:
        cli.die(f"cannot read {path}: {exc}")
    for start in range(0, total, size):
        yield ("range", path, start, min(start + size, total))


def input_size(path: str | None) -> int | None:
    """Size in bytes of a plain input file, or None when it is not known."""
    if path is None or path == "-" or str(path).endswith(".gz"):
        return None
    try:
        return os.path.getsize(path)
    except OSError:
        return None


# --------------------------------------------------------------------------
# The worker side
# --------------------------------------------------------------------------

_WORKER = None


def _start_worker(worker, initializer, initargs) -> None:
    global _WORKER
    _WORKER = worker
    if initializer is not None:
        initializer(*initargs)


def _run_task(task):
    kind = task[0]
    if kind == "item":
        return _WORKER(task[1])
    data = _read_range(*task[1:]) if kind == "range" else task[1]
    return _WORKER(data.decode("utf-8", cli.ENCODING_ERRORS))


def item_tasks(items):
    """Tasks that hand each of ``items`` to the worker as it is."""
    return (("item", item) for item in items)


def lines(text: str, *, strip: bool = True, skip_empty: bool = True) -> list[str]:
    """The lines of a block, exactly as :func:`cli.iter_lines` would give them.

    A file opened in text mode treats ``\\r\\n`` and a lone ``\\r`` as line
    endings too, so the same is done here. ``str.splitlines`` is not used:
    it also breaks on form feeds and several Unicode separators, which a
    file does not.
    """
    if "\r" in text:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
    parts = text.split("\n")
    if parts and not parts[-1]:
        parts.pop()                       # the block ended with its newline
    if strip:
        parts = map(str.strip, parts)
    return list(filter(None, parts)) if skip_empty else list(parts)


def pack(candidates: list[str]) -> bytes:
    """Encode candidates as the bytes that go in the output, one per line."""
    if not candidates:
        return b""
    return ("\n".join(candidates) + "\n").encode("utf-8", cli.ENCODING_ERRORS)


def pack_filtered(candidates, min_length: int = 0,
                  max_length: int | None = None) -> tuple[bytes, int, int]:
    """Apply --min-length/--max-length and pack: ``(bytes, written, filtered)``."""
    if not isinstance(candidates, list):
        candidates = list(candidates)
    pulled = len(candidates)
    if max_length is not None:
        candidates = [c for c in candidates if min_length <= len(c) <= max_length]
    elif min_length > 0:
        candidates = [c for c in candidates if len(c) >= min_length]
    return pack(candidates), len(candidates), pulled - len(candidates)


# --------------------------------------------------------------------------
# The parent side
# --------------------------------------------------------------------------

def ordered(tasks, worker, *, jobs: int, initializer=None, initargs=()):
    """Run ``worker`` over ``tasks`` in ``jobs`` processes; yield results in order.

    At most ``jobs`` plus a small margin of tasks are submitted and not yet
    yielded, so neither the task source nor the results are ever read far
    ahead of the consumer. Close the generator (or let it finish) to stop
    the workers.
    """
    window = jobs + max(2, jobs // 2)
    pool = ProcessPoolExecutor(
        max_workers=jobs, initializer=_start_worker,
        initargs=(worker, initializer, initargs),
    )
    pending: deque = deque()
    try:
        for task in tasks:
            pending.append(pool.submit(_run_task, task))
            if len(pending) >= window:
                yield pending.popleft().result()
        while pending:
            yield pending.popleft().result()
    finally:
        for future in pending:
            future.cancel()
        pool.shutdown(wait=True, cancel_futures=True)


def _after_lines(data: bytes, count: int) -> int:
    """Offset just past the ``count``-th newline of ``data``."""
    offset = 0
    for _ in range(count):
        offset = data.index(b"\n", offset) + 1
    return offset


class BlockWriter:
    """Write workers' results in order, applying --skip and --limit.

    The parallel counterpart of :class:`cli.CandidateWriter`. Length
    filtering is done in the workers, where it is free to parallelise;
    skipping and limiting depend on position in the whole stream, so they
    are done here. Only the one or two blocks a boundary falls inside are
    ever looked into; the rest are written or dropped whole.
    """

    def __init__(self, handle, *, skip: int = 0, limit: int | None = None):
        handle.flush()
        self._write = handle.buffer.write
        self._skip = max(0, skip)
        self._limit = None if limit is None else max(0, limit)
        self.written = 0
        self.filtered = 0
        self.skipped = 0

    @property
    def full(self) -> bool:
        """True once --limit has been reached and nothing more is wanted."""
        return self._limit is not None and self.written >= self._limit

    def skip_ahead(self, count: int) -> bool:
        """Account for ``count`` lines without having them, if --skip covers them all.

        For a generator that knows how many candidates a piece of work will
        produce: a piece that falls wholly inside the skipped region need
        not be generated at all. Returns False, changing nothing, when any
        of the lines would have to be written.
        """
        if self._skip - self.skipped < count:
            return False
        self.skipped += count
        return True

    def add(self, data: bytes, count: int, filtered: int = 0) -> bool:
        """Write a block of ``count`` lines. Returns False when no more are wanted."""
        self.filtered += filtered
        if count and self.skipped < self._skip:
            drop = min(self._skip - self.skipped, count)
            self.skipped += drop
            count -= drop
            if count:
                data = data[_after_lines(data, drop):]
        if count and self._limit is not None:
            room = self._limit - self.written
            if count > room:
                data = data[:_after_lines(data, room)]
                count = room
        if count:
            self._write(data)
            self.written += count
        return not self.full

    def report(self) -> str:
        parts = [f"{self.written:,} written"]
        if self.filtered:
            parts.append(f"{self.filtered:,} outside the length range")
        if self.skipped:
            parts.append(f"{self.skipped:,} skipped")
        return ", ".join(parts)


def length_bounds(args) -> tuple[int, int | None]:
    """The validated ``(--min-length, --max-length)`` of parsed arguments."""
    min_length = getattr(args, "min_length", 0) or 0
    max_length = getattr(args, "max_length", None)
    if max_length is not None and max_length < min_length:
        cli.die("--max-length cannot be smaller than --min-length")
    return min_length, max_length


def block_writer_for(handle, args) -> BlockWriter:
    """Build a :class:`BlockWriter` from parsed --skip/--limit arguments."""
    length_bounds(args)
    return BlockWriter(
        handle,
        skip=getattr(args, "skip", 0) or 0,
        limit=getattr(args, "limit", None),
    )


def drain(results, writer: BlockWriter, totals: list[int] | None = None) -> None:
    """Feed ``(bytes, written, filtered, *counters)`` results to ``writer``.

    Any counters after the first three are summed into ``totals``. Stops the
    workers as soon as the writer has all it wants.
    """
    try:
        for data, count, filtered, *counters in results:
            if totals is not None:
                for index, value in enumerate(counters):
                    totals[index] += value
            if not writer.add(data, count, filtered):
                break
    finally:
        results.close()
