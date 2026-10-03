# Enhancement Plan — Password Cracking Dictionary Generators

> **Status: implemented.** Every item below has been applied. Two details
> changed during implementation:
>
> * The hashcat rule-length cap is **31 functions** (one per character), not
>   the "~15 chars" estimated in 1.3; `rules-generator.py --max-functions`
>   defaults to 31.
> * Several files were renamed for the consistency described in 3.4. Old → new:
>   `Dictionary Manipulation/` → `dictionary-manipulation/`,
>   `keyboard_walk.py` → `keyboard-walk.py`,
>   `Multiple-Words-Joiner.py` → `multiple-words-joiner.py`,
>   `dict_compare.py` → `dict-compare.py`,
>   `rules_generator.py` → `rules-generator.py`,
>   `extract_strings.py` → `extract-strings.py`,
>   `short-strings.py` → `filter-by-length.py`.
>   `extract_strings-v0.py` and `longer-strings.py` were folded into
>   `extract-strings.py` and deleted (2.7).

A review of all 16 utilities (9 Python at repo root + `Dictionary Manipulation/`, 1 C) with
concrete, prioritised suggestions. Findings marked **BUG** were reproduced locally against
Python 3.14.7 on 2026-10-03; everything else is an improvement proposal.

---

## Part 1 — Correctness bugs (fix these first)

These are ordered by impact. Four of them mean a tool currently produces wrong output or no
output at all.

### 1.1 `lm-hash-joiner.py` does not run at all — **BUG (blocker)**

Line 54 contains a typo that makes the file unparseable:

```python
plain_first = pot_dict.get(first_half, <'HASH_NOT_FOUND>')   # <-- angle bracket outside the quote
```

`python3 -m py_compile lm-hash-joiner.py` → `SyntaxError: invalid syntax`. The script has never
been executable in its committed form.

**Fix:** `pot_dict.get(first_half, '<HASH_NOT_FOUND>')` to match the line below it.

**Action:** add a trivial CI step (Part 3.5) so a syntax error can never be committed again.

---

### 1.2 `nt-hash-joiner.py` silently drops every real dcsync line — **BUG (high)**

The dcsync branch tests for the *literal string* `LM` in the third field:

```python
if len(fields) >= 4 and fields[2].upper() == "LM":
```

Real `secretsdump.py` / NTDS output puts the **LM hash value** there, not the word `LM`:

```
CORP\jsmith:1103:aad3b435b51404eeaad3b435b51404ee:31d6cfe0d16ae931b73c59d7e0c089c0:::
                ^^^^^^^^^^^^^^^^ fields[2] is a hash, never "LM"
```

So the branch never fires, the line falls through to the "simple NT file" branch, fails the
`len(nt_hash) != 32` check, and is skipped. Verified: feeding the line above plus a matching pot
entry produces a **1-byte output file** (just the trailing newline) instead of `Password1`.

**Fix:** detect the format structurally rather than by magic string:

```python
HEX32 = re.compile(r'^[0-9a-fA-F]{32}$')
...
if len(fields) >= 4 and HEX32.match(fields[3]):
    nt_hash = fields[3].upper()          # dcsync / NTDS layout
elif HEX32.match(fields[0]):
    nt_hash = fields[0].upper()          # bare NT hash, or `hash:plain` leftovers
else:
    continue
```

**Also worth adding while in this file:**
- Recognise `aad3b435b51404eeaad3b435b51404ee` (empty LM) and `31d6cfe0d16ae931b73c59d7e0c089c0`
  (empty NT) and label them `<BLANK_PASSWORD>` rather than `<HASH_NOT_FOUND>`.
- Keep the username (`fields[0]`) in `--full` output — for a report you nearly always want
  `user:password`, which is currently impossible to get.
- Add `--only-cracked` to suppress `<HASH_NOT_FOUND>` lines, since the current output is
  unusable as a wordlist without a `grep -v` afterwards.

---

### 1.3 `Dictionary Manipulation/rules_generator.py` emits prefix rules in reverse — **BUG (high)**

