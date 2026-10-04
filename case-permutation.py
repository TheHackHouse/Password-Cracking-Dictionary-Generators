#!/usr/bin/env python3
"""Generate case permutations of a word, or of every word in a file.

Every distinct combination of upper and lower case is produced. Characters
with no case (digits, symbols) are left alone instead of being expanded into
two identical branches, so the output contains no duplicate lines.

Growth is 2^n in the number of cased characters, so for anything longer than a
dozen or so characters use --max-upper (cap how many letters are uppercased at
once) or --common (just the four or five forms people actually type).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_here = Path(__file__).resolve().parent
for _candidate in (_here, _here.parent):
    if (_candidate / "wordlistlib").is_dir():
        sys.path.insert(0, str(_candidate))
        break

from wordlistlib import caseperm, cli, estimate  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate case permutations for words.",
        epilog=(
            "Examples:\n"
            "  case-permutation.py -w megacorp -o perms.txt\n"
            "  case-permutation.py -w megacorp --max-upper 2\n"
            "  cat words.txt | case-permutation.py --common > cased.txt\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument("-w", "--word", help="A single input word.")
    source.add_argument(
        "-i", "--input", "-f", "--file", dest="input",
        help="File of words, one per line. Defaults to stdin when -w is not given.",
    )
    parser.add_argument(
        "-o", "--output",
        help="Output file. Defaults to stdout.",
    )
    parser.add_argument(
        "-m", "--max-upper", type=int, metavar="N",
        help="Uppercase at most N characters per candidate. Turns 2^n growth "
             "into something manageable for long inputs.",
    )
    parser.add_argument(
        "--no-c", action="store_true",
        help="Do not hand off to the compiled case-permutation binary even "
             "if one is present.",
    )
    parser.add_argument(
        "--rules", action="store_true",
        help="Emit a hashcat .rule file instead of a wordlist. The rules "
             "reproduce the same candidates but apply to every word in a "
             "dictionary, so a 10k-word list costs 2^n rules rather than "
             "10k x 2^n lines. See --positions.",
    )
    parser.add_argument(
        "--positions", type=int, metavar="N",
        help="With --rules, how many character positions to toggle "
             "(default: the length of the longest input word). hashcat can "
             "address 36 positions.",
    )
    parser.add_argument(
        "--common", action="store_true",
        help="Skip the full permutation and emit only lower, UPPER, Capitalised, "
             "swapped and Title case.",
    )
    parser.add_argument(
        "--max-candidates", type=int, default=estimate.DEFAULT_MAX_CANDIDATES,
        metavar="N", help="Safety limit before --force is required "
                          f"(default {estimate.DEFAULT_MAX_CANDIDATES:,}).",
    )
    cli.add_common_args(parser)
    cli.add_output_args(parser)
    return parser


def read_words(args) -> list[str]:
    if args.word:
        return [args.word]
    if args.input is None and sys.stdin.isatty():
        try:
            word = input("Please enter the word: ").strip()
        except EOFError:
            word = ""
        if not word:
            cli.die("no input provided")
        return [word]
    with cli.open_input(args.input) as handle:
        words = list(cli.iter_lines(handle))
    if not words:
        cli.die("input contained no words")
    return words


#: Name of the compiled twin, looked for next to this script.
C_BINARY = "case-permutation"


def try_compiled_binary(args) -> None:
    """Hand off to the compiled twin when it can do exactly this job.

    The C build is roughly 4x faster and produces byte-identical output, so
    the handoff is invisible apart from one line on stderr. It only happens
    for jobs C supports: a single -w word with no rule output, no gzip and
    no candidate-stream slicing.
    """
    if args.no_c or args.rules or args.common or not args.word:
        return
    if args.gzip or args.skip or args.limit:
        return
    if args.min_length or args.max_length is not None:
        return

    binary = Path(__file__).resolve().parent / C_BINARY
    if not (binary.is_file() and os.access(binary, os.X_OK)):
        return

    argv = [str(binary), "-w", args.word]
    if args.output:
        argv += ["-o", args.output]
    if args.max_upper is not None:
        argv += ["-m", str(args.max_upper)]
    if args.force:
        argv.append("--force")
    if args.quiet:
        argv.append("-q")

    cli.log(f"Using the compiled {C_BINARY} (~4x faster; --no-c to disable).")
    sys.stderr.flush()
    try:
        os.execv(str(binary), argv)
    except OSError as exc:            # fall back rather than fail the run
        cli.warn(f"could not run {binary}: {exc}; continuing in Python")


#: hashcat equivalents of the --common forms. Title case has no single
#: function, so it is not representable and is left out.
COMMON_RULES = [
    (":", "unchanged"),
    ("l", "lowercase"),
    ("u", "UPPERCASE"),
    ("c", "Capitalised"),
    ("t", "sWAPPED CASE"),
]


def emit_rules(args) -> None:
    """Write a hashcat rule file instead of a wordlist."""
    if args.common:
        rules = [rule for rule, _ in COMMON_RULES]
        cli.log("Emitting the --common forms as rules "
                "(title case has no hashcat function and is omitted).")
    else:
        if args.positions is not None:
            positions = args.positions
        else:
            words = read_words(args)
            positions = max(len(word) for word in words)
            cli.log(f"Using {positions} positions (longest input word). "
                    f"Override with --positions.")
        if positions < 1:
            cli.die("--positions must be at least 1")
        try:
            total = caseperm.count_toggle_rules(positions, args.max_upper)
            estimate.confirm_or_exit(
                cli.sliced_total(total, args),
                avg_length=1 + 2 * (args.max_upper or positions),
                force=args.force,
                max_candidates=args.max_candidates,
                label="rules",
            )
            rules = caseperm.toggle_rules(positions, args.max_upper)
        except ValueError as exc:
            cli.die(str(exc))

    with cli.open_output(args.output, compress=args.gzip) as out:
        writer = cli.CandidateWriter(
            out, skip=args.skip or 0, limit=args.limit,
        )
        writer.feed(rules)
        writer.close()

    cli.log(f"Rules: {writer.report()}"
            + (f" -> {args.output}" if args.output else ""))
    cli.log("Apply with: hashcat -m <mode> hashes.txt dict.txt -r <this file>")


def main() -> None:
    args = build_parser().parse_args()
    cli.set_quiet(args.quiet)

    if args.max_upper is not None and args.max_upper < 0:
        cli.die("--max-upper cannot be negative")
    if args.common and args.max_upper is not None:
        cli.die("--common and --max-upper are mutually exclusive")
    if args.positions is not None and not args.rules:
        cli.warn("--positions has no effect without --rules")

    if args.rules:
        emit_rules(args)
        return

    try_compiled_binary(args)         # replaces this process when it applies

    words = read_words(args)

    if args.common:
        total = sum(len(caseperm.common_forms(w)) for w in words)
    else:
        total = sum(caseperm.count_permutations(w, args.max_upper) for w in words)
    avg_length = sum(len(w) for w in words) / len(words)

    estimate.confirm_or_exit(
        cli.sliced_total(total, args),
        avg_length=avg_length,
        force=args.force,
        max_candidates=args.max_candidates,
        label="permutations",
    )

    def candidates():
        for word in words:
            if args.common:
                yield from caseperm.common_forms(word)
            else:
                yield from caseperm.permutations(word, args.max_upper)

    with cli.open_output(args.output, compress=args.gzip) as out:
        writer = cli.writer_for(out, args)
        writer.feed(candidates())
        writer.close()

    cli.log(f"Permutations: {writer.report()}"
            + (f" -> {args.output}" if args.output else ""))


if __name__ == "__main__":
    main()
