#!/usr/bin/env python3
"""Split a wordlist into runs of letters, digits and special characters.

Useful for working out what a cracked password set is actually made of: feed
in the cracked plaintexts and you get the base words, the numbers people
append, and the symbols they use, each ready to be recombined with
multiple-words-joiner.py or turned into rules with rules-generator.py.

This replaces the former extract_strings.py, extract_strings-v0.py and
longer-strings.py, which were three near-copies of the same logic. The
two-category behaviour of the older pair is `--categories letters,specials`.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_here = Path(__file__).resolve().parent
for _candidate in (_here, _here.parent):
    if (_candidate / "wordlistlib").is_dir():
        sys.path.insert(0, str(_candidate))
        break

from wordlistlib import cli  # noqa: E402

CATEGORIES = ("letters", "short_letters", "numbers", "specials")
DEFAULT_CATEGORIES = ",".join(CATEGORIES)

ASCII_SPLIT = re.compile(r"[a-zA-Z]+|\d+|[^a-zA-Z\d]+")


def split_sequences(line: str, unicode_mode: bool):
    """Yield consecutive runs of letters, digits or other characters."""
    if not unicode_mode:
        yield from ASCII_SPLIT.findall(line)
        return

    def kind(char: str) -> str:
        if char.isalpha():
            return "alpha"
        if char.isdigit():
            return "digit"
        return "other"

    run = ""
    run_kind = None
    for char in line:
        this_kind = kind(char)
        if this_kind == run_kind:
            run += char
        else:
            if run:
                yield run
            run, run_kind = char, this_kind
    if run:
        yield run


def classify(seq: str, short_letters_enabled: bool, unicode_mode: bool) -> str | None:
    is_alpha = seq.isalpha() if unicode_mode else seq.isascii() and seq.isalpha()
    is_digit = seq.isdigit() if unicode_mode else seq.isascii() and seq.isdigit()
    if is_alpha:
        if short_letters_enabled and len(seq) <= 2:
            return "short_letters"
        return "letters"
    if is_digit:
        return "numbers"
    return "specials"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Split strings into letter, digit and special-character runs.",
        epilog=(
            "Examples:\n"
            "  extract-strings.py -i cracked.txt --out-dir parts/\n"
            "  extract-strings.py -i cracked.txt --categories letters,numbers\n"
            "  cat cracked.txt | extract-strings.py --categories letters -o words.txt\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-i", "--input", help="Input file. Defaults to stdin.")
    parser.add_argument(
        "-o", "--output",
        help="Write a single category to this file (or stdout with '-'). "
             "Requires exactly one --categories entry.",
    )
    parser.add_argument(
        "--out-dir", default=".",
        help="Directory for the per-category files (default: current directory).",
    )
    parser.add_argument(
        "--categories", default=DEFAULT_CATEGORIES,
        help=f"Comma separated subset of: {', '.join(CATEGORIES)} "
             f"(default: all). 'short_letters' splits runs of 1-2 letters out "
             f"of 'letters'.",
    )
    parser.add_argument(
        "--no-sort", action="store_true",
        help="Leave output in input order instead of sorting and deduplicating.",
    )
    parser.add_argument(
        "--unicode", action="store_true",
        help="Treat accented and non-ASCII letters as letters rather than "
             "special characters.",
    )
    cli.add_common_args(parser, force=False)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    cli.set_quiet(args.quiet)

    selected = [c.strip() for c in args.categories.split(",") if c.strip()]
    unknown = [c for c in selected if c not in CATEGORIES]
    if unknown:
        cli.die(f"unknown categories: {', '.join(unknown)} (choose from {', '.join(CATEGORIES)})")
    if not selected:
        cli.die("--categories selected nothing")

    short_enabled = "short_letters" in selected

    if args.output:
        if len(selected) != 1:
            cli.die("-o writes one category; pass a single --categories value or use --out-dir")
        targets = {selected[0]: args.output}
    else:
        out_dir = Path(args.out_dir)
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            cli.die(f"cannot create {out_dir}: {exc}")
        targets = {name: str(out_dir / f"{name}.txt") for name in selected}

    counts = dict.fromkeys(selected, 0)
    handles = {}
    try:
        for name, path in targets.items():
            try:
                handles[name] = open(path, "w", encoding="utf-8", newline="\n") \
                    if path != "-" else sys.stdout
            except OSError as exc:
                cli.die(f"cannot write {path}: {exc}")

        with cli.open_input(args.input) as infile:
            for line in cli.iter_lines(infile, skip_empty=False):
                for seq in split_sequences(line, args.unicode):
                    category = classify(seq, short_enabled, args.unicode)
                    if category in handles:
                        handles[category].write(seq + "\n")
                        counts[category] += 1
    finally:
        for handle in handles.values():
            if handle is not sys.stdout:
                handle.close()

    if not args.no_sort:
        for path in targets.values():
            if path != "-":
                cli.sort_unique_file(path)

    for name in selected:
        cli.log(f"{name}: {counts[name]:,} sequences -> {targets[name]}")


if __name__ == "__main__":
    main()
