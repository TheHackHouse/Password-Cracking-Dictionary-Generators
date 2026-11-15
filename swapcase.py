#!/usr/bin/env python3
"""Apply a single case transformation to every word in a list.

The default --mode swap inverts the case of each character, simulating someone
who left caps lock on and still used shift. The other modes cover the handful
of forms that show up constantly in cracked password sets.

For every combination of upper and lower case rather than one transformation,
use case-permutation.py.
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

from wordlistlib import cli, parallel  # noqa: E402

MODES = {
    "swap": str.swapcase,
    "upper": str.upper,
    "lower": str.lower,
    "title": str.title,
    "capitalize": str.capitalize,
}

# Per-worker state for --jobs, set once in each worker by start_worker().
_TRANSFORM = str.swapcase
_BOUNDS: tuple[int, int | None] = (0, None)


def start_worker(mode: str, min_length: int, max_length: int | None) -> None:
    global _TRANSFORM, _BOUNDS
    _TRANSFORM = MODES[mode]
    _BOUNDS = (min_length, max_length)


def transform_block(text: str) -> tuple[bytes, int, int]:
    """Worker: one block of words, transformed and length-filtered."""
    return parallel.pack_filtered(map(_TRANSFORM, parallel.lines(text)), *_BOUNDS)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Swap or normalise the case of each word in a list.",
        epilog=(
            "Examples:\n"
            "  swapcase.py -i dictionary.txt -o swapped.txt\n"
            "  cat dictionary.txt | swapcase.py --mode title > titled.txt\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-i", "--input",
        help="Input file, one word per line. Defaults to stdin.",
    )
    parser.add_argument(
        "-o", "--output",
        help="Output file. Defaults to stdout.",
    )
    parser.add_argument(
        "-m", "--mode", choices=sorted(MODES), default="swap",
        help="Transformation to apply (default: swap).",
    )
    parser.add_argument(
        "--keep-duplicates", action="store_true",
        help="Do not drop candidates that are duplicates of each other (e.g. "
             "two inputs that upper-case to the same string). Dropping them "
             "means remembering every distinct output, so use this for lists "
             "larger than memory and run sort -u afterwards.",
    )
    parallel.add_jobs_arg(parser)
    cli.add_common_args(parser, force=False)
    cli.add_output_args(parser)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    cli.set_quiet(args.quiet)
    transform = MODES[args.mode]

    duplicates = 0

    def distinct(candidates):
        nonlocal duplicates
        seen: set[str] = set()
        add = seen.add
        for candidate in candidates:
            if candidate in seen:
                duplicates += 1
            else:
                add(candidate)
                yield candidate

    jobs = parallel.effective_jobs(
        args.jobs,
        None if args.keep_duplicates else
        "dropping duplicates needs one process to see every word; add "
        "--keep-duplicates and run sort -u on the result",
    )

    if jobs > 1:
        with cli.open_output(args.output, compress=args.gzip) as outfile:
            writer = parallel.block_writer_for(outfile, args)
            parallel.drain(
                parallel.ordered(
                    parallel.input_tasks(args.input), transform_block, jobs=jobs,
                    initializer=start_worker,
                    initargs=(args.mode, *parallel.length_bounds(args)),
                ),
                writer,
            )
    else:
        with cli.open_input(args.input) as infile, \
                cli.open_output(args.output, compress=args.gzip) as outfile:
            # map() keeps the transform itself out of the Python loop. With
            # --keep-duplicates nothing is remembered, so the whole run is
            # streaming and the input can be any size.
            candidates = map(transform, cli.iter_lines(infile))
            if not args.keep_duplicates:
                candidates = distinct(candidates)
            writer = cli.writer_for(outfile, args)
            writer.feed(candidates)
            writer.close()

    read = writer.written + writer.filtered + writer.skipped + duplicates
    cli.log(f"Read {read:,} words with mode '{args.mode}': {writer.report()}"
            + (f", {duplicates:,} duplicates dropped" if duplicates else "") + ".")


if __name__ == "__main__":
    cli.run(main)
