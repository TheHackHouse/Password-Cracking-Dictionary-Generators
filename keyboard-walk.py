#!/usr/bin/env python3
"""Generate keyboard walks -- sequences of adjacent keys such as 1q2w3e.

The candidate count is worked out before anything is generated, so the
confirmation prompt is useful rather than decorative, and walks are streamed to
the output instead of being collected in a list. Growth is roughly 6.6x per
extra character on qwerty: length 6 is ~515k walks, length 8 is ~22M.
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


def build_adjacency(rows: list[list[str]]) -> dict[str, list[str]]:
    """Precompute every key's neighbours once.

    The previous implementation rescanned the whole layout on every step of
    the recursion, which dominated the runtime at longer lengths.
    """
    adjacency: dict[str, list[str]] = {}
    for i, row in enumerate(rows):
        for j, key in enumerate(row):
            neighbours = []
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    if di == 0 and dj == 0:
                        continue
                    ni, nj = i + di, j + dj
                    if 0 <= ni < len(rows) and 0 <= nj < len(rows[ni]):
                        neighbours.append(rows[ni][nj])
            adjacency[key] = neighbours
    return adjacency


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


def walks(adjacency: dict[str, list[str]], length: int):
    """Yield every walk of ``length`` keys. Memory is O(length), not O(output)."""
    if length <= 0:
        return
    acc: list[str] = []

    def step(key: str, remaining: int):
        acc.append(key)
        if remaining == 0:
            yield "".join(acc)
        else:
            for neighbour in adjacency[key]:
                yield from step(neighbour, remaining - 1)
        acc.pop()

    for key in adjacency:
        yield from step(key, length - 1)


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
    return parser


def main() -> None:
    args = build_parser().parse_args()
    cli.set_quiet(args.quiet)

    if args.length < 1:
        cli.die("--length must be at least 1")

    rows = LAYOUTS[args.layout]
    validate_layout(args.layout, rows)
    adjacency = build_adjacency(rows)

    total = count_walks(adjacency, args.length)
    estimate.confirm_or_exit(
        total,
        avg_length=args.length,
        force=args.force,
        max_candidates=args.max_candidates,
        label="walks",
    )

    written = 0
    with cli.open_output(args.output) as out:
        for walk in walks(adjacency, args.length):
            out.write(walk + "\n")
            written += 1

    if args.output:
        cli.log(f"Wrote {written:,} walks to {args.output}")


if __name__ == "__main__":
    main()
