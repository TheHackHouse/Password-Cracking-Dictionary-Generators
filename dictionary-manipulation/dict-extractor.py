#!/usr/bin/env python3
"""Split strings into their component dictionary words plus the leftovers.

Feed it cracked passwords and it decomposes 'summerbreeze2026' into the words
'summer' and 'breeze' with '2026' left over. The words make a targeted base
dictionary and the leftovers make good rule material for the next round.

The matcher finds the split that covers as much of the string as possible
with dictionary words, using as few (so as long) words as it can. Characters
no word accounts for -- digits, symbols, unknown fragments -- are stepped over
and reported as leftovers; they do not stop the words around them from being
found.
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


def word_starts(vocabulary: set[str], min_length: int) -> frozenset[str]:
    """The first ``min_length`` characters of every usable vocabulary word.

    A position whose next ``min_length`` characters are not in this set
    cannot begin a word, which lets the matcher skip almost every position
    in a typical password without trying a single substring there.
    """
    min_length = max(1, min_length)
    return frozenset(word[:min_length] for word in vocabulary if len(word) >= min_length)


def split_into_words(
    text: str, vocabulary: set[str], min_length: int, max_length: int | None = None,
    starts: frozenset[str] | None = None,
) -> list[tuple[int, int]]:
    """Return the ``(start, end)`` spans of the dictionary words in ``text``.

    The spans do not overlap and are in order. They are the choice that
    covers the most characters; among equals, the one with the fewest words,
    then the one whose earlier words are longer. An empty list means no
    dictionary word was found.

    ``max_length`` (the longest word in the vocabulary) and ``starts`` (from
    :func:`word_starts`) are optional and only make it faster: the first
    bounds the work per character, the second skips positions where no word
    can begin. The result is the same with or without them.

    Offsets are returned rather than the words themselves so the caller can
    remove exactly the matched spans; removing by text would strip the wrong
    occurrence when a word repeats.
    """
    size = len(text)
    # Lowercasing can change a string's length for a few characters, which
    # would make the offsets point at the wrong place; match as-is then.
    lowered = text.lower()
    if len(lowered) != size:
        lowered = text
    longest = size if max_length is None else min(max_length, size)
    min_length = max(1, min_length)

    # Worked backwards and iteratively (a line can be thousands of characters
    # long, far past the recursion limit). covered[i] / words[i] describe the
    # best split of text[i:]; step[i] is where its first word ends, or 0 when
    # the character at i is not part of any word.
    covered = [0] * (size + 1)
    words = [0] * (size + 1)
    step = [0] * (size + 1)
    for start in range(size - 1, -1, -1):
        best_covered, best_words, best_end = covered[start + 1], words[start + 1], 0
        if starts is not None and lowered[start:start + min_length] not in starts:
            covered[start], words[start] = best_covered, best_words
            continue
        for end in range(min(size, start + longest), start + min_length - 1, -1):
            if lowered[start:end] in vocabulary:
                total = end - start + covered[end]
                count = 1 + words[end]
                if total > best_covered or (total == best_covered and count < best_words):
                    best_covered, best_words, best_end = total, count, end
        covered[start], words[start], step[start] = best_covered, best_words, best_end

    spans = []
    position = 0
    while position < size:
        end = step[position]
        if end:
            spans.append((position, end))
            position = end
        else:
            position += 1
    return spans


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
    longest_word = max(map(len, vocabulary))
    starts = word_starts(vocabulary, args.min_word_length)

    lines = split_count = word_count = remainder_count = 0
    try:
        known_file = cli.create_text_file(args.known_out)
        remaining_file = cli.create_text_file(args.remaining_out)
    except OSError as exc:
        cli.die(f"cannot open output file: {exc}")

    try:
        with cli.open_input(args.input) as infile:
            for line in cli.iter_lines(infile):
                lines += 1
                spans = split_into_words(
                    line, vocabulary, args.min_word_length, longest_word, starts
                )
                if not spans:
                    remaining_file.write(line + "\n")
                    remainder_count += 1
                    continue

                split_count += 1
                # Each stretch between words is its own leftover, so
                # 'acme2026summer!' leaves '2026' and '!', not '2026!'.
                position = 0
                for start, end in [*spans, (len(line), len(line))]:
                    if start > position:
                        remaining_file.write(line[position:start] + "\n")
                        remainder_count += 1
                    if end > start:
                        known_file.write(line[start:end] + "\n")
                        word_count += 1
                    position = end
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
    cli.run(main)
