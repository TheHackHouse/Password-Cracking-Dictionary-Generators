#!/usr/bin/env python3
"""Filter a wordlist by string length.

Replaces short-strings.py, whose 3-character cut-off was hardcoded in four
places. Trailing whitespace is stripped (it used to survive into the output
because the length test and the write disagreed) and blank lines are dropped.
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

from wordlistlib import cli  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Keep only the lines whose length is within a range.",
        epilog=(
            "Examples:\n"
            "  filter-by-length.py -i words.txt --max-length 3 -o short.txt\n"
            "  filter-by-length.py -i words.txt --min-length 8 > long.txt\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-i", "--input", help="Input file. Defaults to stdin.")
    parser.add_argument("-o", "--output", help="Output file. Defaults to stdout.")
    parser.add_argument(
        "--min-length", type=int, default=1, metavar="N",
        help="Shortest length to keep (default: 1).",
    )
    parser.add_argument(
        "--max-length", type=int, default=None, metavar="N",
        help="Longest length to keep (default: no limit).",
    )
    parser.add_argument(
        "--sort", action="store_true",
        help="Sort and deduplicate the output. Requires -o.",
    )
    cli.add_common_args(parser, force=False)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    cli.set_quiet(args.quiet)

    if args.min_length < 0:
        cli.die("--min-length cannot be negative")
    if args.max_length is not None and args.max_length < args.min_length:
        cli.die("--max-length cannot be smaller than --min-length")
    if args.sort and not args.output:
        cli.die("--sort needs -o/--output (it rewrites the file in place)")

    read = kept = 0
    with cli.open_input(args.input) as infile, cli.open_output(args.output) as outfile:
        for line in cli.iter_lines(infile):
            read += 1
            if len(line) < args.min_length:
                continue
            if args.max_length is not None and len(line) > args.max_length:
                continue
            outfile.write(line + "\n")
            kept += 1

    if args.sort:
        cli.sort_unique_file(args.output)

    bounds = f">= {args.min_length}"
    if args.max_length is not None:
        bounds += f" and <= {args.max_length}"
    cli.log(f"Read {read:,} lines, kept {kept:,} with length {bounds}.")


if __name__ == "__main__":
    main()