```python
prefix_rule = ''.join([f'^{char}' for char in line])
```

Hashcat's `^X` function *prepends* X, and rule functions apply left to right. So the generated
rule `^a^b^c` turns `pass` into `cbapass`, not `abcpass`. Every prefix rule this tool has ever
produced is reversed. (Suffix rules using `$X` are correct — `$` appends, so left-to-right order
is already right.)

**Fix:** `''.join(f'^{c}' for c in reversed(line))`

**Also:**
- Characters that are special to hashcat rule syntax (space, `#`, and anything non-printable)
  need escaping or the rule is silently mangled. Emit `^\x20`-style hex escapes, or skip and
  warn on lines containing them.
- Hashcat's default rule-length cap is 31 functions, and each character costs one function,
  so strings longer than 31 characters produce a rule hashcat rejects. Warn or skip.
- Add `--prefix-only` / `--suffix-only`, and `--dedupe`, so the output can be fed straight to
  `-r` without hand-editing out the `# Prefix Rules` section.

---

### 1.4 `case-permutation.py` emits duplicate lines for every non-alpha character — **BUG (medium)**

```python
itertools.product(*((c.upper(), c.lower()) for c in word))
```

For digits and symbols `c.upper() == c.lower()`, so each such character doubles the output with
identical strings. Reproduced:

```
$ python3 case-permutation.py -w "a1"
A1
A1
a1
a1
```

A word like `pa55w0rd!` produces **16× more lines than it should**, all duplicates. The C version
already guards against this (`if (tolower(current) != toupper(current))`) — the Python port
dropped the check.

**Fix:**

```python
def _variants(c):
    lo, up = c.lower(), c.upper()
    return (lo,) if lo == up else (lo, up)

def generate_permutations(word):
    return map(''.join, itertools.product(*(_variants(c) for c in word)))
```

**Also in this file:** `process_word` writes a `Permutations for word: X` header and a blank line
*into the output file*. That makes the output not a wordlist — hashcat will happily try
`Permutations for word: mega` as a candidate. Move the header to stderr, or gate it behind
`--verbose`, and never write it to the output handle.

---

### 1.5 `Dictionary Manipulation/dict-extractor.py` — greedy match with no backtracking — **BUG (medium)**

```python
if longest_word:
    remainder = find_longest_word(...)
    if remainder is not None:
        ...
memo[start] = None
return None
```

If the longest word at a position leads to a dead end, the function gives up instead of retrying
the next-longest candidate. For `catalogue` it will take `catalogue`; but for a string like
`passwordsy` it takes `passwords`, fails on the `y` remainder, and discards the whole line —
even though `password` + `sy` would have been a usable split. The `memo` also caches the `None`,
so the failure propagates.

**Fix:** iterate candidates longest-first and recurse on each until one succeeds:

```python
for end in range(len(string), start + 3, -1):      # longest first, min length 4
    word = string[start:end]
    if word.lower() in english_words:
        remainder = find_longest_word(string, english_words, end, memo)
        if remainder is not None:
            memo[start] = [word] + remainder
            return memo[start]
memo[start] = None
return None
```

**Secondary issues in the same file:**
- `remaining.replace(word, '', 1)` strips the *first* textual occurrence, which may not be the
  one that was matched. Track offsets from the split instead of re-searching the string.
- `words = find_words_in_string(...)` shadows the `from nltk.corpus import words` binding in the
  same scope. It happens to work because `words.words()` is called earlier, but rename the local
  to `found` — this is one refactor away from a confusing `AttributeError`.
- Output paths `known_words.txt` / `remaining_text.txt` are hardcoded into the CWD. Add
  `--known-out` / `--remaining-out`.

---

### 1.6 `keyboard_walk.py` — the confirmation prompt happens after all the work — **BUG (medium, UX)**

```python
walks = keyboard_walks(args.length, args.layout)   # generates EVERYTHING into a list
total_walks = len(walks)
print(f"Total walks to be generated: {total_walks}")
confirm = input("Do you want to proceed with generation? (yes/no): ")
```

