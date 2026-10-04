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
    """Yield every candidate, lazily, respecting the substitution budget.

    The candidate is carried down as a string and the last position is
    expanded inside the loop, rather than recursing once more and joining an
    accumulator list at every leaf. Emission order is unchanged.
    """
    if not positions:
        return
    budget = len(positions) if max_subs is None else max_subs
    last = len(positions) - 1

    def walk(index: int, prefix: str, remaining: int):
        plain, subs = positions[index]
        if index == last:
            for option in plain:
                yield prefix + option
            if remaining > 0:
                for option in subs:
                    yield prefix + option
            return
        for option in plain:
            yield from walk(index + 1, prefix + option, remaining)
        if remaining > 0:
            for option in subs:
                yield from walk(index + 1, prefix + option, remaining - 1)

    yield from walk(0, "", budget)


# --------------------------------------------------------------------------
# hashcat rule output
# --------------------------------------------------------------------------

def rule_substitutions(table, phrase: str | None):
    r"""``{letter: [single-character substitutions]}`` expressible as rules.

    Two limits of hashcat's ``sXY``, both reported and skipped:

    * X and Y must each be a single character, so the multi-character
      level-3 forms (``|_|``, ``|)``, ``/\/\``) and the space separators
      cannot be expressed.
    * ``sa4`` replaces *every* ``a`` in the word. Wordlist mode substitutes
      each position independently, so it can produce ``meg4corp`` *and*
      ``m3gacorp`` *and* ``b4nana``; the rule set cannot produce ``b4nana``
      from ``banana`` without also changing the other two a's. The rules are
      therefore a subset of the wordlist, traded for applying to every word
      in a dictionary at GPU speed.
    """
    if phrase:
        letters = sorted({c.lower() for c in phrase if c.lower() in table and c != " "})
    else:
        letters = sorted(c for c in table if c != " ")

    usable, dropped = {}, []
    for letter in letters:
        _, subs = table[letter]
        single = [sub for sub in subs if len(sub) == 1]
        dropped.extend(sub for sub in subs if len(sub) != 1)
        if single:
            usable[letter] = single
    return usable, dropped


def count_substitution_rules(usable: dict[str, list[str]], max_subs: int | None) -> int:
    letters = list(usable)
    budget = len(letters) if max_subs is None else min(max_subs, len(letters))
    # counts[k] = number of ways to substitute exactly k of the letters seen
    counts = [1] + [0] * budget
    for letter in letters:
        options = len(usable[letter])
        for k in range(budget, 0, -1):
            counts[k] += counts[k - 1] * options
    return sum(counts)


def substitution_rules(usable: dict[str, list[str]], max_subs: int | None):
    """Yield hashcat ``sXY`` rules covering the same substitutions."""
    letters = list(usable)
    budget = len(letters) if max_subs is None else max_subs

    def walk(index: int, prefix: str, remaining: int):
        if index == len(letters):
            yield prefix or ":"      # ":" is hashcat's do-nothing rule
            return
        letter = letters[index]
        yield from walk(index + 1, prefix, remaining)
        if remaining > 0:
            for sub in usable[letter]:
                yield from walk(index + 1, prefix + f"s{letter}{sub}", remaining - 1)

    yield from walk(0, "", budget)


def emit_rules(args, table) -> None:
    usable, dropped = rule_substitutions(table, args.input)
    if dropped:
        cli.warn(
            f"{len(dropped)} multi-character substitution(s) cannot be expressed "
            f"as hashcat rules and were skipped: {' '.join(sorted(set(dropped)))}"
        )
    if " " in (args.input or ""):
        cli.warn("space separators cannot be expressed as rules and were skipped")
    if not usable:
        cli.die("no rule-expressible substitutions at this level")

    total = count_substitution_rules(usable, args.max_subs)
    estimate.confirm_or_exit(
        cli.sliced_total(total, args),
        avg_length=3 * (args.max_subs or len(usable)),
        force=args.force,
        max_candidates=args.max_candidates,
        label="rules",
    )

    with cli.open_output(args.output, compress=args.gzip) as out:
        writer = cli.CandidateWriter(out, skip=args.skip or 0, limit=args.limit)
        writer.feed(substitution_rules(usable, args.max_subs))
        writer.close()

    cli.log(f"Rules: {writer.report()}"
            + (f" -> {args.output}" if args.output else ""))
    cli.log(f"Covering letters: {' '.join(usable)}")
    cli.log("Apply with: hashcat -m <mode> hashes.txt dict.txt -r <this file>")


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
        "--rules", action="store_true",
        help="Emit a hashcat .rule file of sXY substitutions instead of a "
             "wordlist, so the substitutions apply to a whole dictionary "
             "rather than one phrase. Multi-character substitutions are not "
             "expressible as rules and are skipped.",
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
    cli.add_output_args(parser)
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

    if args.rules:
        emit_rules(args, table)
        return

    positions = positions_for(phrase, table)
    total, exact_bytes = count_and_size(positions, args.max_subs)

    estimate.confirm_or_exit(
        cli.sliced_total(total, args),
        exact_bytes=exact_bytes,
        force=args.force,
        max_candidates=args.max_candidates,
        label="permutations",
    )

    with cli.open_output(args.output, compress=args.gzip) as out:
        writer = cli.writer_for(out, args)
        writer.feed(generate(positions, args.max_subs))
        writer.close()

    cli.log(f"Permutations: {writer.report()}"
            + (f" -> {args.output}" if args.output else ""))


if __name__ == "__main__":
    main()
