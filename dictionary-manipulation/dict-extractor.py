#!/usr/bin/env python3
"""Split strings into their component dictionary words plus the leftovers.

Feed it cracked passwords and it decomposes 'summerbreeze2026' into the words
'summer' and 'breeze' with '2026' left over. The words make a targeted base
dictionary and the leftovers make good rule material for the next round.

The matcher takes the longest word first but backtracks to shorter candidates
when the remainder cannot be split. The previous version gave up on the first
dead end -- and memoised the failure -- so a string like 'passwordsy' was
discarded whole rather than split into 'password' + 'sy'.
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

from wordlistlib import cli, vocab  # noqa: E402


def split_into_words(
    text: str, vocabulary: set[str], min_length: int
) -> list[tuple[int, int]] | None:
    """Return ``[(start, end), ...]`` covering ``text`` with dictionary words.

    Offsets are returned rather than the words themselves so the caller can
    remove exactly the matched spans; removing by text would strip the wrong
    occurrence when a word repeats.
    """
    memo: dict[int, list[tuple[int, int]] | None] = {}
    lowered = text.lower()

    def search(start: int) -> list[tuple[int, int]] | None:
        if start == len(text):
            return []
        if start in memo:
            return memo[start]

        memo[start] = None  # guards against re-entry on pathological input
        # Longest candidate first, but keep trying shorter ones on failure.
        for end in range(len(text), start + min_length - 1, -1):
            if lowered[start:end] in vocabulary:
                remainder = search(end)
                if remainder is not None:
                    memo[start] = [(start, end)] + remainder
                    return memo[start]
        memo[start] = None
        return None

    return search(0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Split strings into known dictionary words and leftovers.",
        epilog=(
            "Examples:\n"
            "  dict-extractor.py -i cracked.txt --known-out words.txt --remaining-out rest.txt\n"
            "  dict-extractor.py -i cracked.txt --custom-dict english.txt --min-word-length 5\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-i", "--input", help="Input file. Defaults to stdin.")
    parser.add_argument(
        "--known-out", default="known_words.txt",
        help="File for the extracted dictionary words (default: known_words.txt).",
    )
    parser.add_argument(
        "--remaining-out", default="remaining_text.txt",
        help="File for everything left over (default: remaining_text.txt).",
    )
    parser.add_argument(
        "--custom-dict", "--custom_dict", dest="custom_dict",
        help="Reference word list. Without it the NLTK corpus is used, falling back to the system word list.",
    )
    parser.add_argument(
        "--min-word-length", type=int, default=4, metavar="N",
        help="Shortest substring treated as a word (default: 4). Lower values "
             "match far more aggressively and produce noisier output.",
    )
    parser.add_argument(
        "--no-sort", action="store_true",
        help="Leave output in input order instead of sorting and deduplicating.",
    )
    cli.add_common_args(parser, force=False)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    cli.set_quiet(args.quiet)

    if args.min_word_length < 1:
        cli.die("--min-word-length must be at least 1")
    if args.known_out == args.remaining_out:
        cli.die("--known-out and --remaining-out must be different files")

    vocabulary = vocab.load(args.custom_dict)

    lines = split_count = word_count = remainder_count = 0
    try:
        known_file = open(args.known_out, "w", encoding="utf-8", newline="\n")
        remaining_file = open(args.remaining_out, "w", encoding="utf-8", newline="\n")
    except OSError as exc:
        cli.die(f"cannot open output file: {exc}")

    try:
        with cli.open_input(args.input) as infile:
            for line in cli.iter_lines(infile):
                lines += 1
                spans = split_into_words(line, vocabulary, args.min_word_length)
                if not spans:
                    remaining_file.write(line + "\n")
                    remainder_count += 1
                    continue

                split_count += 1
                covered = bytearray(len(line))
                for start, end in spans:
                    known_file.write(line[start:end] + "\n")
                    word_count += 1
                    for i in range(start, end):
                        covered[i] = 1
                leftover = "".join(c for i, c in enumerate(line) if not covered[i])
                if leftover:
                    remaining_file.write(leftover + "\n")
                    remainder_count += 1
    finally:
        known_file.close()
        remaining_file.close()

    if not args.no_sort:
        cli.sort_unique_file(args.known_out)
        cli.sort_unique_file(args.remaining_out)

    cli.log(
        f"Read {lines:,} lines: {split_count:,} were split into {word_count:,} words "
        f"({args.known_out}); {remainder_count:,} leftovers ({args.remaining_out})."
    )


if __name__ == "__main__":
    main()
