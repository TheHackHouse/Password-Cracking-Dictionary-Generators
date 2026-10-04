#!/usr/bin/env python3
"""Combine words into candidate passwords.

Two modes:

  -i cat,dog,bird      every ordering of the given words, in any subset size
                       allowed by --min-words/--max-words
  -d a.txt -d b.txt    one word from each dictionary, in the order given

Any number of dictionaries can be supplied by repeating -d. The first one is
streamed from disk rather than loaded, so the memory cost is set by the
smaller lists rather than the largest.
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

from wordlistlib import cli, estimate  # noqa: E402


def survey_file(path: str) -> tuple[int, float]:
    """Return the distinct word count and mean word length of a dictionary.

    Counting up front is what lets the tool report the real candidate total
    before writing anything; only the words of one file are held at a time.
    """
    seen: set[str] = set()
    with cli.open_input(path) as handle:
        for word in cli.iter_lines(handle):
            seen.add(word)
    if not seen:
        return 0, 0.0
    return len(seen), sum(len(w) for w in seen) / len(seen)


def stream_file_words(path: str):
    """Yield each distinct word from a file without holding the file in memory."""
    seen: set[str] = set()
    with cli.open_input(path) as handle:
        for word in cli.iter_lines(handle):
            if word in seen:
                continue
            seen.add(word)
            yield word


def dictionary_combinations(paths: list[str]):
    """Cartesian product across dictionaries, streaming the first one."""
    rest = [cli.load_wordlist(p) for p in paths[1:]]
    for first in stream_file_words(paths[0]):
        if rest:
            for tail in itertools.product(*rest):
                yield (first,) + tail
        else:
            yield (first,)


def word_combinations(words: list[str], min_words: int, max_words: int):
    for size in range(min_words, max_words + 1):
        yield from itertools.permutations(words, size)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a wordlist by combining words or dictionaries.",
        epilog=(
            "Examples:\n"
            "  multiple-words-joiner.py -i 'mega,corp,2026' --min-words 2 -d- > list.txt\n"
            "  multiple-words-joiner.py -d names.txt -d years.txt -D '-' -a '!' -o list.txt\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-i", "--input",
        help="Comma separated list of words, e.g. 'cat,bird,dog'.",
    )
    parser.add_argument(
        "-d", "--dict", action="append", dest="dicts", metavar="FILE",
        help="Dictionary file, one word per line. Repeat for each dictionary.",
    )
    parser.add_argument("-o", "--output", help="Output file. Defaults to stdout.")
    parser.add_argument(
        "-D", "--delimiter", default="",
        help="String placed between words (default: none).",
    )
    parser.add_argument(
        "-p", "--prepend", default="",
        help="Static string placed at the start of each candidate. It is "
             "separated from the first word by --delimiter; use "
             "--no-affix-delimiter to butt it straight up against the word.",
    )
    parser.add_argument(
        "-a", "--append", default="",
        help="Static string placed at the end of each candidate, separated "
             "from the last word by --delimiter.",
    )
    parser.add_argument(
        "--no-affix-delimiter", action="store_true",
        help="Concatenate --prepend and --append directly, with no delimiter "
             "between them and the words.",
    )
    parser.add_argument(
        "--min-words", type=int, default=None, metavar="N",
        help="With -i, the fewest words per candidate (default: all of them).",
    )
    parser.add_argument(
        "--max-words", type=int, default=None, metavar="N",
        help="With -i, the most words per candidate (default: all of them).",
    )
    parser.add_argument(
        "--max-candidates", type=int, default=estimate.DEFAULT_MAX_CANDIDATES,
        metavar="N", help="Safety limit before --force is required "
                          f"(default {estimate.DEFAULT_MAX_CANDIDATES:,}).",
    )
    cli.add_common_args(parser)
    cli.add_output_args(parser)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    cli.set_quiet(args.quiet)

    if args.dicts and args.input:
        cli.die("use either -i or -d, not both")

    if args.dicts:
        surveys = [survey_file(p) for p in args.dicts]
        total = 1
        avg_length = 0.0
        for path, (size, mean_len) in zip(args.dicts, surveys, strict=True):
            if size == 0:
                cli.die(f"{path} contains no usable words")
            cli.log(f"{path}: {size:,} distinct words")
            total *= size
            avg_length += mean_len
        avg_length += len(args.delimiter) * (len(args.dicts) - 1)
        combinations = dictionary_combinations(args.dicts)
    elif args.input:
        words = list(dict.fromkeys(w for w in args.input.split(",") if w))
        if not words:
            cli.die("-i did not contain any words")
        max_words = args.max_words or len(words)
        min_words = args.min_words or (1 if args.max_words else len(words))
        if not 1 <= min_words <= max_words <= len(words):
            cli.die(
                f"need 1 <= --min-words <= --max-words <= {len(words)} "
                f"(got min={min_words}, max={max_words})"
            )
        total = sum(
            len(list(itertools.permutations(words, size)))
            for size in range(min_words, max_words + 1)
        )
        mean_word = sum(len(w) for w in words) / len(words)
        mean_count = (min_words + max_words) / 2
        avg_length = mean_word * mean_count + len(args.delimiter) * (mean_count - 1)
        combinations = word_combinations(words, min_words, max_words)
    else:
        cli.die("provide either -i/--input or at least one -d/--dict")

    affix = len(args.prepend) + len(args.append)
    if not args.no_affix_delimiter:
        affix += len(args.delimiter) * bool(args.prepend)
        affix += len(args.delimiter) * bool(args.append)
    total = cli.sliced_total(total, args)
    estimate.confirm_or_exit(
        total,
        avg_length=avg_length + affix,
        force=args.force,
        max_candidates=args.max_candidates,
        label="combinations",
    )

    def rendered():
        delimiter, prepend, append = args.delimiter, args.prepend, args.append
        plain = args.no_affix_delimiter
        for combo in combinations:
            parts = list(combo)
            if plain:
                yield prepend + delimiter.join(parts) + append
            else:
                # The affixes join like any other word, so `-p corp -D -`
                # gives corp-mega-2025 rather than corpmega-2025.
                if prepend:
                    parts.insert(0, prepend)
                if append:
                    parts.append(append)
                yield delimiter.join(parts)

    with cli.open_output(args.output, compress=args.gzip) as out:
        writer = cli.writer_for(out, args)
        writer.feed(rendered())
        writer.close()

    cli.log(f"Combinations: {writer.report()}"
            + (f" -> {args.output}" if args.output else ""))


if __name__ == "__main__":
    main()
