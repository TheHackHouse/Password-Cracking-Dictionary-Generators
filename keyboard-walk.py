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

from wordlistlib import cli, estimate  # noqa: E402

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


def count_walks(adjacency: dict[str, list[str]], length: int) -> int:
    """Number of walks of ``length`` keys, without generating any of them."""
    if length <= 0:
        return 0
    counts = {key: 1 for key in adjacency}
    for _ in range(length - 1):
        counts = {
            key: sum(counts[n] for n in neighbours)
            for key, neighbours in adjacency.items()
        }
    return sum(counts.values())


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

    tail_keys = min(TAIL_KEYS, length - 1)
    # tails[key]: every continuation of tail_keys keys after ``key``.
    tails = {key: [""] for key in adjacency}
    for _ in range(tail_keys):
        tails = {
            key: [n + rest for n in neighbours for rest in tails[n]]
            for key, neighbours in adjacency.items()
        }

    def step(prefix: str, key: str, remaining: int):
        if remaining == 0:
            yield from map(prefix.__add__, tails[key])
            return
        for neighbour in adjacency[key]:
            yield from step(prefix + neighbour, neighbour, remaining - 1)

    for key in adjacency:
        yield from step(key, key, length - 1 - tail_keys)


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

    with cli.open_output(args.output, compress=args.gzip) as out:
        writer = cli.writer_for(out, args)
        writer.feed(walks(adjacency, args.length))
        writer.close()

    cli.log(f"Walks: {writer.report()}"
            + (f" -> {args.output}" if args.output else ""))


if __name__ == "__main__":
    cli.run(main)
