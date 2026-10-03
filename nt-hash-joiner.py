#!/usr/bin/env python3
"""Map NT hashes back to the plaintexts you have already cracked.

Input formats are detected structurally rather than by looking for a magic
string, so real secretsdump / NTDS output works:

    CORP\\jsmith:1103:aad3b435b51404ee...:31d6cfe0d16ae931...:::
    31d6cfe0d16ae931b73c59d7e0c089c0

POT files may be hashcat's ``<32 hex>:<password>`` or John's ``$NT$<32 hex>:<password>``.

Statistics go to stderr, so `nt-hash-joiner.py a.pot b.txt > list.txt` gives a
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

from wordlistlib import cli  # noqa: E402

#: NT hash of the empty string. A match means a blank password, not a miss.
BLANK_NT = "31D6CFE0D16AE931B73C59D7E0C089C0"
NOT_FOUND = "<HASH_NOT_FOUND>"
BLANK_PASSWORD = "<BLANK_PASSWORD>"

HEX32 = re.compile(r"^[0-9A-F]{32}$")


def load_pot_file(pot_file: str) -> dict[str, str]:
    """Load ``NT_HASH:PLAINTEXT`` lines into a lookup table."""
    pot: dict[str, str] = {}
    skipped = 0
    with cli.open_input(pot_file) as handle:
        for line in cli.iter_lines(handle):
            if line.startswith("$NT$"):
                line = line[len("$NT$"):]
            nt_hash, sep, plaintext = line.partition(":")
            if not sep:
                skipped += 1
                continue
            nt_hash = nt_hash.strip().upper()
            if HEX32.match(nt_hash):
                pot[nt_hash] = plaintext
            else:
                skipped += 1
    if skipped:
        cli.warn(f"{skipped:,} unparseable line(s) in {pot_file} were ignored")
    if not pot:
        cli.die(f"{pot_file} contained no usable NT hash entries")
    cli.log(f"Loaded {len(pot):,} cracked NT hashes from {pot_file}")
    return pot


def parse_line(line: str) -> tuple[str, str | None, list[str] | None]:
    """Pull the NT hash out of a line.

    Returns ``(nt_hash, username, fields)``; ``fields`` is None for a bare
    hash. A dcsync line is identified by its *shape* -- field 3 being 32 hex
    characters -- because the real format puts the LM hash value there, never
    the literal word "LM" that the previous version looked for.
    """
    fields = line.split(":")
    if len(fields) >= 4 and HEX32.match(fields[3].strip().upper()):
        return fields[3].strip().upper(), fields[0], fields
    bare = line.strip().upper()
    if HEX32.match(bare):
        return bare, None, None
    # `hash:plaintext` or `hash:anything` leftovers.
    if fields and HEX32.match(fields[0].strip().upper()):
        return fields[0].strip().upper(), None, None
    return "", None, None


def process(hash_file: str, pot: dict[str, str], args):
    """Yield output lines, streaming rather than buffering the whole result."""
    stats = {"lines": 0, "skipped": 0, "cracked": 0, "blank": 0, "missing": 0}

    with cli.open_input(hash_file) as handle:
        for line in cli.iter_lines(handle):
            nt_hash, username, fields = parse_line(line)
            if not nt_hash:
                stats["skipped"] += 1
                continue
            stats["lines"] += 1

            if nt_hash in pot:
                plaintext = pot[nt_hash]
                found = True
                stats["cracked"] += 1
            elif nt_hash == BLANK_NT:
                plaintext = BLANK_PASSWORD
                found = True
                stats["blank"] += 1
            else:
                plaintext = NOT_FOUND
                found = False
                stats["missing"] += 1

            if args.only_cracked and not found:
                continue

            # A blank password is a real finding but not a wordlist candidate,
            # so the marker is kept for the reporting formats only.
            if plaintext == BLANK_PASSWORD and not (args.full or args.user_pass):
                continue

            if args.user_pass:
                if username is None:
                    cli.warn(f"--user-pass: no username on line for {nt_hash}")
                    yield plaintext
                else:
                    yield f"{username}:{plaintext}"
            elif args.full:
                if fields is not None:
                    out_fields = list(fields)
                    out_fields[3] = plaintext
                    yield ":".join(out_fields)
                else:
                    yield f"{nt_hash}:{plaintext}"
            else:
                yield plaintext

    cli.log(
        f"Read {stats['lines']:,} NT hashes "
        f"({stats['skipped']:,} unparseable lines skipped)"
    )
    cli.log(
        f"Cracked: {stats['cracked']:,} | blank passwords: {stats['blank']:,} | "
        f"not cracked: {stats['missing']:,}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Replace NT hashes with the plaintexts from a POT file.",
        epilog=(
            "Examples:\n"
            "  nt-hash-joiner.py nt.pot ntds.dit.ntds --user-pass -o cracked.csv\n"
            "  nt-hash-joiner.py nt.pot hashes.txt --only-cracked > wordlist.txt\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "pot_file",
        help="POT file of cracked NT hashes: <32 hex>:<password> (hashcat) "
             "or $NT$<32 hex>:<password> (John).",
    )
    parser.add_argument(
        "hash_file",
        help="File of NT hashes: secretsdump/NTDS lines "
             "(user:rid:lm:nt:::) or one bare 32-character hash per line.",
    )
    parser.add_argument("-o", "--output", help="Output file. Defaults to stdout.")
    # Plain output is a wordlist; --full and --user-pass are reports.
    output_format = parser.add_mutually_exclusive_group()
    output_format.add_argument(
        "--full", action="store_true",
        help="Keep the original line structure with the NT hash replaced.",
    )
    output_format.add_argument(
        "--user-pass", action="store_true",
        help="Emit 'username:plaintext'. Needs a dcsync-style input line.",
    )
    parser.add_argument(
        "--only-cracked", action="store_true",
        help=f"Omit uncracked entries instead of emitting {NOT_FOUND}.",
    )
    cli.add_common_args(parser, force=False)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    cli.set_quiet(args.quiet)

    pot = load_pot_file(args.pot_file)

    written = 0
    with cli.open_output(args.output) as out:
        for line in process(args.hash_file, pot, args):
            out.write(line + "\n")
            written += 1

    if args.output:
        cli.log(f"Wrote {written:,} lines to {args.output}")


if __name__ == "__main__":
    main()
