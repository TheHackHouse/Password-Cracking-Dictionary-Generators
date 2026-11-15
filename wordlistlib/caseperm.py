"""Case permutation, shared by ``case-permutation.py`` and ``lm-hash-joiner.py``.

The important detail is that a character whose upper and lower forms are
identical (every digit and symbol) contributes exactly one variant. Expanding
it to two produces an output full of duplicate lines -- which is what the
Python generator used to do, while its C twin got it right.
"""

from __future__ import annotations

import itertools
import string
from functools import lru_cache
from math import comb


def char_variants(char: str) -> tuple[str, ...]:
    """Distinct case forms of a single character."""
    lower, upper = char.lower(), char.upper()
    if lower == upper:
        return (lower,)
    return (lower, upper)


_DELETE_ASCII_LETTERS = {ord(c): None for c in string.ascii_letters}


def cased_count(word: str) -> int:
    """How many characters of ``word`` have distinct upper and lower forms.

    For an ASCII word that is just its letters, which one C-level translate
    can count; this runs once per input word when a job is being sized, so
    on a large list it is most of the counting pass.
    """
    if word.isascii():
        return len(word) - len(word.translate(_DELETE_ASCII_LETTERS))
    return sum(1 for c in word if c.lower() != c.upper())


@lru_cache(maxsize=4096)
def _capped_count(cased: int, max_upper: int) -> int:
    return sum(comb(cased, k) for k in range(0, min(max_upper, cased) + 1))


def count_permutations(word: str, max_upper: int | None = None) -> int:
    """Number of distinct case permutations of ``word``."""
    cased = cased_count(word)
    if max_upper is None:
        return 1 << cased
    return _capped_count(cased, max_upper)


#: Characters whose variants are materialised as a block. 2^12 = 4096 tails
#: are built once and concatenated to each prefix, which turns the per-
#: candidate ``"".join`` of n pieces into a single two-piece concatenation.
TAIL_BITS = 12


def permutations(word: str, max_upper: int | None = None):
    """Yield every distinct case permutation of ``word``.

    ``max_upper`` caps how many characters may be uppercased at once, which is
    what makes the tool usable on long inputs: real passwords are ``Password``
    or ``PassWord``, not ``pAsSwOrD``.

    The unrestricted path materialises the last :data:`TAIL_BITS` characters'
    variants once and concatenates prefixes onto them. Emission order is
    unchanged -- ``itertools.product`` is lexicographic by position, so
    splitting it in two and nesting the halves yields the same sequence.
    """
    if max_upper is not None and max_upper >= cased_count(word):
        # A cap that cannot bind: take the faster unrestricted path, which
        # also keeps the C twin's emission order in step.
        max_upper = None

    if max_upper is None:
        variants = [char_variants(c) for c in word]
        split = len(variants) - TAIL_BITS
        if split <= 0:
            yield from map("".join, itertools.product(*variants))
            return
        tails = ["".join(combo) for combo in itertools.product(*variants[split:])]
        for prefix in map("".join, itertools.product(*variants[:split])):
            # map() over a bound method keeps the inner loop out of Python.
            yield from map(prefix.__add__, tails)
        return

    # Work per character rather than on word.lower(): a few characters change
    # length when their case changes, which would shift every later index.
    forms = [char_variants(c) for c in word]
    positions = [i for i, form in enumerate(forms) if len(form) == 2]
    base = [form[0] for form in forms]
    limit = min(max_upper, len(positions))
    for k in range(0, limit + 1):
        for chosen in itertools.combinations(positions, k):
            candidate = base[:]
            for i in chosen:
                candidate[i] = forms[i][1]
            yield "".join(candidate)


def common_forms(word: str) -> list[str]:
    """The handful of case forms that actually show up in real passwords."""
    return list(iter_common_forms(word))


def iter_common_forms(word: str):
    """The forms of :func:`common_forms` as an ordered, duplicate-free iterable.

    A dict's keys, in fact: ``dict.fromkeys`` drops the repeats (a
    digits-only word has one form, not five) and keeps the order without a
    Python-level loop, and handing the dict straight to the consumer saves
    building a list per word.
    """
    return dict.fromkeys(
        (word.lower(), word.upper(), word.capitalize(), word.swapcase(), word.title())
    )


def count_common_forms(word: str) -> int:
    """``len(common_forms(word))`` without building the ordered result."""
    return len({word.lower(), word.upper(), word.capitalize(), word.swapcase(), word.title()})


# --------------------------------------------------------------------------
# hashcat rule output
# --------------------------------------------------------------------------

#: hashcat encodes a rule position in base 36: 0-9 then A-Z, so position 10
#: is "A" and position 35 is "Z". Past that a position is not addressable.
_POSITION_DIGITS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
MAX_RULE_POSITION = len(_POSITION_DIGITS)

#: hashcat applies at most this many functions per rule line.
MAX_RULE_FUNCTIONS = 31


def position_digit(index: int) -> str:
    """hashcat's base-36 encoding of a character position."""
    if not 0 <= index < MAX_RULE_POSITION:
        raise ValueError(f"position {index} is outside hashcat's addressable range")
    return _POSITION_DIGITS[index]


def count_toggle_rules(positions: int, max_upper: int | None = None) -> int:
    limit = positions if max_upper is None else min(max_upper, positions)
    return sum(comb(positions, k) for k in range(0, limit + 1))


def toggle_rules(positions: int, max_upper: int | None = None):
    """Yield hashcat rules reproducing every case permutation.

    Each rule starts with ``l`` (lowercase everything) so the result does not
    depend on how the dictionary word was already cased, then toggles the
    chosen positions: ``lT0T3`` lowercases and uppercases characters 0 and 3.

    Unlike a wordlist, these apply to *every* word in a dictionary, so the
    cost is one rule per case pattern rather than one line per word per
    pattern.
    """
    if positions > MAX_RULE_POSITION:
        raise ValueError(
            f"hashcat can only address {MAX_RULE_POSITION} positions; got {positions}"
        )
    limit = positions if max_upper is None else min(max_upper, positions)
    if 1 + limit > MAX_RULE_FUNCTIONS:
        raise ValueError(
            f"{1 + limit} functions per rule exceeds hashcat's limit of "
            f"{MAX_RULE_FUNCTIONS}; lower --max-upper"
        )
    for k in range(0, limit + 1):
        for chosen in itertools.combinations(range(positions), k):
            yield "l" + "".join("T" + position_digit(i) for i in chosen)
