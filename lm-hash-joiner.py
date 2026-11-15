#!/usr/bin/env python3
"""Rejoin cracked LM hash halves back into whole passwords.

Workflow this fits into:

  1. Crack the LM hashes            hashcat -m 3000 lm.txt ...
  2. Rejoin the halves (this tool)  lm-hash-joiner.py lm.pot lm-hashes.txt
  3. Recover the real case          --permute-case, or case-permutation.py
  4. Attack the NT hashes with the resulting list

Step 3 matters because LM is case-insensitive: everything this tool recovers
is uppercase and will not match the corresponding NT hash as-is.

Statistics go to stderr, so `lm-hash-joiner.py a.pot b.txt > list.txt` gives a
clean wordlist.
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

from wordlistlib import caseperm, cli  # noqa: E402

#: LM hash of an empty 7-character half. Resolves to "", not a failed lookup.
BLANK_HALF = "AAD3B435B51404EE"
#: Both halves empty. Windows stores this whenever it has no LM hash to
#: store -- LM disabled (the default since Vista) or a password longer than
#: 14 characters -- so it says nothing about the password and is skipped.
BLANK_LM = BLANK_HALF * 2
NOT_FOUND = "<HASH_NOT_FOUND>"

HEX16 = re.compile(r"^[0-9A-F]{16}$")
HEX32 = re.compile(r"^[0-9A-F]{32}$")


def load_pot_file(pot_file: str) -> dict[str, str]:
    """Load ``LM_HASH_HALF:PLAINTEXT`` lines into a lookup table.

    Accepts hashcat's bare ``<16 hex>:<plain>`` and John's ``$LM$<16 hex>:<plain>``.
    Only the line ending is removed, so a plaintext that begins or ends with
    a space keeps it, and hashcat's ``$HEX[...]`` plaintexts are decoded.
    """
    pot: dict[str, str] = {}
    skipped = 0
    with cli.open_input(pot_file) as handle:
        for line in cli.iter_lines(handle, strip=False):
            if line.startswith("$LM$"):
                line = line[len("$LM$"):]
            half, sep, plaintext = line.partition(":")
            if not sep:
                skipped += 1
                continue
            half = half.strip().upper()
            if HEX16.match(half):
                pot[half] = cli.decode_pot_plaintext(plaintext)
            else:
                skipped += 1
    if skipped:
        cli.warn(f"{skipped:,} unparseable line(s) in {pot_file} were ignored")
    if not pot:
        cli.die(f"{pot_file} contained no usable LM half-hash entries")
    cli.log(f"Loaded {len(pot):,} cracked LM halves from {pot_file}")
    return pot


def find_lm_hash(line: str) -> str | None:
    """Pull the LM hash out of a line.

    Returns the 32 hex characters, ``""`` when the line is a dump entry whose
    LM field holds no hash (``NO PASSWORD*****``, or empty), and ``None``
    when the line is not recognisable at all.

    In ``user:rid:LM:NT:::`` the LM hash is always the third field. Taking
    "the first field that looks like a hash" would pick up the NT hash
    whenever the LM field is a placeholder.
    """
    candidate = line.upper()
    if HEX32.match(candidate):
        return candidate
    fields = [field.strip() for field in candidate.split(":")]
    if len(fields) >= 4 and (HEX32.match(fields[2]) or HEX32.match(fields[3])):
        return fields[2] if HEX32.match(fields[2]) else ""
    return next((field for field in fields if HEX32.match(field)), None)


def resolve(half: str, pot: dict[str, str]) -> tuple[str, bool]:
    """Return ``(plaintext, found)`` for one LM half."""
    if half == BLANK_HALF:
        return "", True          # empty half: the password is under 8 chars
    if half in pot:
        return pot[half], True
    return NOT_FOUND, False


def process(hash_file: str, pot: dict[str, str], args):
    """Yield output lines, streaming rather than buffering the whole result."""
    stats = {"lines": 0, "skipped": 0, "no_lm": 0,
             "complete": 0, "partial": 0, "missing": 0}

    with cli.open_input(hash_file) as handle:
        for line in cli.iter_lines(handle):
            candidate = find_lm_hash(line)
            if candidate is None:
                stats["skipped"] += 1
                continue

            stats["lines"] += 1
            if candidate in ("", BLANK_LM):
                stats["no_lm"] += 1
                continue

            first, second = candidate[:16], candidate[16:]
            plain_first, found_first = resolve(first, pot)
            plain_second, found_second = resolve(second, pot)
            password = plain_first + plain_second

            if found_first and found_second:
                stats["complete"] += 1
            elif found_first or found_second:
                stats["partial"] += 1
            else:
                stats["missing"] += 1

            if args.only_cracked and not (found_first and found_second):
                continue

            if args.permute_case and found_first and found_second:
                if args.full:
                    prefix = candidate + ":"
                    yield from map(prefix.__add__,
                                   caseperm.permutations(password, args.max_upper))
                else:
                    yield from caseperm.permutations(password, args.max_upper)
            else:
                yield f"{candidate}:{password}" if args.full else password

    cli.log(
        f"Read {stats['lines']:,} entries "
        f"({stats['skipped']:,} unparseable lines skipped)"
    )
    cli.log(
        f"Fully recovered: {stats['complete']:,} | "
        f"partially recovered: {stats['partial']:,} | "
        f"not cracked: {stats['missing']:,} | "
        f"no LM hash stored: {stats['no_lm']:,}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Rejoin cracked LM hash halves into whole passwords.",
        epilog=(
            "Examples:\n"
            "  lm-hash-joiner.py lm.pot lm-hashes.txt -o joined.txt\n"
            "  lm-hash-joiner.py lm.pot lm-hashes.txt --only-cracked "
            "--permute-case -m 2 > nt-candidates.txt\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "pot_file",
        help="POT file of cracked LM halves. Format: LM_HASH_HALF:PLAINTEXT "
             "(hashcat -m 3000) or $LM$HASH:PLAINTEXT (John).",
    )
    parser.add_argument(
        "hash_file",
        help="File of full 32-character LM hashes, one per line. Lines from a "
             "dcsync/NTDS dump are accepted too; the LM field is picked out.",
    )
    parser.add_argument("-o", "--output", help="Output file. Defaults to stdout.")
    parser.add_argument(
        "--full", action="store_true",
        help="Prefix each result with the original LM hash (HASH:PLAINTEXT).",
    )
    parser.add_argument(
        "--only-cracked", action="store_true",
        help=f"Omit entries where a half is missing, instead of emitting {NOT_FOUND}.",
    )
    parser.add_argument(
        "--permute-case", action="store_true",
        help="Also emit case permutations of each recovered password. LM is "
             "case-insensitive, so this is what makes the output usable "
             "against the matching NT hashes.",
    )
    parser.add_argument(
        "-m", "--max-upper", type=int, metavar="N",
        help="With --permute-case, uppercase at most N characters per "
             "candidate. Strongly recommended: without it a 14-character "
             "password expands to 16,384 candidates.",
    )
    parser.add_argument(
        "--unique", action="store_true",
        help="Write each distinct line once. Accounts that share a password "
             "otherwise repeat it. Holds the distinct lines in memory.",
    )
    cli.add_common_args(parser, force=False)
    cli.add_output_args(parser)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    cli.set_quiet(args.quiet)

    if args.max_upper is not None and args.max_upper < 0:
        cli.die("--max-upper cannot be negative")
    if args.max_upper is not None and not args.permute_case:
        cli.warn("--max-upper has no effect without --permute-case")

    pot = load_pot_file(args.pot_file)

    results = process(args.hash_file, pot, args)
    if args.unique:
        results = cli.unique(results)

    with cli.open_output(args.output, compress=args.gzip) as out:
        writer = cli.writer_for(out, args)
        writer.feed(results)
        writer.close()

    cli.log(f"Output: {writer.report()}"
            + (f" -> {args.output}" if args.output else ""))


if __name__ == "__main__":
    cli.run(main)
