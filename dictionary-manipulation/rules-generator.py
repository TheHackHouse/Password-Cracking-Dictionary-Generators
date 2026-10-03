#!/usr/bin/env python3
"""Turn a list of strings into hashcat prefix and suffix rules.

Given 'corp' this emits the rule that prepends "corp" and the rule that
appends it, so a base dictionary can be decorated with company names, years,
site codes and so on.

Note on ordering: hashcat's ^X *prepends* X and rule functions run left to
right, so the prefix rule for "corp" is ^p^r^o^c, not ^c^o^r^p. The latter
produces "proc" and was what this tool used to emit.
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

#: Characters usable as a literal operand. A rule line is split on whitespace
#: and '#' starts a comment, so neither can appear unescaped.
SAFE_CHARS = frozenset(string.printable) - frozenset(string.whitespace) - {"#"}


def unsafe_characters(text: str) -> list[str]:
    return sorted({c for c in text if c not in SAFE_CHARS})


def prefix_rule(text: str) -> str:
    """Rule that prepends ``text``. Built in reverse: each ^ pushes onto the front."""
    return "".join(f"^{c}" for c in reversed(text))


def suffix_rule(text: str) -> str:
    """Rule that appends ``text``. Natural order: each $ pushes onto the end."""
    return "".join(f"${c}" for c in text)


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
        help="Omit the '# Prefix Rules' / '# Suffix Rules' headers so the file "
             "can be fed straight to hashcat -r without editing.",
    )
    parser.add_argument(
        "--keep-duplicates", action="store_true",
        help="Do not drop repeated rules.",
    )
    parser.add_argument(
        "--max-functions", type=int, default=DEFAULT_MAX_FUNCTIONS, metavar="N",
        help=f"Skip strings longer than N characters, since hashcat rejects "
             f"rules with more than N functions (default: {DEFAULT_MAX_FUNCTIONS}).",
    )
    parser.add_argument(
        "--allow-unsafe", action="store_true",
        help="Emit rules for strings containing whitespace or '#' anyway. "
             "hashcat will misparse them; off by default.",
    )
    cli.add_common_args(parser, force=False)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    cli.set_quiet(args.quiet)

    with cli.open_input(args.input) as handle:
        lines = list(cli.iter_lines(handle))

    prefixes: list[str] = []
    suffixes: list[str] = []
    skipped_long = 0
    skipped_unsafe = 0
    seen_prefix: set[str] = set()
    seen_suffix: set[str] = set()

    for text in lines:
        if len(text) > args.max_functions:
            skipped_long += 1
            continue
        bad = unsafe_characters(text)
        if bad and not args.allow_unsafe:
            skipped_unsafe += 1
            cli.warn(f"skipping {text!r}: contains {''.join(bad)!r} (use --allow-unsafe to force)")
            continue

        if not args.suffix_only:
            rule = prefix_rule(text)
            if args.keep_duplicates or rule not in seen_prefix:
                seen_prefix.add(rule)
                prefixes.append(rule)
        if not args.prefix_only:
            rule = suffix_rule(text)
            if args.keep_duplicates or rule not in seen_suffix:
                seen_suffix.add(rule)
                suffixes.append(rule)

    with cli.open_output(args.output) as out:
        if prefixes:
            if not args.no_comments:
                out.write("# Prefix Rules\n")
            out.write("".join(rule + "\n" for rule in prefixes))
        if suffixes:
            if not args.no_comments:
                out.write(("\n" if prefixes else "") + "# Suffix Rules\n")
            out.write("".join(rule + "\n" for rule in suffixes))

    cli.log(
        f"Read {len(lines):,} strings; wrote {len(prefixes):,} prefix and "
        f"{len(suffixes):,} suffix rules."
    )
    if skipped_long:
        cli.log(f"Skipped {skipped_long:,} string(s) longer than {args.max_functions} characters.")
    if skipped_unsafe:
        cli.log(f"Skipped {skipped_unsafe:,} string(s) containing whitespace or '#'.")


if __name__ == "__main__":
    main()
