#!/usr/bin/env python3
"""Combine words into candidate passwords.

Two modes:

  -i cat,dog,bird      every ordering of the given words, in any subset size
                       allowed by --min-words/--max-words
  -d a.txt -d b.txt    one word from each dictionary, in the order given

Any number of dictionaries can be supplied by repeating -d. The first one is
streamed from disk and never held in memory, so put the big list first: the
memory cost is then set by the smaller lists, and the first can be any size.
"""

from __future__ import annotations

import argparse
import itertools
import sys
from math import perm
from pathlib import Path

_here = Path(__file__).resolve().parent
for _candidate in (_here, _here.parent):
    if (_candidate / "wordlistlib").is_dir():
        sys.path.insert(0, str(_candidate))
        break

from wordlistlib import cli, estimate, parallel  # noqa: E402

#: Most ready-made endings kept in memory. The trailing dictionaries are
#: multiplied out once into a block of endings, as many dictionaries as fit
#: under this, and the block is glued onto each leading word.
TAIL_LIMIT = 1 << 20


def survey_stream(path: str) -> tuple[int, float]:
    """Count the words in the streamed (first) dictionary and their mean length.

    One sequential pass that keeps nothing, so it works on a file of any
    size. Duplicates are *not* removed -- that would mean holding every word
    -- so a first dictionary with repeated lines produces repeated
    candidates. Run it through ``sort -u`` first if that matters.
    """
    count = total = 0
    with cli.open_input(path) as handle:
        words = cli.iter_lines(handle)
        while True:
            block = list(itertools.islice(words, cli.DEFAULT_CHUNK_SIZE))
            if not block:
                break
            count += len(block)
            total += sum(map(len, block))
    return count, (total / count if count else 0.0)


def build_tails(rest: list[list[str]], delimiter: str,
                trail: str) -> tuple[list[list[str]], list[str]]:
    """Split ``rest`` into ``(middle dictionaries, ready-made endings)``.

    The last few dictionaries are multiplied out once into a list of
    endings, so the innermost loop is a single concatenation.
    """
    # Take dictionaries off the end while their product stays small enough.
    # The last one always qualifies: it is in memory already.
    split = len(rest)
    size = 1
    while split > 0 and (split == len(rest)
                         or size * len(rest[split - 1]) <= TAIL_LIMIT):
        size *= len(rest[split - 1])
        split -= 1
    middle, tail_lists = rest[:split], rest[split:]

    if tail_lists:
        tails = [
            delimiter + delimiter.join(combo) + trail
            for combo in itertools.product(*tail_lists)
        ]
    else:
        tails = [trail]
    return middle, tails


def combine(first_words, middle: list[list[str]], tails: list[str],
            lead: str, delimiter: str):
    """Yield every candidate that starts with one of ``first_words``."""
    for first in first_words:
        if middle:
            for combo in itertools.product(*middle):
                head = lead + first + delimiter + delimiter.join(combo)
                yield from map(head.__add__, tails)
        else:
            yield from map((lead + first).__add__, tails)


def dictionary_candidates(paths: list[str], rest: list[list[str]],
                          lead: str, delimiter: str, trail: str):
    """Yield ``lead + word1 + delimiter + word2 ... + trail`` for every combination.

    ``rest`` holds the dictionaries after the first, already loaded. The
    first is read line by line.
    """
    middle, tails = build_tails(rest, delimiter, trail)
    with cli.open_input(paths[0]) as handle:
        yield from combine(cli.iter_lines(handle), middle, tails, lead, delimiter)


# Per-worker state for --jobs, set once in each worker by start_worker().
_COMBINE: tuple = ()
_BOUNDS: tuple[int, int | None] = (0, None)


def start_worker(rest, lead, delimiter, trail, min_length, max_length) -> None:
    global _COMBINE, _BOUNDS
    middle, tails = build_tails(rest, delimiter, trail)
    _COMBINE = (middle, tails, lead, delimiter)
    _BOUNDS = (min_length, max_length)


def combine_block(text: str) -> tuple[bytes, int, int]:
    """Worker: every candidate for one block of the first dictionary."""
    return parallel.pack_filtered(combine(parallel.lines(text), *_COMBINE), *_BOUNDS)


def survey_block(text: str) -> tuple[int, int]:
    """Worker for the sizing pass: ``(words, total length)`` of a block."""
    words = parallel.lines(text)
    return len(words), sum(map(len, words))


def survey_parallel(path: str, jobs: int) -> tuple[int, float]:
    count = total = 0
    for words, length in parallel.ordered(parallel.input_tasks(path), survey_block, jobs=jobs):
        count += words
        total += length
    return count, (total / count if count else 0.0)


