"""Case permutation, shared by ``case-permutation.py`` and ``lm-hash-joiner.py``.

The important detail is that a character whose upper and lower forms are
identical (every digit and symbol) contributes exactly one variant. Expanding
it to two produces an output full of duplicate lines -- which is what the
Python generator used to do, while its C twin got it right.
"""

from __future__ import annotations

import itertools
from math import comb


def char_variants(char: str) -> tuple[str, ...]:
    """Distinct case forms of a single character."""
    lower, upper = char.lower(), char.upper()
    if lower == upper:
        return (lower,)
    return (lower, upper)


def count_permutations(word: str, max_upper: int | None = None) -> int:
    """Number of distinct case permutations of ``word``."""
    cased = sum(1 for c in word if c.lower() != c.upper())
    if max_upper is None:
        return 1 << cased
    return sum(comb(cased, k) for k in range(0, min(max_upper, cased) + 1))


def permutations(word: str, max_upper: int | None = None):
    """Yield every distinct case permutation of ``word``.

    ``max_upper`` caps how many characters may be uppercased at once, which is
    what makes the tool usable on long inputs: real passwords are ``Password``
    or ``PassWord``, not ``pAsSwOrD``.
    """
    if max_upper is None:
        yield from map("".join, itertools.product(*(char_variants(c) for c in word)))
        return

    positions = [i for i, c in enumerate(word) if c.lower() != c.upper()]
    base = list(word.lower())
    limit = min(max_upper, len(positions))
    for k in range(0, limit + 1):
        for chosen in itertools.combinations(positions, k):
            candidate = base[:]
            for i in chosen:
                candidate[i] = word[i].upper()
            yield "".join(candidate)


def common_forms(word: str) -> list[str]:
    """The handful of case forms that actually show up in real passwords."""
    forms = [word.lower(), word.upper(), word.capitalize(), word.swapcase(), word.title()]
    seen: set[str] = set()
    unique: list[str] = []
    for form in forms:
        if form not in seen:
            seen.add(form)
            unique.append(form)
    return unique
