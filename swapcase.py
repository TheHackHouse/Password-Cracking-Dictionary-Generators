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

from wordlistlib import cli  # noqa: E402

MODES = {
    "swap": str.swapcase,
    "upper": str.upper,
    "lower": str.lower,
    "title": str.title,
    "capitalize": str.capitalize,
}


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
        help="Do not drop candidates that are unchanged duplicates of each "
             "other (e.g. two inputs that upper-case to the same string).",
    )
    cli.add_common_args(parser, force=False)
    cli.add_output_args(parser)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    cli.set_quiet(args.quiet)
    transform = MODES[args.mode]

    stats = {"read": 0}

    def transformed(handle):
        seen: set[str] = set()
        for line in cli.iter_lines(handle):
            stats["read"] += 1
            candidate = transform(line)
            if not args.keep_duplicates:
                if candidate in seen:
                    continue
                seen.add(candidate)
            yield candidate

    with cli.open_input(args.input) as infile, \
            cli.open_output(args.output, compress=args.gzip) as outfile:
        writer = cli.writer_for(outfile, args)
        writer.feed(transformed(infile))
        writer.close()

    cli.log(f"Read {stats['read']:,} words with mode '{args.mode}': {writer.report()}.")


if __name__ == "__main__":
    main()