def word_candidates(words: list[str], min_words: int, max_words: int,
                    lead: str, delimiter: str, trail: str):
    join = delimiter.join
    for size in range(min_words, max_words + 1):
        for combo in itertools.permutations(words, size):
            yield lead + join(combo) + trail


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a wordlist by combining words or dictionaries.",
        epilog=(
            "Examples:\n"
            "  multiple-words-joiner.py -i 'mega,corp,2026' --min-words 2 -D- > list.txt\n"
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
        help="Dictionary file, one word per line. Repeat for each dictionary. "
             "The first is streamed and may be any size (its duplicate lines "
             "are not removed); the others are loaded into memory.",
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
        help="With -i, the fewest words per candidate (default: all of them, "
             "or 1 when --max-words is given).",
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
    parallel.add_jobs_arg(parser)
    cli.add_common_args(parser)
    cli.add_output_args(parser)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    cli.set_quiet(args.quiet)

    if args.dicts and args.input:
        cli.die("use either -i or -d, not both")

    jobs = parallel.effective_jobs(
        args.jobs,
        None if args.dicts else "only dictionary mode (-d) has an input to split up",
    )

    # The affixes join like any other word, so `-p corp -D -` gives
    # corp-mega-2025 rather than corpmega-2025 -- unless told otherwise.
    delimiter = args.delimiter
    affix_delimiter = "" if args.no_affix_delimiter else delimiter
    lead = args.prepend + affix_delimiter if args.prepend else ""
    trail = affix_delimiter + args.append if args.append else ""

    if args.dicts:
        if "-" in args.dicts:
            cli.die("-d needs real files, not '-': each dictionary is read "
                    "more than once, which stdin cannot do")
        if jobs > 1:
            size, avg_length = survey_parallel(args.dicts[0], jobs)
        else:
            size, avg_length = survey_stream(args.dicts[0])
        first_length = avg_length
        if size == 0:
            cli.die(f"{args.dicts[0]} contains no usable words")
        cli.log(f"{args.dicts[0]}: {size:,} words (streamed)")
        total = size
        rest = []
        for path in args.dicts[1:]:
            words = cli.load_wordlist(path)
            cli.log(f"{path}: {len(words):,} distinct words")
            total *= len(words)
            avg_length += sum(map(len, words)) / len(words)
            rest.append(words)
        avg_length += len(delimiter) * (len(args.dicts) - 1)
        candidates = dictionary_candidates(args.dicts, rest, lead, delimiter, trail)

        # What one word of the first dictionary turns into. A worker builds
        # all of that before handing it back, so past a point the serial
        # path, which streams it, is the only safe one.
        per_word = total // size
        per_word_bytes = per_word * (avg_length + len(lead) + len(trail) + 1)
        if jobs > 1 and per_word_bytes > parallel.MAX_LINE_RESULT_BYTES:
            cli.warn(f"--jobs ignored: each word of {args.dicts[0]} becomes "
                     f"{per_word:,} candidates, too many to build in one piece")
            jobs = 1
    elif args.input:
        words = list(dict.fromkeys(w.strip() for w in args.input.split(",") if w.strip()))
        if not words:
            cli.die("-i did not contain any words")
        max_words = len(words) if args.max_words is None else args.max_words
        if args.min_words is not None:
            min_words = args.min_words
        else:
            min_words = 1 if args.max_words is not None else len(words)
        if not 1 <= min_words <= max_words <= len(words):
            cli.die(
                f"need 1 <= --min-words <= --max-words <= {len(words)} "
                f"(got min={min_words}, max={max_words})"
            )
        # Counted arithmetically: n!/(n-k)! orderings of k words out of n.
        # Building them to count them would exhaust memory at a dozen words.
        sizes = range(min_words, max_words + 1)
        counts = [perm(len(words), size) for size in sizes]
        total = sum(counts)
        mean_word = sum(len(w) for w in words) / len(words)
        mean_count = sum(n * size for n, size in zip(counts, sizes, strict=True)) / total
        avg_length = mean_word * mean_count + len(delimiter) * (mean_count - 1)
        candidates = word_candidates(words, min_words, max_words, lead, delimiter, trail)
    else:
        cli.die("provide either -i/--input or at least one -d/--dict")

    total = cli.sliced_total(total, args)
    estimate.confirm_or_exit(
        total,
        avg_length=avg_length + len(lead) + len(trail),
        force=args.force,
        max_candidates=args.max_candidates,
        label="combinations",
    )

    with cli.open_output(args.output, compress=args.gzip) as out:
        if jobs > 1:
            # Blocks of the first dictionary sized so that each one's output
            # is a few megabytes, however large the other dictionaries are.
            size = max(1, min(
                parallel.block_bytes(),
                int(parallel.TARGET_RESULT_BYTES / per_word_bytes * (first_length + 1)),
            ))
            writer = parallel.block_writer_for(out, args)
            parallel.drain(
                parallel.ordered(
                    parallel.input_tasks(args.dicts[0], size), combine_block, jobs=jobs,
                    initializer=start_worker,
                    initargs=(rest, lead, delimiter, trail, *parallel.length_bounds(args)),
                ),
                writer,
            )
        else:
            writer = cli.writer_for(out, args)
            writer.feed(candidates)
            writer.close()

    cli.log(f"Combinations: {writer.report()}"
            + (f" -> {args.output}" if args.output else ""))


if __name__ == "__main__":
    cli.run(main)
