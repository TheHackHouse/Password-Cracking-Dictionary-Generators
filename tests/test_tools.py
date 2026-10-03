"""Regression tests for the dictionary generators.

Each test in the first class pins a bug that was live in the repository, so a
reintroduction fails here rather than in an engagement.
"""

from __future__ import annotations

import compileall
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
TOOLS = REPO / "dictionary-manipulation"

sys.path.insert(0, str(REPO))

from wordlistlib import caseperm, estimate  # noqa: E402


def run(script: Path, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True, text=True, input=stdin, cwd=REPO,
    )


def load(script: Path):
    """Import a hyphenated script file as a module."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(script.stem.replace("-", "_"), script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------
# Bugs that were live in the repository
# --------------------------------------------------------------------------

class TestRegressions:
    def test_every_script_compiles(self):
        """lm-hash-joiner.py shipped with a SyntaxError and could never run."""
        assert compileall.compile_dir(str(REPO), quiet=2, force=True), \
            "at least one Python file does not compile"

    def test_case_permutation_has_no_duplicates(self):
        """Digits and symbols used to be expanded into two identical branches."""
        result = run(REPO / "case-permutation.py", "-w", "pa55w0rd!", "-q", "--force")
        lines = result.stdout.splitlines()
        assert len(lines) == 32, f"expected 2^5 for five letters, got {len(lines)}"
        assert len(set(lines)) == len(lines), "output contains duplicates"

    def test_prefix_rule_order(self):
        """^X prepends, so the prefix rule for 'corp' must be built in reverse."""
        module = load(TOOLS / "rules-generator.py")
        assert module.prefix_rule("corp") == "^p^r^o^c"
        assert module.suffix_rule("corp") == "$c$o$r$p"

    def test_nt_joiner_reads_real_secretsdump_output(self, tmp_path):
        """fields[2] holds the LM hash value, never the literal string 'LM'."""
        pot = tmp_path / "nt.pot"
        pot.write_text("31d6cfe0d16ae931b73c59d7e0c089c1:Password1\n")
        hashes = tmp_path / "ntds.txt"
        hashes.write_text(
            "CORP\\jsmith:1103:aad3b435b51404eeaad3b435b51404ee:"
            "31d6cfe0d16ae931b73c59d7e0c089c1:::\n"
        )
        result = run(REPO / "nt-hash-joiner.py", str(pot), str(hashes), "-q")
        assert result.stdout == "Password1\n", result.stderr

    def test_nt_joiner_user_pass_keeps_username(self, tmp_path):
        pot = tmp_path / "nt.pot"
        pot.write_text("31d6cfe0d16ae931b73c59d7e0c089c1:Password1\n")
        hashes = tmp_path / "ntds.txt"
        hashes.write_text(
            "CORP\\jsmith:1103:aad3b435b51404eeaad3b435b51404ee:"
            "31d6cfe0d16ae931b73c59d7e0c089c1:::\n"
        )
        result = run(REPO / "nt-hash-joiner.py", str(pot), str(hashes), "--user-pass", "-q")
        assert result.stdout == "CORP\\jsmith:Password1\n", result.stderr

    def test_lm_joiner_blank_half(self, tmp_path):
        """AAD3B435B51404EE is an empty half, not an uncracked one."""
        pot = tmp_path / "lm.pot"
        pot.write_text("E52CAC67419A9A22:ABCDEFG\n")
        hashes = tmp_path / "lm.txt"
        hashes.write_text("E52CAC67419A9A22AAD3B435B51404EE\n")
        result = run(REPO / "lm-hash-joiner.py", str(pot), str(hashes), "-q")
        assert result.stdout == "ABCDEFG\n", result.stderr

    def test_dict_extractor_backtracks(self):
        """The old matcher gave up when the longest word led to a dead end."""
        module = load(TOOLS / "dict-extractor.py")
        vocabulary = {"password", "pass", "words", "sy"}
        spans = module.split_into_words("passwordsy", vocabulary, 2)
        assert spans is not None
        assert ["passwordsy"[a:b] for a, b in spans] == ["password", "sy"]

    def test_keyboard_walk_counts_before_generating(self):
        """The count has to be exact, because the prompt depends on it."""
        module = load(REPO / "keyboard-walk.py")
        adjacency = module.build_adjacency(module.LAYOUTS["qwerty"])
        for length in (1, 2, 3, 4):
            predicted = module.count_walks(adjacency, length)
            generated = sum(1 for _ in module.walks(adjacency, length))
            assert predicted == generated, f"length {length}"

    def test_filter_by_length_strips_whitespace(self):
        """The length test used to strip but the write did not."""
        result = run(TOOLS / "filter-by-length.py", "--max-length", "3", "-q",
                     stdin="ab  \n\nabcdefgh\nxyz\n")
        assert result.stdout == "ab\nxyz\n", result.stderr


# --------------------------------------------------------------------------
# Behaviour that must not drift
# --------------------------------------------------------------------------

class TestBehaviour:
    def test_keyboard_walk_layouts_have_unique_keys(self):
        module = load(REPO / "keyboard-walk.py")
        for name, rows in module.LAYOUTS.items():
            keys = [key for row in rows for key in row]
            assert len(keys) == len(set(keys)), f"layout {name} repeats a key"

    def test_keyboard_walk_known_counts(self):
        """Pinned against the original implementation's output."""
        module = load(REPO / "keyboard-walk.py")
        adjacency = module.build_adjacency(module.LAYOUTS["qwerty"])
        assert module.count_walks(adjacency, 3) == 1824
        assert module.count_walks(adjacency, 4) == 11900
        assert module.count_walks(adjacency, 6) == 515362

    @pytest.mark.parametrize("level,max_subs", [(1, None), (2, None), (3, None), (3, 1), (3, 2)])
    def test_leetspeak_prediction_is_exact(self, level, max_subs, tmp_path):
        """The predicted count and byte size must match what is written."""
        module = load(REPO / "leetspeak-generator.py")
        table = module.build_table(level)
        positions = module.positions_for("mega corp", table)
        count, size = module.count_and_size(positions, max_subs)
        produced = list(module.generate(positions, max_subs))
        assert len(produced) == count
        assert sum(len(c) + 1 for c in produced) == size

    def test_leetspeak_max_subs_budget(self):
        module = load(REPO / "leetspeak-generator.py")
        table = module.build_table(3)
        positions = module.positions_for("ab", table)
        produced = set(module.generate(positions, 1))
        assert produced == {"ab", "aB", "a8", "Ab", "AB", "A8", "4b", "4B", "@b", "@B"}

    def test_case_permutation_max_upper(self):
        assert list(caseperm.permutations("abc", 1)) == ["abc", "Abc", "aBc", "abC"]
        assert caseperm.count_permutations("abc", 1) == 4
        assert caseperm.count_permutations("pa55w0rd") == 32

    def test_case_permutation_count_matches_generation(self):
        for word in ("abc", "pa55w0rd!", "Mega Corp"):
            for cap in (None, 0, 1, 2):
                assert caseperm.count_permutations(word, cap) == \
                    len(list(caseperm.permutations(word, cap)))

    def test_multiple_words_joiner_defaults_to_full_permutations(self):
        result = run(REPO / "multiple-words-joiner.py", "-i", "cat,dog", "-q", "--force")
        assert sorted(result.stdout.split()) == ["catdog", "dogcat"]

    def test_multiple_words_joiner_subsets(self):
        result = run(REPO / "multiple-words-joiner.py", "-i", "cat,dog",
                     "--min-words", "1", "-q", "--force")
        assert sorted(result.stdout.split()) == ["cat", "catdog", "dog", "dogcat"]

    def test_swapcase_modes(self):
        result = run(REPO / "swapcase.py", "-m", "title", "-q", stdin="pass word\n")
        assert result.stdout == "Pass Word\n"

    def test_extract_strings_categories(self, tmp_path):
        result = run(TOOLS / "extract-strings.py", "--categories", "numbers",
                     "-o", "-", "-q", stdin="Password123!\nacme2026\n")
        assert result.stdout == "123\n2026\n"

    def test_rules_generator_skips_unsafe(self):
        result = run(TOOLS / "rules-generator.py", "--prefix-only", "--no-comments", "-q",
                     stdin="corp\nbad token\n")
        assert result.stdout == "^p^r^o^c\n"

    def test_format_size(self):
        assert estimate.format_size(512) == "512 Bytes"
        assert estimate.format_size(2048) == "2.00 KB"
        assert estimate.format_size(5 * 1024 ** 3) == "5.00 GB"


