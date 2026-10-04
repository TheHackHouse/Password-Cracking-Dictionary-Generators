"""Loading the reference vocabulary for dict-compare.py and dict-extractor.py.

Both tools need the same thing and used to carry their own copy of this logic.

Sources are tried in order:

  1. --custom-dict, if given
  2. the NLTK 'words' corpus, if nltk is installed
  3. the system word list (/usr/share/dict/words), present on macOS and most
     Linux installs

so nltk is genuinely optional rather than a hard dependency.
"""

from __future__ import annotations

from pathlib import Path

from . import cli

#: Checked in order when neither --custom-dict nor nltk is available.
SYSTEM_WORD_LISTS = (
    "/usr/share/dict/words",
    "/usr/dict/words",
)


def _from_file(path: str, label: str) -> set[str]:
    with cli.open_input(path) as handle:
        vocabulary = {word.lower() for word in cli.iter_lines(handle)}
    if not vocabulary:
        cli.die(f"{path} contained no words")
    cli.log(f"Loaded {len(vocabulary):,} words from {label}")
    return vocabulary


def _from_nltk() -> set[str] | None:
    try:
        import nltk
    except ImportError:
        return None

    # Only hit the network when the corpus is genuinely missing; the original
    # scripts re-downloaded on every single run.
    try:
        nltk.data.find("corpora/words")
    except LookupError:
        cli.log("Downloading the NLTK 'words' corpus (one time)...")
        try:
            nltk.download("words", quiet=True)
            nltk.data.find("corpora/words")
        except Exception as exc:  # offline, proxy, read-only home...
            cli.warn(f"could not download the NLTK corpus ({exc})")
            return None

    from nltk.corpus import words as nltk_words

    vocabulary = {word.lower() for word in nltk_words.words()}
    cli.log(f"Loaded {len(vocabulary):,} words from the NLTK corpus")
    return vocabulary


def load(custom_dict: str | None) -> set[str]:
    """Return the reference vocabulary, lowercased."""
    if custom_dict:
        return _from_file(custom_dict, custom_dict)

    vocabulary = _from_nltk()
    if vocabulary:
        return vocabulary

    for candidate in SYSTEM_WORD_LISTS:
        if Path(candidate).is_file():
            return _from_file(candidate, f"the system word list ({candidate})")

    cli.die(
        "no word list available. Pass --custom-dict with your own list, or "
        "`pip install nltk`, or install a system dictionary "
        "(e.g. apt install wamerican)."
    )