The "do you want to proceed?" safety valve fires *after* the memory and CPU have already been
spent. Answering `no` saves only the file write. Measured on qwerty:

| length | walks | time |
|---|---|---|
| 3 | 1,824 | <0.01s |
| 4 | 11,900 | 0.01s |
| 5 | 78,164 | 0.06s |
| 6 | 515,362 | 0.43s |

Growth is ~6.6× per character, so length 8 is ~22M strings held in a Python list (multiple GB of
RSS) before the user is ever asked.

**Fix:** count first, generate second.
- The count is a cheap matrix power: build the adjacency counts per key and multiply, or just
  recurse counting without building strings. Prompt on *that*.
- Then convert `generate_walks` into a generator (`yield` instead of `walks.append`) and stream
  straight to the file. Memory becomes O(length) instead of O(output).

**Performance:** `get_adjacent_keys` rescans the entire layout on every single call — that's an
O(keys) linear search per node of the recursion tree. Precompute `{key: [neighbours]}` once per
layout. Expect roughly an order-of-magnitude speedup, which matters a lot at length 7-8.

**Latent bug:** because `get_adjacent_keys` loops over *all* positions matching a key, a layout
where a character appears twice would merge both neighbourhoods and emit duplicate walks. None of
the six shipped layouts currently have a repeated character, so this is dormant — but it will bite
the first person who adds a layout. Validate layouts for uniqueness at load.

---

### 1.7 `Dictionary Manipulation/extract_strings.py` — no CLI, runs on import — **BUG (low, usability)**

Unlike every other script in the repo, this one has no `argparse` and no `if __name__ ==
"__main__":` guard. It has `input_file = 'input.txt'` hardcoded at module level and calls
`extract_strings(...)` on import, so merely importing it clobbers `letters.txt`, `specials.txt`,
`short_letters.txt` and `numbers.txt` in the CWD.

**Fix:** wrap in `main()` + `argparse` with `--out-dir`, matching the other scripts.

---

## Part 2 — Per-utility enhancements

### 2.1 `leetspeak-generator.py`

The strongest tool in the repo; the suggestions are about control, not correctness.

- **Substitution levels.** Right now every mapping is always on, which is why the README has to
  warn that `mega company` yields 53MB. Add `--level {1,2,3}`:
  - L1: single-char digit-only subs (`a→4`, `e→3`, `i→1`, `o→0`, `s→5`) — the ones that actually
    appear in real passwords
  - L2: + symbol subs (`@ $ ! #`)
  - L3: current behaviour including multi-char (`|_|`, `|)`, `|]`)

  This alone turns an unusable 53MB list into a targeted few-hundred-KB one.
- **`--max-subs N`** — cap how many positions are substituted at once. Real-world leetspeak
  substitutes 1-3 characters, not all of them. Combined with L1 this is the single highest-value
  addition for actual cracking yield.
- **Size estimate is wrong for multi-char substitutions.** `estimate_file_size` uses
  `avg_length = len(input_string)`, but `u→|_|` and `d→|)` make outputs longer than the input.
  Compute the true mean candidate length from the substitution table:
  `sum(len(v) for v in options)/len(options)` per position.
- **Abort threshold.** The confirmation prompt only appears in interactive mode; `-i` mode prints
  the estimate and charges ahead. Add `--max-candidates N` (default e.g. 50M) that refuses in
  both modes unless `--force`, so a typo in a scripted run can't fill a disk.
- **Stats go to stdout** (`print(f"Total permutations: ...")`), which corrupts the wordlist when
  the README's own documented usage is `... > words_here_leet.txt`. Send all status output to
  **stderr**. This is a one-line fix with real impact.
- **Uppercase input is passed through unsubstituted** (the dict is lowercase-keyed). Either
  casefold the input first or document it at the `-i` help string, not just in the README.
- The README's ToDo (more variants from the gamehouse cheat sheet) folds naturally into the
  `--level` work above.

### 2.2 `case-permutation.py` / `case-permutation.c`

Beyond the duplicate bug (1.4) and the header pollution:

