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

from wordlistlib import cli  # noqa: E402


def load_english_words(custom_dict: str | None) -> set[str]:
    """Load the reference vocabulary, lowercased."""
    if custom_dict:
        with cli.open_input(custom_dict) as handle:
            vocabulary = {word.lower() for word in cli.iter_lines(handle)}
        if not vocabulary:
            cli.die(f"{custom_dict} contained no words")
        cli.log(f"Loaded {len(vocabulary):,} words from {custom_dict}")
        return vocabulary

    try:
        import nltk
    except ImportError:
        cli.die(
            "nltk is not installed. Either `pip install nltk` or pass "
            "--custom-dict with your own word list."
        )

    # Only hit the network when the corpus is genuinely missing; the previous
    # version re-downloaded on every single run.
    try:
        nltk.data.find("corpora/words")
    except LookupError:
        cli.log("Downloading the NLTK 'words' corpus (one time)...")
        nltk.download("words", quiet=True)

    from nltk.corpus import words as nltk_words

    vocabulary = {word.lower() for word in nltk_words.words()}
    cli.log(f"Loaded {len(vocabulary):,} words from the NLTK corpus")
    return vocabulary


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
        help="Reference word list to compare against, instead of the NLTK corpus.",
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

    vocabulary = load_english_words(args.custom_dict)

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
