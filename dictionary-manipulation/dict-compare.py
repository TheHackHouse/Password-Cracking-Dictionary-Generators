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
import itertools
import sys
from pathlib import Path

_here = Path(__file__).resolve().parent
for _candidate in (_here, _here.parent):
    if (_candidate / "wordlistlib").is_dir():
        sys.path.insert(0, str(_candidate))
        break

from wordlistlib import cli, parallel, vocab  # noqa: E402

# Per-worker state for --jobs, set once in each worker by start_worker().
_VOCABULARY: frozenset[str] | set[str] = frozenset()
_INVERT = False
_SPLIT_WORDS = False


def start_worker(vocabulary, invert: bool, split_words: bool) -> None:
    global _VOCABULARY, _INVERT, _SPLIT_WORDS
    _VOCABULARY, _INVERT, _SPLIT_WORDS = vocabulary, invert, split_words


def compare_block(text: str) -> tuple[bytes, int, int, int, int]:
    """Worker: ``(output, written, 0, checked, matched)`` for one block."""
    # Splitting the whole block on whitespace gives the same tokens as
    # splitting each line, since a line break is whitespace too.
    tokens = text.split() if _SPLIT_WORDS else parallel.lines(text)
    wanted = [t for t in tokens if (t.lower() in _VOCABULARY) == _INVERT]
    matched = len(wanted) if _INVERT else len(tokens) - len(wanted)
    return parallel.pack(wanted), len(wanted), 0, len(tokens), matched


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
    parallel.add_jobs_arg(parser)
    cli.add_common_args(parser, force=False)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    cli.set_quiet(args.quiet)

    vocabulary = vocab.load(args.custom_dict)

    jobs = parallel.resolve_jobs(args.jobs)
    if jobs > 1:
        checked, matched = parallel_compare(args, vocabulary, jobs)
    else:
        checked, matched = serial_compare(args, vocabulary)

    wanted = "dictionary words" if args.invert else "non-dictionary words"
    cli.log(
        f"Checked {checked:,} entries: {matched:,} in the dictionary, "
        f"{checked - matched:,} not. Wrote the {wanted}."
    )


def parallel_compare(args, vocabulary, jobs: int) -> tuple[int, int]:
    totals = [0, 0]                       # checked, matched
    with cli.open_output(args.output) as outfile:
        parallel.drain(
            parallel.ordered(
                parallel.input_tasks(args.input), compare_block, jobs=jobs,
                initializer=start_worker,
                initargs=(vocabulary, args.invert, args.split_words),
            ),
            parallel.BlockWriter(outfile),
            totals,
        )
    return totals[0], totals[1]


def serial_compare(args, vocabulary) -> tuple[int, int]:
    checked = matched = 0
    invert = args.invert
    with cli.open_input(args.input) as infile, cli.open_output(args.output) as outfile:
        if args.split_words:
            tokens = itertools.chain.from_iterable(map(str.split, infile))
        else:
            tokens = cli.iter_lines(infile)
        # Tested and written a block at a time: one comprehension and one
        # write per few thousand entries instead of a loop turn per entry.
        while True:
            batch = list(itertools.islice(tokens, cli.DEFAULT_CHUNK_SIZE))
            if not batch:
                break
            wanted_tokens = [t for t in batch if (t.lower() in vocabulary) == invert]
            checked += len(batch)
            matched += len(wanted_tokens) if invert else len(batch) - len(wanted_tokens)
            if wanted_tokens:
                outfile.write("\n".join(wanted_tokens))
                outfile.write("\n")
    return checked, matched


if __name__ == "__main__":
    cli.run(main)
