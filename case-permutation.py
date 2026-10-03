#!/usr/bin/env python3
"""Generate case permutations of a word, or of every word in a file.

Every distinct combination of upper and lower case is produced. Characters
with no case (digits, symbols) are left alone instead of being expanded into
two identical branches, so the output contains no duplicate lines.

Growth is 2^n in the number of cased characters, so for anything longer than a
dozen or so characters use --max-upper (cap how many letters are uppercased at
once) or --common (just the four or five forms people actually type).
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

from wordlistlib import caseperm, cli, estimate  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate case permutations for words.",
        epilog=(
            "Examples:\n"
            "  case-permutation.py -w megacorp -o perms.txt\n"
            "  case-permutation.py -w megacorp --max-upper 2\n"
            "  cat words.txt | case-permutation.py --common > cased.txt\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument("-w", "--word", help="A single input word.")
    source.add_argument(
        "-i", "--input", "-f", "--file", dest="input",
        help="File of words, one per line. Defaults to stdin when -w is not given.",
    )
    parser.add_argument(
        "-o", "--output",
        help="Output file. Defaults to stdout.",
    )
    parser.add_argument(
        "-m", "--max-upper", type=int, metavar="N",
        help="Uppercase at most N characters per candidate. Turns 2^n growth "
             "into something manageable for long inputs.",
    )
    parser.add_argument(
        "--common", action="store_true",
        help="Skip the full permutation and emit only lower, UPPER, Capitalised, "
             "swapped and Title case.",
    )
    parser.add_argument(
        "--max-candidates", type=int, default=estimate.DEFAULT_MAX_CANDIDATES,
        metavar="N", help="Safety limit before --force is required "
                          f"(default {estimate.DEFAULT_MAX_CANDIDATES:,}).",
    )
    cli.add_common_args(parser)
    return parser


def read_words(args) -> list[str]:
    if args.word:
        return [args.word]
    if args.input is None and sys.stdin.isatty():
        try:
            word = input("Please enter the word: ").strip()
        except EOFError:
            word = ""
        if not word:
            cli.die("no input provided")
        return [word]
    with cli.open_input(args.input) as handle:
        words = list(cli.iter_lines(handle))
    if not words:
        cli.die("input contained no words")
    return words


def main() -> None:
    args = build_parser().parse_args()
    cli.set_quiet(args.quiet)

    if args.max_upper is not None and args.max_upper < 0:
        cli.die("--max-upper cannot be negative")
    if args.common and args.max_upper is not None:
        cli.die("--common and --max-upper are mutually exclusive")

    words = read_words(args)

    if args.common:
        total = sum(len(caseperm.common_forms(w)) for w in words)
    else:
        total = sum(caseperm.count_permutations(w, args.max_upper) for w in words)
    avg_length = sum(len(w) for w in words) / len(words)

    estimate.confirm_or_exit(
        total,
        avg_length=avg_length,
        force=args.force,
        max_candidates=args.max_candidates,
        label="permutations",
    )

    written = 0
    with cli.open_output(args.output) as out:
        for word in words:
            produce = (
                caseperm.common_forms(word)
                if args.common
                else caseperm.permutations(word, args.max_upper)
            )
            for candidate in produce:
                out.write(candidate + "\n")
                written += 1

    if args.output:
        cli.log(f"Wrote {written:,} permutations to {args.output}")


if __name__ == "__main__":
    main()
