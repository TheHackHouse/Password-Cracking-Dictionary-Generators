#!/usr/bin/env python3
"""Separate the dictionary words in a list from the ones that are not.

Point it at a set of cracked passwords and it tells you which are plain
dictionary words and which are not; the leftovers are usually the interesting
ones (names, site codes, product names) and make a good targeted dictionary.

The NLTK 'words' corpus is the fallback, but it is archaic and has no names,
brands or plurals, so --custom-dict with a corpus of real cracked passwords
gives noticeably better results.
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Split a list into dictionary words and non-dictionary words.",
        epilog=(
            "Examples:\n"
            "  dict-compare.py -i cracked.txt -o not-words.txt\n"
            "  dict-compare.py -i cracked.txt --invert --custom-dict english.txt\n"
            "  dict-compare.py -i cracked.txt --split-words > tokens.txt\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-i", "--input", help="Input file. Defaults to stdin.")
    parser.add_argument("-o", "--output", help="Output file. Defaults to stdout.")
    parser.add_argument(
        "--custom-dict", "--custom_dict", dest="custom_dict",
        help="Reference word list to compare against. Without it the NLTK corpus is used, falling back to the system word list.",
    )
    parser.add_argument(
        "--invert", action="store_true",
        help="Emit the words that ARE in the dictionary rather than the ones that are not.",
    )
    parser.add_argument(
        "--split-words", action="store_true",
        help="Treat each whitespace-separated token as a word. By default a "
             "whole line is one word, which is what you want for a password list.",
    )
    cli.add_common_args(parser, force=False)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    cli.set_quiet(args.quiet)

    vocabulary = vocab.load(args.custom_dict)

    checked = matched = 0
    with cli.open_input(args.input) as infile, cli.open_output(args.output) as outfile:
        for line in cli.iter_lines(infile):
            tokens = line.split() if args.split_words else [line]
            for token in tokens:
                checked += 1
                is_word = token.lower() in vocabulary
                if is_word:
                    matched += 1
                if is_word == args.invert:
                    outfile.write(token + "\n")

    wanted = "dictionary words" if args.invert else "non-dictionary words"
    cli.log(
        f"Checked {checked:,} entries: {matched:,} in the dictionary, "
        f"{checked - matched:,} not. Wrote the {wanted}."
    )


if __name__ == "__main__":
    main()