# --------------------------------------------------------------------------
# Shared CLI conventions
# --------------------------------------------------------------------------

SCRIPTS = [
    REPO / "case-permutation.py",
    REPO / "keyboard-walk.py",
    REPO / "leetspeak-generator.py",
    REPO / "lm-hash-joiner.py",
    REPO / "multiple-words-joiner.py",
    REPO / "nt-hash-joiner.py",
    REPO / "swapcase.py",
    TOOLS / "dict-compare.py",
    TOOLS / "dict-extractor.py",
    TOOLS / "extract-strings.py",
    TOOLS / "filter-by-length.py",
    TOOLS / "rules-generator.py",
]


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_help_works(script):
    result = run(script, "--help")
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout


#: dict-extractor.py splits its input across two files (--known-out and
#: --remaining-out), so a single -o has nothing to mean for it.
SINGLE_OUTPUT_SCRIPTS = [s for s in SCRIPTS if s.name != "dict-extractor.py"]


@pytest.mark.parametrize("script", SINGLE_OUTPUT_SCRIPTS, ids=lambda p: p.name)
def test_supports_output_flag(script):
    """Every tool writes its wordlist to -o, or to stdout by default."""
    result = run(script, "--help")
    assert "-o" in result.stdout and "--output" in result.stdout


def test_statistics_never_reach_stdout():
    """`tool ... > list.txt` must produce a clean wordlist."""
    result = run(REPO / "leetspeak-generator.py", "-i", "ab", "--level", "1", "--force")
    assert "Total permutations" not in result.stdout
    assert "Total permutations" in result.stderr
    for line in result.stdout.splitlines():
        assert line and not line.startswith("#")