- **Guard rails.** 2^n growth with no warning. A 20-character input is 1M candidates; 30 is a
  billion. Print the exact count (`2 ** sum(1 for c in word if c.isalpha())`) and require
  confirmation or `--force` past a threshold.
- **`--max-upper N`** — only permute up to N uppercase characters. Real passwords are
  `Password`, `PassWord`, rarely `pAsSwOrD`. This is the enhancement that makes the tool
  practically useful rather than combinatorially complete.
- **Toggle-case-only mode** — just first-letter-upper, all-upper, all-lower, and title case. For
  most engagements that four-line output beats 2^n.
- **C/Python parity.** The C version takes positional `word outfile`; the Python version takes
  `-w/-f/-o`. The README documents `python case-permutation.py example output.txt`, which the
  current Python script does not accept (it would error on unrecognised positional args). Pick
  one interface and make the README match.
- **C version:** `strncpy(word, argv[1], MAX_LENGTH)` silently truncates input longer than 24
  chars with no warning — the user gets permutations of a word they didn't ask for. Check
  `strlen(argv[1]) > MAX_LENGTH` and error out. Also consider `setvbuf` with a large buffer
  rather than relying on the comment telling users not to stream to console.
- The C version could replace recursion with a counter loop over `2^alpha_count`, which both
  removes the stack depth concern and makes it trivially parallelisable.

### 2.3 `swapcase.py`

- No `main()` / `if __name__` guard — the only root script without one. Wrap it.
- `outfile` is opened inside the `with` block for `infile` but closed after it, and is never
  closed on an exception path. Use `contextlib.ExitStack` or nest the `with`.
- Make `-i` optional and **default to stdin** so it composes in a pipeline:
  `cat base.txt | python3 swapcase.py | hashcat ...`. Same for stdout. This is the natural shape
  for a one-line filter and applies to several scripts here.
- The tool is a strict subset of one hashcat rule (`:` with case toggles). Consider folding it
  into a small `case-tools.py` alongside `case-permutation.py` with modes: `swap`, `upper`,
  `lower`, `title`, `permute`.

### 2.4 `lm-hash-joiner.py` (beyond the syntax fix)

- **Blank half handling.** `AAD3B435B51404EE` is the LM hash of an empty 7-char half. It should
  resolve to `""`, not `<HASH_NOT_FOUND>` — otherwise every password shorter than 8 characters
  comes out as `PASSWOR<HASH_NOT_FOUND>`.
- **Document the real workflow in `--help`.** The docstring explains it well; surface it. The
  pipeline is: crack LM (`-m 3000`) → join halves here → `case-permutation.py` → attack the
  remaining NT hashes. Consider a `--permute-case` flag that pipes directly into that step, since
  LM output is always uppercase and useless against NT without it.
- **Memory:** `"\n".join(results)` materialises the whole output. Stream with a generator and
  write per line.
- **Report stats to stderr:** how many halves resolved, how many missed, how many full passwords
  recovered. That's the number that goes in the report.

### 2.5 `Multiple-Words-Joiner.py`

- **`--dict1/2/3` should be `-d` repeated** (`action='append'`) — the current design caps at
  three dictionaries for no reason and makes the arg list awkward.
- **Dictionaries are fully loaded into memory** before the product. For two 100k-line files
  that's fine; for a rockyou-sized input it is not. Stream the outer dimension and re-read the
  inner ones.
- **No candidate count or warning.** Three 10k-word dictionaries is 10^12 candidates and an
  unbounded write. Print `len(a)*len(b)*len(c)` and confirm, as the other generators do.
- **`-p/--prepend` has no `-a/--append` counterpart.** Add it; also allow a separator between the
  prepend and the first word.
- **`-i` mode only emits full-length permutations.** `itertools.permutations(words, len(words))`
  on `cat,dog,bird` gives six 3-word combinations but never `catdog`. Add `--min-words` /
  `--max-words` and iterate `r` over that range.
- **No deduplication** — repeated words in the input produce identical output lines.
- **`-o` is required**, unlike every other tool here. Default to stdout.

