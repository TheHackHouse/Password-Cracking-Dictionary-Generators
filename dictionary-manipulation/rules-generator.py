#!/usr/bin/env python3
"""Turn a list of strings into hashcat prefix and suffix rules.

Given 'corp' this emits the rule that prepends "corp" and the rule that
appends it, so a base dictionary can be decorated with company names, years,
site codes and so on.

Note on ordering: hashcat's ^X *prepends* X and rule functions run left to
right, so the prefix rule for "corp" is ^p^r^o^c, not ^c^o^r^p. The latter
produces "proc" and was what this tool used to emit.

Which characters can be an operand, per the hashcat rule documentation:

* Any printable ASCII character, '#' included. A comment is only a line
  that *starts* with '#', and these rules always start with ^ or $.
* A space. "Whitespace is ignored unless it is used as a parameter", so
  '$ ' appends one.
* Anything else -- tabs, control characters, bytes outside ASCII -- has to be
  written as a \\xNN hex byte, one function per byte. That is opt-in
  (--hex-escape) because it needs a hashcat recent enough to support it.
"""

from __future__ import annotations

import argparse
import string
import sys
from pathlib import Path

_here = Path(__file__).resolve().parent
for _candidate in (_here, _here.parent):
    if (_candidate / "wordlistlib").is_dir():
        sys.path.insert(0, str(_candidate))
        break

from wordlistlib import cli  # noqa: E402

#: hashcat applies at most this many functions per rule line.
DEFAULT_MAX_FUNCTIONS = 31

#: Characters written as themselves: printable ASCII and the space.
LITERAL_CHARS = (frozenset(string.printable) - frozenset(string.whitespace)) | {" "}

#: Skipped strings named individually before the rest are only counted.
MAX_SKIP_WARNINGS = 10


def needs_hex(text: str) -> list[str]:
    """The characters of ``text`` that can only be written as hex bytes."""
    return sorted({c for c in text if c not in LITERAL_CHARS})


def operands(text: str) -> list[str]:
    """One rule operand per byte hashcat will see, in order.

    A literal character is one operand. Anything else becomes one ``\\xNN``
    operand per UTF-8 byte, because hashcat rules work on bytes: 'é' is two
    functions, not one.
    """
    result: list[str] = []
    for char in text:
        if char in LITERAL_CHARS:
            result.append(char)
        else:
            result.extend(
                f"\\x{byte:02x}" for byte in char.encode("utf-8", cli.ENCODING_ERRORS)
            )
    return result


def function_count(text: str) -> int:
    """How many rule functions ``text`` costs: one per operand."""
    if LITERAL_CHARS.issuperset(text):
        return len(text)
    return len(operands(text))


def prefix_rule(text: str) -> str:
    """Rule that prepends ``text``. Built in reverse: each ^ pushes onto the front."""
    if not text:
        return ""
    # The common case, every character literal, needs no per-character work.
    ops = text[::-1] if LITERAL_CHARS.issuperset(text) else reversed(operands(text))
    return "^" + "^".join(ops)


def suffix_rule(text: str) -> str:
    """Rule that appends ``text``. Natural order: each $ pushes onto the end."""
    if not text:
        return ""
    ops = text if LITERAL_CHARS.issuperset(text) else operands(text)
    return "$" + "$".join(ops)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate hashcat prefix/suffix rules from a list of strings.",
        epilog=(
            "Examples:\n"
            "  rules-generator.py -i tokens.txt -o corp.rule\n"
            "  rules-generator.py -i tokens.txt --suffix-only --no-comments > suffix.rule\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-i", "--input", help="Input file, one string per line. Defaults to stdin.")
    parser.add_argument("-o", "--output", help="Output .rule file. Defaults to stdout.")
    side = parser.add_mutually_exclusive_group()
    side.add_argument("--prefix-only", action="store_true", help="Emit only prefix rules.")
    side.add_argument("--suffix-only", action="store_true", help="Emit only suffix rules.")
    parser.add_argument(
        "--no-comments", action="store_true",
        help="Omit the '# Prefix Rules' / '# Suffix Rules' header lines. "
             "hashcat ignores them either way; this is for tools that do not.",
    )
    parser.add_argument(
        "--keep-duplicates", action="store_true",
        help="Do not drop repeated rules.",
    )
    parser.add_argument(
        "--max-functions", type=int, default=DEFAULT_MAX_FUNCTIONS, metavar="N",
        help=f"Skip strings that need more than N rule functions, since "
             f"hashcat rejects longer rules (default: {DEFAULT_MAX_FUNCTIONS}). "
             f"That is one function per character, or per byte for "
             f"characters written as hex.",
    )
    parser.add_argument(
        "--hex-escape", "--allow-unsafe", dest="hex_escape", action="store_true",
        help="Emit strings containing tabs, control characters or non-ASCII "
             "characters, writing those as \\xNN hex bytes. Needs a hashcat "
             "version that supports \\xNN in rules; off by default, and such "
             "strings are skipped. Spaces and '#' never need this. "
             "(--allow-unsafe is the old name for this option.)",
    )
    cli.add_common_args(parser, force=False)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    cli.set_quiet(args.quiet)

    prefixes: list[str] = []
    suffixes: list[str] = []
    read = skipped_long = skipped_hex = 0
    seen: set[str] = set()

    with cli.open_input(args.input) as handle:
        for text in cli.iter_lines(handle):
            read += 1
            if not args.hex_escape and not LITERAL_CHARS.issuperset(text):
                skipped_hex += 1
                if skipped_hex <= MAX_SKIP_WARNINGS:
                    cli.warn(f"skipping {text!r}: {''.join(needs_hex(text))!r} can only "
                             f"be written as hex bytes (--hex-escape to emit it)")
                continue
            # One function per operand, so a multi-byte character costs more
            # than one against the limit.
            if function_count(text) > args.max_functions:
                skipped_long += 1
                continue
            # A string maps to exactly one prefix and one suffix rule, so one
            # set of strings deduplicates both.
            if not args.keep_duplicates:
                if text in seen:
                    continue
                seen.add(text)

            if not args.suffix_only:
                prefixes.append(prefix_rule(text))
            if not args.prefix_only:
                suffixes.append(suffix_rule(text))

    with cli.open_output(args.output) as out:
        if prefixes:
            if not args.no_comments:
                out.write("# Prefix Rules\n")
            out.write("\n".join(prefixes))
            out.write("\n")
        if suffixes:
            if not args.no_comments:
                out.write(("\n" if prefixes else "") + "# Suffix Rules\n")
            out.write("\n".join(suffixes))
            out.write("\n")

    cli.log(
        f"Read {read:,} strings; wrote {len(prefixes):,} prefix and "
        f"{len(suffixes):,} suffix rules."
    )
    if skipped_long:
        cli.log(f"Skipped {skipped_long:,} string(s) needing more than "
                f"{args.max_functions} rule functions.")
    if skipped_hex:
        cli.log(f"Skipped {skipped_hex:,} string(s) that need hex bytes "
                f"(tabs, control or non-ASCII characters); --hex-escape emits them.")


if __name__ == "__main__":
    cli.run(main)
