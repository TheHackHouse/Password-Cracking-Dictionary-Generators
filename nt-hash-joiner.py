#!/usr/bin/env python3
"""Map NT hashes back to the plaintexts you have already cracked.

Input formats are detected structurally rather than by looking for a magic
string, so real secretsdump / NTDS output works:

    CORP\\jsmith:1103:aad3b435b51404ee...:31d6cfe0d16ae931...:::
    jsmith:31d6cfe0d16ae931b73c59d7e0c089c0          (hashcat --username)
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
    """Load ``NT_HASH:PLAINTEXT`` lines into a lookup table.

    Only the line ending is removed, so a plaintext that begins or ends with
    a space keeps it, and hashcat's ``$HEX[...]`` plaintexts are decoded.
    """
    pot: dict[str, str] = {}
    skipped = 0
    with cli.open_input(pot_file) as handle:
        for line in cli.iter_lines(handle, strip=False):
            if line.startswith("$NT$"):
                line = line[len("$NT$"):]
            nt_hash, sep, plaintext = line.partition(":")
            if not sep:
                skipped += 1
                continue
            nt_hash = nt_hash.strip().upper()
            if HEX32.match(nt_hash):
                pot[nt_hash] = cli.decode_pot_plaintext(plaintext)
            else:
                skipped += 1
    if skipped:
        cli.warn(f"{skipped:,} unparseable line(s) in {pot_file} were ignored")
    if not pot:
        cli.die(f"{pot_file} contained no usable NT hash entries")
    cli.log(f"Loaded {len(pot):,} cracked NT hashes from {pot_file}")
    return pot


def as_hash(field: str) -> str:
    """``field`` as an uppercase NT hash, or ``""`` if it is not one.

    Called for every line of a dump, so the common case -- exactly 32 hex
    characters, no padding -- is a length test and one C-level hex decode
    rather than a strip, an upper and a regular expression.
    """
    if len(field) != 32:
        field = field.strip()
        if len(field) != 32:
            return ""
    try:
        # fromhex skips spaces, so 16 bytes back means all 32 were hex digits.
        if len(bytes.fromhex(field)) != 16:
            return ""
    except ValueError:
        return ""
    return field.upper()


def parse_line(line: str) -> tuple[str, str | None, list[str] | None, int]:
    """Pull the NT hash out of a line.

    Returns ``(nt_hash, username, fields, index)``. ``fields`` is the line
    split on ``:`` with the hash at ``fields[index]``, or None for a bare
    hash. A line is identified by its *shape*, never by a marker string:

    * ``user:rid:lm:nt:::`` -- field 3 is 32 hex characters (the real dump
      format puts the LM hash value in field 2, not the literal word "LM")
    * ``hash`` or ``hash:anything``
    * ``user:hash`` -- what ``hashcat --username`` takes
    """
    fields = line.split(":")
    count = len(fields)
    if count >= 4:
        nt_hash = as_hash(fields[3])
        if nt_hash:
            return nt_hash, fields[0], fields, 3
    nt_hash = as_hash(fields[0])
    if nt_hash:
        return nt_hash, None, None, 0
    if count >= 2:
        nt_hash = as_hash(fields[1])
        if nt_hash:
            return nt_hash, fields[0], fields, 1
    return "", None, None, 0


def process(hash_file: str, pot: dict[str, str], args):
    """Yield output lines, streaming rather than buffering the whole result."""
    # Plain local counters and flags: this loop runs once per line of a dump
    # that can be millions of lines long.
    skipped = cracked = blank = missing = no_username = 0
    lookup = pot.get
    only_cracked, user_pass, full = args.only_cracked, args.user_pass, args.full
    report = full or user_pass

    with cli.open_input(hash_file) as handle:
        for line in cli.iter_lines(handle):
            nt_hash, username, fields, index = parse_line(line)
            if not nt_hash:
                skipped += 1
                continue

            plaintext = lookup(nt_hash)
            if plaintext is not None:
                cracked += 1
            elif nt_hash == BLANK_NT:
                blank += 1
                # A blank password is a real finding but not a wordlist
                # candidate, so the marker is for the report formats only.
                if not report:
                    continue
                plaintext = BLANK_PASSWORD
            else:
                missing += 1
                if only_cracked:
                    continue
                plaintext = NOT_FOUND

            if user_pass:
                if username is None:
                    no_username += 1
                    yield plaintext
                else:
                    yield f"{username}:{plaintext}"
            elif full:
                if fields is not None:
                    fields[index] = plaintext
                    yield ":".join(fields)
                else:
                    yield f"{nt_hash}:{plaintext}"
            else:
                yield plaintext

    if no_username:
        cli.warn(
            f"--user-pass: {no_username:,} line(s) had no username; "
            f"the plaintext was written on its own"
        )
    cli.log(
        f"Read {cracked + blank + missing:,} NT hashes "
        f"({skipped:,} unparseable lines skipped)"
    )
    cli.log(
        f"Cracked: {cracked:,} | blank passwords: {blank:,} | "
        f"not cracked: {missing:,}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Replace NT hashes with the plaintexts from a POT file.",
        epilog=(
            "Examples:\n"
            "  nt-hash-joiner.py nt.pot domain.ntds --user-pass -o cracked.txt\n"
            "  nt-hash-joiner.py nt.pot hashes.txt --only-cracked --unique > wordlist.txt\n"
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
        help="File of NT hashes: secretsdump/NTDS lines (user:rid:lm:nt:::), "
             "user:hash lines, or one bare 32-character hash per line.",
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
        help="Emit 'username:plaintext'. Needs input lines that carry a "
             "username (dump lines or user:hash).",
    )
    parser.add_argument(
        "--only-cracked", action="store_true",
        help=f"Omit uncracked entries instead of emitting {NOT_FOUND}.",
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