### 2.6 `Dictionary Manipulation/dict_compare.py`

- `nltk.download('words')` runs on **every invocation**, hitting the network even when the corpus
  is already present. Wrap in `try: nltk.data.find('corpora/words') except LookupError: download`.
- Output filename `non_english_words.txt` is hardcoded. Add `-o`, default stdout.
- The header comment says it compares "each word in the file" but the code treats **each line** as
  a single word. Either split on whitespace or fix the comment.
- Add `--invert` to emit the English words instead — equally useful, and it's one line.
- The NLTK `words` corpus is a poor fit for password work (it's archaic and misses names, brands,
  and plurals). Document that `--custom_dict` with a cracked-password corpus gives far better
  results, and consider shipping a small default list so `nltk` becomes optional.

### 2.7 `Dictionary Manipulation/extract_strings.py`, `extract_strings-v0.py`, `longer-strings.py` — consolidate

These three are near-duplicates:

| file | splits into | sorts output | has CLI |
|---|---|---|---|
| `extract_strings.py` | letters / short_letters / numbers / specials | yes | **no** |
| `extract_strings-v0.py` | letters / others | yes | yes |
| `longer-strings.py` | letters / others | no | yes |

`extract_strings-v0.py` and `longer-strings.py` differ only by two `subprocess.run(['sort'...])`
calls. Its own header comment trails off mid-sentence ("`and the `").

**Proposal:** collapse to a single `extract_strings.py` with `--categories
letters,numbers,specials,short` and `--no-sort`, delete the other two, and note the removal in
the README. If the v0 variant is kept for historical reference, move it to an `archive/`
directory so it isn't mistaken for a working alternative.

**While consolidating:**
- `lines = file.readlines()` loads the whole input into memory — iterate the file handle instead.
  These scripts are the ones most likely to be pointed at a multi-GB wordlist.
- Shelling out to `sort -u` makes the scripts Unix-only and spawns a process per output file. For
  inputs that fit in memory, a Python `set` is simpler; for ones that don't, `sort -u` is
  genuinely the right call — so keep it but guard with `shutil.which('sort')` and fall back.
- `[a-zA-Z]` discards accented and non-ASCII characters, which matters for non-English targets
  (note the repo already ships an AZERTY layout). Offer `--unicode` using `str.isalpha()`.

### 2.8 `Dictionary Manipulation/short-strings.py`

- Writes the **unstripped** `line` while testing the **stripped** length, so trailing whitespace
  survives into the output. Write `line.strip() + '\n'`.
- Empty lines pass the `<= 3` test and produce blank entries. Skip them.
- The threshold 3 is hardcoded in the code, the comment, the `--help` text and the final `print`.
  Make it `--max-length N` (default 3) and interpolate it everywhere.
- Pairs naturally with a `--min-length`; at that point this and `longer-strings.py` could become
  one `filter-by-length.py`.

### 2.9 `Dictionary Manipulation/dict-extractor.py` (beyond 1.5)

- Same `nltk.download` on-every-run issue as 2.6.
- The minimum word length of 4 is hardcoded in the middle of the matching condition — promote it
  to `--min-word-length`.
- Worth stating in the README what this is *for*: splitting cracked passwords into their
  component words so you can build a targeted dictionary for the next round. That's a genuinely
  good idea that isn't currently explained anywhere.

---

## Part 3 — Repo-level improvements

### 3.1 Consistent CLI conventions

Across 16 tools there are currently four different conventions: positional args
(`rules_generator.py`, `nt-hash-joiner.py`), short flags (`swapcase.py`, `leetspeak-generator.py`),
long-only flags (`Multiple-Words-Joiner.py --dict1`), and none at all (`extract_strings.py`).

Standardise on:
- `-i/--input` (default stdin), `-o/--output` (default stdout)
- all status/progress/warning output to **stderr**, so `> out.txt` always yields a clean wordlist
- `--force` to bypass size confirmations, so every tool is scriptable
- `-q/--quiet` and consistent exit codes

This is the single change that would most improve the collection — it turns 16 separate scripts
into a toolkit you can pipe together.

