#!/usr/bin/env python3
"""Generate keyboard walks -- sequences of adjacent keys such as 1q2w3e.

The candidate count is worked out before anything is generated, so the
confirmation prompt is useful rather than decorative, and walks are streamed to
the output instead of being collected in a list. Growth is roughly 6.6x per
extra character on qwerty: length 6 is ~514k walks, length 8 is ~22M.

Keys are neighbours when they touch on a grid in which the number row sits
one key to the left of the letter rows, so 1 is above q and 2 is above w.
That is what makes 1q2w3e, 1qaz and zaq1 all walks.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_here = Path(__file__).resolve().parent
for _candidate in (_here, _here.parent):
    if (_candidate / "wordlistlib").is_dir():
        sys.path.insert(0, str(_candidate))
        break

from wordlistlib import cli, estimate, parallel  # noqa: E402

LAYOUTS: dict[str, list[list[str]]] = {
    "qwerty": [
        ['`', '1', '2', '3', '4', '5', '6', '7', '8', '9', '0', '-', '='],
        ['q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p', '[', ']', '\\'],
        ['a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l', ';', '\''],
        ['z', 'x', 'c', 'v', 'b', 'n', 'm', ',', '.', '/'],
    ],
    "qwertyshifted": [
        ['~', '!', '@', '#', '$', '%', '^', '&', '*', '(', ')', '_', '+'],
        ['`', '1', '2', '3', '4', '5', '6', '7', '8', '9', '0', '-', '='],
        ['q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p', '[', ']', '\\'],
        ['a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l', ';', '\''],
        ['z', 'x', 'c', 'v', 'b', 'n', 'm', ',', '.', '/'],
    ],
    "qwertyshifted1": [
        ['`', '1', '2', '3', '4', '5', '6', '7', '8', '9', '0', '-', '='],
        ['~', '!', '@', '#', '$', '%', '^', '&', '*', '(', ')', '_', '+'],
        ['q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p', '[', ']', '\\'],
        ['a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l', ';', '\''],
        ['z', 'x', 'c', 'v', 'b', 'n', 'm', ',', '.', '/'],
    ],
    "qwertyshifted2": [
        ['~', '!', '@', '#', '$', '%', '^', '&', '*', '(', ')', '_', '+'],
        ['q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p', '[', ']', '\\'],
        ['a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l', ';', '\''],
        ['z', 'x', 'c', 'v', 'b', 'n', 'm', ',', '.', '/'],
    ],
    "dvorak": [
        ['`', '1', '2', '3', '4', '5', '6', '7', '8', '9', '0', '[', ']'],
        ['\'', ',', '.', 'p', 'y', 'f', 'g', 'c', 'r', 'l', '/', '=', '\\'],
        ['a', 'o', 'e', 'u', 'i', 'd', 'h', 't', 'n', 's', '-'],
        [';', 'q', 'j', 'k', 'x', 'b', 'm', 'w', 'v', 'z'],
    ],
    "azerty": [
        ['²', '&', 'é', '"', '\'', '(', '-', 'è', '_', 'ç', 'à', ')', '=', '\\'],
        ['a', 'z', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p', '^', '$'],
        ['q', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l', 'm', 'ù', '*'],
        ['<', 'w', 'x', 'c', 'v', 'b', 'n', ',', ';', ':', '!'],
    ],
}


def validate_layout(name: str, rows: list[list[str]]) -> None:
    """Reject a layout with a repeated key.

    Adjacency is keyed by character, so a character appearing in two places
    would merge both neighbourhoods and emit duplicate walks. None of the
    shipped layouts do this; this check is here so a new one cannot.
    """
    seen: dict[str, tuple[int, int]] = {}
    duplicates = []
    for i, row in enumerate(rows):
        for j, key in enumerate(row):
            if key in seen:
                duplicates.append(f"{key!r} at {seen[key]} and {(i, j)}")
            else:
                seen[key] = (i, j)
    if duplicates:
        cli.die(f"layout '{name}' has repeated keys: " + "; ".join(duplicates))


#: How many leading rows of each layout are number rows. A number row starts
#: with an extra key (` ~ or ²) that has no letter beneath it, so it sits one
#: column to the left of the letter rows: 1 is above q, not above w. Without
#: this, q and 2 are not neighbours and 1q2w3e is never generated.
NUMBER_ROWS = {
    "qwerty": 1,
    "qwertyshifted": 2,
    "qwertyshifted1": 2,
    "qwertyshifted2": 1,
    "dvorak": 1,
    "azerty": 1,
}


def build_adjacency(rows: list[list[str]], number_rows: int = 0) -> dict[str, list[str]]:
    """Precompute every key's neighbours once.

    The first ``number_rows`` rows are shifted one column left (see
    :data:`NUMBER_ROWS`). Neighbours are the up-to-eight keys around a key
    on the resulting grid, listed row by row, left to right.
    """
    grid: dict[tuple[int, int], str] = {}
    for i, row in enumerate(rows):
        shift = -1 if i < number_rows else 0
        for j, key in enumerate(row):
            grid[(i, j + shift)] = key

    adjacency: dict[str, list[str]] = {}
    for (i, column), key in grid.items():
        adjacency[key] = [
            grid[(i + di, column + dj)]
            for di in (-1, 0, 1)
            for dj in (-1, 0, 1)
            if (di or dj) and (i + di, column + dj) in grid
        ]
    return adjacency


def adjacency_for(layout: str) -> dict[str, list[str]]:
    """The adjacency table of a named layout."""
    rows = LAYOUTS[layout]
    validate_layout(layout, rows)
    return build_adjacency(rows, NUMBER_ROWS.get(layout, 0))


def continuation_counts(adjacency: dict[str, list[str]], keys: int) -> dict[str, int]:
    """For each key, how many ways there are to walk on for ``keys`` more keys."""
    counts = {key: 1 for key in adjacency}
    for _ in range(keys):
        counts = {
            key: sum(counts[n] for n in neighbours)
            for key, neighbours in adjacency.items()
        }
    return counts


def count_walks(adjacency: dict[str, list[str]], length: int) -> int:
    """Number of walks of ``length`` keys, without generating any of them."""
    if length <= 0:
        return 0
    return sum(continuation_counts(adjacency, length - 1).values())


#: Keys of each walk that are precomputed as a block. Every way of continuing
#: for this many keys is built once per starting key (a few thousand short
#: strings each) and then glued onto each prefix, so the last four levels of
#: the search cost one C-level concatenation per walk instead of four nested
#: generator hops.
TAIL_KEYS = 4


def walks(adjacency: dict[str, list[str]], length: int):
    """Yield every walk of ``length`` keys.

    Memory is the tail table (independent of ``length``) plus O(length) for
    the search, never O(output). Emission order is depth-first in neighbour
    order, exactly as a plain recursion would give.
    """
    if length <= 0:
        return
    if length == 1:
        yield from adjacency
        return
    tails = tail_table(adjacency, min(TAIL_KEYS, length - 1))
    for key in adjacency:
        yield from walks_from(adjacency, key, length, tails)


def tail_table(adjacency: dict[str, list[str]], keys: int) -> dict[str, list[str]]:
    """For each key, every continuation of ``keys`` keys after it, in walk order."""
    tails = {key: [""] for key in adjacency}
    for _ in range(keys):
        tails = {
            key: [n + rest for n in neighbours for rest in tails[n]]
            for key, neighbours in adjacency.items()
        }
    return tails


def walks_from(adjacency: dict[str, list[str]], prefix: str, length: int,
               tails: dict[str, list[str]] | None = None):
    """Yield the walks of ``length`` keys that begin with the walk ``prefix``.

    Doing this for every prefix of some fixed length, in walk order, gives
    exactly ``walks(adjacency, length)``; that is how --jobs divides the
    work. ``tails`` is the table for ``min(TAIL_KEYS, keys still to add)``,
    passed in so it is not rebuilt for each prefix.
    """
    remaining = length - len(prefix)
    if remaining < 0:
        return
    if remaining == 0:
        yield prefix
        return
    tail_keys = min(TAIL_KEYS, remaining)
    if tails is None:
        tails = tail_table(adjacency, tail_keys)

    def step(prefix: str, key: str, remaining: int):
        if remaining == 0:
            yield from map(prefix.__add__, tails[key])
            return
        for neighbour in adjacency[key]:
            yield from step(prefix + neighbour, neighbour, remaining - 1)

    yield from step(prefix, prefix[-1], remaining - tail_keys)


def split_depth(adjacency: dict[str, list[str]], length: int, jobs: int) -> int:
    """How many leading keys to fix so the walks divide into worker-sized pieces.

    Each walk of that many keys becomes one task: "generate every walk that
    starts like this". The depth is the shallowest at which the largest task
    produces a few megabytes at most and there are enough tasks to keep
    every worker busy.
    """
    target = parallel.block_bytes(parallel.TARGET_RESULT_BYTES)
    for depth in range(1, length):
        largest = max(continuation_counts(adjacency, length - depth).values())
        if largest * (length + 1) <= target and count_walks(adjacency, depth) >= 4 * jobs:
            return depth
    return length


# Per-worker state for --jobs, set once in each worker by start_worker().
_ADJACENCY: dict[str, list[str]] = {}
_LENGTH = 0
_TAILS: dict[str, list[str]] = {}
_BOUNDS: tuple[int, int | None] = (0, None)


def start_worker(layout: str, length: int, depth: int, min_length: int,
                 max_length: int | None) -> None:
    global _ADJACENCY, _LENGTH, _TAILS, _BOUNDS
    _ADJACENCY = adjacency_for(layout)
    _LENGTH = length
    _TAILS = tail_table(_ADJACENCY, min(TAIL_KEYS, length - depth))
    _BOUNDS = (min_length, max_length)


def walk_block(prefix: str) -> tuple[bytes, int, int]:
    """Worker: every walk that starts with ``prefix``."""
    return parallel.pack_filtered(
        walks_from(_ADJACENCY, prefix, _LENGTH, _TAILS), *_BOUNDS
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate keyboard walks (sequences of adjacent keys).",
        epilog=(
            "Examples:\n"
            "  keyboard-walk.py -l 4 -k qwerty -o walks4.txt\n"
            "  keyboard-walk.py -l 6 -k qwertyshifted2 --force > walks6.txt\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-l", "--length", type=int, required=True, help="Length of the walks.")
    parser.add_argument("-o", "--output", help="Output file. Defaults to stdout.")
    parser.add_argument(
        "-k", "--layout", choices=sorted(LAYOUTS), default="qwerty",
        help="Keyboard layout (default: qwerty).",
    )
    parser.add_argument(
        "--max-candidates", type=int, default=estimate.DEFAULT_MAX_CANDIDATES,
        metavar="N", help="Safety limit before --force is required "
                          f"(default {estimate.DEFAULT_MAX_CANDIDATES:,}).",
    )
    parallel.add_jobs_arg(parser)
    cli.add_common_args(parser)
    cli.add_output_args(parser)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    cli.set_quiet(args.quiet)

    if args.length < 1:
        cli.die("--length must be at least 1")

    adjacency = adjacency_for(args.layout)

    total = cli.sliced_total(count_walks(adjacency, args.length), args)
    estimate.confirm_or_exit(
        total,
        avg_length=args.length,
        force=args.force,
        max_candidates=args.max_candidates,
        label="walks",
    )

    jobs = parallel.resolve_jobs(args.jobs)
    with cli.open_output(args.output, compress=args.gzip) as out:
        if jobs > 1:
            writer = parallel.block_writer_for(out, args)
            min_length, max_length = parallel.length_bounds(args)
            depth = split_depth(adjacency, args.length, jobs)
            per_prefix = continuation_counts(adjacency, args.length - depth)
            # Every walk has the same length, so the length filter passes
            # all of them or none; when it passes, a --skip can jump whole
            # pieces without generating them, because their sizes are known.
            kept = args.length >= min_length and (
                max_length is None or args.length <= max_length)

            def prefixes():
                skipping = kept
                for prefix in walks(adjacency, depth):
                    if skipping and writer.skip_ahead(per_prefix[prefix[-1]]):
                        continue
                    skipping = False
                    yield prefix

            parallel.drain(
                parallel.ordered(
                    parallel.item_tasks(prefixes()), walk_block, jobs=jobs,
                    initializer=start_worker,
                    initargs=(args.layout, args.length, depth, min_length, max_length),
                ),
                writer,
            )
        else:
            writer = cli.writer_for(out, args)
            writer.feed(walks(adjacency, args.length))
            writer.close()

    cli.log(f"Walks: {writer.report()}"
            + (f" -> {args.output}" if args.output else ""))


if __name__ == "__main__":
    cli.run(main)
