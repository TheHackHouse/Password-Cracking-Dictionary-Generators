#!/usr/bin/env python3
"""Generate leetspeak variations of an input phrase.

Substitutions are grouped into three levels so the output stays a useful size:

  1  digit swaps only          a->4  e->3  i->1  o->0  s->5
  2  + symbol swaps            a->@  b->8  c->(  g->6  h->#  i->!  l->1
                               s->$  t->7  z->2
  3  + multi-character swaps   d->|)  k->|<  m->/\\/\\  u->|_|  v->\\/  x-><

Case variants of each letter are always included, as are '-', '_' and ' ' for
spaces. --max-subs caps how many characters are substituted at once, which is
what keeps the output realistic: real leetspeak swaps one to three characters,
not all of them.

Statistics go to stderr, so `leetspeak-generator.py -i "mega corp" > out.txt`
produces a clean wordlist.
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

from wordlistlib import cli, estimate  # noqa: E402

# Substitutions by level. Level N includes every level <= N.
LEVEL_1 = {"a": ["4"], "e": ["3"], "i": ["1"], "o": ["0"], "s": ["5"]}
LEVEL_2 = {
    "a": ["@"], "b": ["8"], "c": ["("], "g": ["6"], "h": ["#"],
    "i": ["!"], "l": ["1"], "s": ["$"], "t": ["7"], "z": ["2"],
}
LEVEL_3 = {
    "d": ["|)", "|]"], "k": ["|<"], "m": ["/\\/\\"], "n": ["/\\/"],
    "u": ["|_|"], "v": ["\\/"], "w": ["\\/\\/"], "x": ["><"],
    "o": ["()"], "l": ["|_"], "c": ["<"], "t": ["+"],
}

#: Alternatives for a space. These are separators, not substitutions, so they
#: are not counted against --max-subs.
SEPARATORS = ["-", "_", " "]


def build_table(level: int, keep_case: bool = True) -> dict[str, tuple[list[str], list[str]]]:
    """Return ``{char: (plain_forms, substitutions)}`` for the given level."""
    subs: dict[str, list[str]] = {}
    for table in (LEVEL_1, LEVEL_2, LEVEL_3)[:level]:
        for char, replacements in table.items():
            subs.setdefault(char, []).extend(replacements)

    result: dict[str, tuple[list[str], list[str]]] = {}
    for char in "abcdefghijklmnopqrstuvwxyz":
        plain = [char, char.upper()] if keep_case else [char]
        result[char] = (plain, list(dict.fromkeys(subs.get(char, []))))
    result[" "] = (list(SEPARATORS), [])
    return result


def positions_for(text: str, table) -> list[tuple[list[str], list[str]]]:
    """Per-character (plain forms, substitutions) for the whole input."""
    positions = []
    for char in text:
        lower = char.lower()
        if lower in table:
            plain, subs = table[lower]
            # An uppercase input letter still only needs its two case forms.
            positions.append((list(plain), list(subs)))
        else:
            positions.append(([char], []))
    return positions


def count_and_size(positions, max_subs: int | None) -> tuple[int, int]:
    """Exact candidate count and exact output size in bytes.

    Computed with a backwards DP over (position, remaining substitution
    budget), so multi-character substitutions like ``|_|`` are measured at
    their real length rather than assumed to be one character.
    """
    budget = len(positions) if max_subs is None else min(max_subs, len(positions))
    # counts[b] / lengths[b] for the suffix starting at the current position.
    counts = [1] * (budget + 1)
    lengths = [0] * (budget + 1)

    for plain, subs in reversed(positions):
        new_counts = [0] * (budget + 1)
        new_lengths = [0] * (budget + 1)
        for b in range(budget + 1):
            total_count = 0
            total_length = 0
            for option in plain:
                total_count += counts[b]
                total_length += len(option) * counts[b] + lengths[b]
            if b > 0:
                for option in subs:
                    total_count += counts[b - 1]
                    total_length += len(option) * counts[b - 1] + lengths[b - 1]
            new_counts[b] = total_count
            new_lengths[b] = total_length
        counts, lengths = new_counts, new_lengths

    count = counts[budget]
    return count, lengths[budget] + count  # + one newline per candidate


def generate(positions, max_subs: int | None):
    """Yield every candidate, lazily, respecting the substitution budget."""
    budget = len(positions) if max_subs is None else max_subs
    acc: list[str] = []

    def walk(index: int, remaining: int):
        if index == len(positions):
            yield "".join(acc)
            return
        plain, subs = positions[index]
        for option in plain:
            acc.append(option)
            yield from walk(index + 1, remaining)
            acc.pop()
        if remaining > 0:
            for option in subs:
                acc.append(option)
                yield from walk(index + 1, remaining - 1)
                acc.pop()

    yield from walk(0, budget)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate leetspeak variations of an input phrase.",
        epilog=(
            "Examples:\n"
            "  leetspeak-generator.py -i 'mega corp' --level 1 -o base.txt\n"
            "  leetspeak-generator.py -i 'mega corp' --level 3 --max-subs 2 > base.txt\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-i", "--input",
        help="Input phrase. Prompted for interactively when omitted.",
    )
    parser.add_argument(
        "-o", "--output",
        help="Output file. Defaults to stdout.",
    )
    parser.add_argument(
        "-l", "--level", type=int, choices=(1, 2, 3), default=2,
        help="Substitution level: 1 digits, 2 +symbols, 3 +multi-character "
             "(default: 2).",
    )
    parser.add_argument(
        "-m", "--max-subs", type=int, metavar="N",
        help="Substitute at most N characters per candidate. Spaces do not "
             "count. Without this, every substitutable character is swapped "
             "in every combination.",
    )
    parser.add_argument(
        "--no-case", action="store_true",
        help="Do not also vary upper/lower case (substitutions only).",
    )
    parser.add_argument(
        "--max-candidates", type=int, default=estimate.DEFAULT_MAX_CANDIDATES,
        metavar="N", help="Safety limit before --force is required "
                          f"(default {estimate.DEFAULT_MAX_CANDIDATES:,}).",
    )
    cli.add_common_args(parser)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    cli.set_quiet(args.quiet)

    if args.max_subs is not None and args.max_subs < 0:
        cli.die("--max-subs cannot be negative")

    if args.input is not None:
        phrase = args.input.strip()
    elif sys.stdin.isatty():
        try:
            phrase = input("Enter input phrase: ").strip()
        except EOFError:
            phrase = ""
    else:
        phrase = sys.stdin.read().strip()
    if not phrase:
        cli.die("no input provided")

    table = build_table(args.level, keep_case=not args.no_case)
    positions = positions_for(phrase, table)
    total, exact_bytes = count_and_size(positions, args.max_subs)

    estimate.confirm_or_exit(
        total,
        exact_bytes=exact_bytes,
        force=args.force,
        max_candidates=args.max_candidates,
        label="permutations",
    )

    written = 0
    with cli.open_output(args.output) as out:
        for candidate in generate(positions, args.max_subs):
            out.write(candidate + "\n")
            written += 1

    if args.output:
        cli.log(f"Wrote {written:,} permutations to {args.output}")


if __name__ == "__main__":
    main()