### 3.2 Streaming by default

`keyboard_walk.py`, `lm-hash-joiner.py`, `nt-hash-joiner.py`, `extract_strings*.py` and
`longer-strings.py` all build complete lists or `readlines()` the input. Since the stated purpose
is generating multi-GB wordlists, generators + per-line writes should be the default everywhere.

### 3.3 Size estimation as shared behaviour

`leetspeak-generator.py` already has `predict_permutations` / `estimate_file_size` /
`format_file_size`. `case-permutation.py`, `keyboard_walk.py` and `Multiple-Words-Joiner.py` all
need exactly this and have none of it. Extract to a `wordlistlib/estimate.py` (or a single
`common.py`) and reuse. Every generator should print `N candidates, ~X GB` and confirm before
writing.

### 3.4 Missing repo furniture

- **No `LICENSE`** — for a public offensive-security toolkit this is worth adding explicitly.
- **No `requirements.txt`** — `nltk` is an undeclared dependency of two scripts.
- **No `.gitignore`** — `__pycache__/`, `*.txt` outputs, and the compiled `case-permutation`
  binary will all get committed by accident.
- **No tests.** Even a dozen `pytest` cases asserting known-good outputs would have caught 1.1,
  1.3 and 1.4.
- **Consistent filenames.** The repo mixes `snake_case` (`keyboard_walk.py`, `dict_compare.py`),
  `kebab-case` (`lm-hash-joiner.py`, `short-strings.py`) and `Title-Case`
  (`Multiple-Words-Joiner.py`). Also, the directory name `Dictionary Manipulation` contains a
  space, which breaks naive shell usage (`wc -l $(find . -name '*.py')` fails on it — hit while
  writing this review). Renaming to `dictionary-manipulation/` is a small kindness.

### 3.5 Minimal CI

A GitHub Actions job running `python -m compileall .` plus `ruff check` would take ten minutes to
set up and would have caught the committed `SyntaxError` in `lm-hash-joiner.py` at push time.

### 3.6 README gaps

Documented: leetspeak, case-permutation, swapcase, keyboard_walk. **Undocumented: 11 of 16 tools**
— both hash joiners, `Multiple-Words-Joiner.py`, and the entire `Dictionary Manipulation/`
directory.

Also:
- The `case-permutation.py` usage shown (`python case-permutation.py example output.txt`) does not
  match the script's actual `-w/-f/-o` interface.
- Add a short "workflows" section tying tools together, e.g. the LM→NT pipeline from 2.4, and
  "cracked passwords → `dict-extractor.py` → `rules_generator.py` → targeted second round". The
  tools are individually clear but the *combinations* are where the value is, and that knowledge
  currently exists only in the author's head.

---

## Part 4 — Suggested order of work

1. **`lm-hash-joiner.py` syntax error** (1.1) — one character; the tool is dead until it's fixed.
2. **`nt-hash-joiner.py` dcsync detection** (1.2) — silently wrong output against the most common
   real-world input format.
3. **`rules_generator.py` prefix reversal** (1.3) — silently wrong output, and the kind of bug
   that costs an engagement.
4. **`case-permutation.py` duplicates + header pollution** (1.4).
5. **Stats to stderr across all generators** (3.1, partial) — tiny change, immediately makes
   `> file.txt` safe everywhere.
6. **`dict-extractor.py` backtracking** (1.5) and **`keyboard_walk.py` count-then-generate +
   adjacency cache** (1.6).
7. **`.gitignore`, `requirements.txt`, `LICENSE`, compileall CI** (3.4, 3.5).
8. **README coverage for the 11 undocumented tools** (3.6).
9. **High-value features:** leetspeak `--level` / `--max-subs` (2.1) and case-permutation
   `--max-upper` (2.2) — these two most change what the toolkit can realistically do.
10. **Consolidate the three `extract_strings` variants** (2.7) and standardise CLI/streaming
    across the board (3.1, 3.2, 3.3).

Items 1-4 are bug fixes with no design decisions attached and could all land in a single commit.