# --------------------------------------------------------------------------
# Documentation
# --------------------------------------------------------------------------

class TestDocumentation:
    """The README is the only docs there are, so it has to stay accurate."""

    @staticmethod
    def _flags(script: Path) -> set[str]:
        import re
        out = run(script, "--help").stdout
        return {
            f for f in re.findall(r"(?<![\w-])(--[a-z][a-z0-9-]+)", out)
            if f != "--help"
        }

    @pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
    def test_every_flag_is_documented(self, script):
        readme = (REPO / "README.md").read_text()
        undocumented = sorted(f for f in self._flags(script) if f not in readme)
        assert not undocumented, (
            f"{script.name} has flags missing from README.md: {undocumented}"
        )

    @pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
    def test_tool_is_named_in_readme(self, script):
        readme = (REPO / "README.md").read_text()
        assert script.name in readme, f"{script.name} is not mentioned in README.md"

    def test_readme_refers_to_no_renamed_files(self):
        """The old names were removed; nothing should still point at them."""
        readme = (REPO / "README.md").read_text()
        stale = [
            "keyboard_walk.py", "Multiple-Words-Joiner.py", "dict_compare.py",
            "rules_generator.py", "extract_strings.py", "extract_strings-v0.py",
            "longer-strings.py", "short-strings.py", "Dictionary Manipulation",
        ]
        found = [name for name in stale if name in readme]
        assert not found, f"README.md still refers to removed files: {found}"
