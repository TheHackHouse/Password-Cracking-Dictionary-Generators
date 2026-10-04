# Password Cracking Dictionary Generators

A collection of small tools for building targeted password-cracking
dictionaries. They are most useful when you have some idea what the password
is likely to look like — a company name, a site code, a season and a year —
and want to turn that guess into a candidate list.

The generated lists are rarely worth much on their own. The intended use is as
a *base* dictionary that you then attack with hashcat rules.

## Conventions

Every tool follows the same conventions, so they pipe together:

| | |
|---|---|
| `-i`, `--input` | input file; **defaults to stdin** |
| `-o`, `--output` | output file; **defaults to stdout** |
| `-q`, `--quiet` | suppress progress and statistics |
| `--force` | skip the size confirmation prompt (for scripted runs) |

Candidates go to **stdout**; counts, warnings and prompts go to **stderr**.
`tool ... > list.txt` therefore always produces a clean wordlist.

Every generator works out how many candidates it is about to produce *before*
producing any, prints the count and the output size, and asks for confirmation
past 50 million (`--max-candidates` to change, `--force` to skip).

## Install

Nothing to install — they are standalone Python 3.10+ scripts that only need
the `wordlistlib/` directory alongside them.

```sh
gcc -O3 -march=native -o case-permutation case-permutation.c   # optional fast path
pip install -r requirements.txt   # optional: nltk, for dict-compare/dict-extractor
```

`dict-compare.py` and `dict-extractor.py` need a reference word list. They use
`--custom-dict` if you give them one, otherwise the NLTK corpus if `nltk` is
installed, otherwise the system word list at `/usr/share/dict/words`. So
`nltk` is optional.

---

## Generators

### leetspeak-generator.py

Generates leetspeak variations of a phrase.

Substitutions are grouped into levels so the output stays a usable size:

| level | adds |
|---|---|
| 1 | digit swaps: `a→4 e→3 i→1 o→0 s→5` |
| 2 | symbol swaps: `a→@ b→8 c→( g→6 h→# i→! l→1 s→$ t→7 z→2` |
| 3 | multi-character: `d→|) k→|< m→/\/\ u→|_| v→\/ x→><` and more |

Case variants are always included, and `-`, `_`, ` ` are tried for spaces.

```sh
leetspeak-generator.py -i "mega corp" --level 1 -o base.txt
leetspeak-generator.py -i "mega corp" --level 3 --max-subs 2 > base.txt
```

`--max-subs N` is the one to reach for: real leetspeak substitutes one to
three characters, not all of them, and the cap is what keeps the list
realistic as well as small. For `mega corp`: level 1 is 2,592 candidates,
level 3 unrestricted is 20,736, level 3 with `--max-subs 2` is 10,560.

The reported count and output size are exact, not estimates — multi-character
substitutions are measured at their true length.

### case-permutation.py / case-permutation.c

Every distinct combination of upper and lower case for a word. Characters with
no case are left alone, so there are no duplicate lines.

```sh
case-permutation.py -w megacorp -o perms.txt
case-permutation.py -w megacorp --max-upper 2      # at most 2 capitals
case-permutation.py --common -i words.txt          # lower/UPPER/Title/swapped
cat words.txt | case-permutation.py > cased.txt
```

Growth is 2^n in the number of letters, so `--max-upper N` (real passwords are
`Password` or `PassWord`, not `pAsSwOrD`) or `--common` are what make this
practical on anything long.

The C build takes the same flags and produces byte-identical output:

```sh
gcc -O3 -march=native -o case-permutation case-permutation.c
./case-permutation -w megacorp -m 2 -o perms.txt
```

### keyboard-walk.py

Walks along adjacent keys — `1q2w3e`, `qwerty`, `zaqwsx`.

```sh
keyboard-walk.py -l 4 -k qwerty -o walks4.txt
keyboard-walk.py -l 6 -k qwertyshifted2 --force > walks6.txt
```

Layouts: `qwerty`, `qwertyshifted`, `qwertyshifted1`, `qwertyshifted2`,
`dvorak`, `azerty`.

Walk counts grow about 6.6× per character on qwerty (length 4 is 11,900;
length 6 is 515,362; length 8 is roughly 22 million), so check the reported
count before committing to a long run. The count is computed arithmetically
and takes under a millisecond at any length.

### multiple-words-joiner.py

Combines words into candidates, either as orderings of a given set or as a
product across dictionaries.

```sh
# every ordering of the three words
multiple-words-joiner.py -i 'mega,corp,2026' -o list.txt

# every ordering of one, two or three of them
multiple-words-joiner.py -i 'mega,corp,2026' --min-words 1 -o list.txt

# one word from each dictionary, hyphenated, with a trailing !
multiple-words-joiner.py -d names.txt -d years.txt -D '-' -a '!' -o list.txt
```

Repeat `-d` for as many dictionaries as you like. The first is streamed from
disk rather than loaded into memory.

`--prepend` and `--append` are separated from the words by `--delimiter`, so
`-p corp -D -` gives `corp-mega-2025`. Pass `--no-affix-delimiter` to butt
them straight against the words instead.

### swapcase.py

One case transformation applied to every word in a list. The default inverts
each character's case — the "left caps lock on and still used shift" pattern.

```sh
swapcase.py -i dictionary.txt -o swapped.txt
cat dictionary.txt | swapcase.py --mode title > titled.txt
```

Modes: `swap` (default), `upper`, `lower`, `title`, `capitalize`. For *every*
case combination rather than one transformation, use `case-permutation.py`.

---

## Hash joiners

### lm-hash-joiner.py

Rejoins cracked LM hash halves into whole passwords.

```sh
hashcat -m 3000 lm-halves.txt rockyou.txt --potfile-path lm.pot
lm-hash-joiner.py lm.pot lm-hashes.txt --only-cracked --permute-case -m 2 \
  > nt-candidates.txt
hashcat -m 1000 nt-hashes.txt nt-candidates.txt
```

LM is case-insensitive, so everything recovered is uppercase and will not
match the corresponding NT hash as-is — `--permute-case` (or a separate run of
`case-permutation.py`) is what closes that gap. `-m/--max-upper` caps the
expansion; without it a 14-character password becomes 16,384 candidates.

`AAD3B435B51404EE` (an empty second half, i.e. a password under 8 characters)
resolves to an empty string rather than being reported as uncracked.

Accepts hashcat (`<16 hex>:<plain>`) and John (`$LM$<16 hex>:<plain>`) pot
files, and picks the LM field out of dcsync-style lines.

### nt-hash-joiner.py

Maps NT hashes back to plaintexts you have already cracked.

```sh
nt-hash-joiner.py nt.pot domain.ntds --user-pass -o cracked.txt
nt-hash-joiner.py nt.pot domain.ntds --only-cracked > wordlist.txt
```

| flag | output |
|---|---|
| *(none)* | just the plaintext — a wordlist |
| `--user-pass` | `username:plaintext` — the reporting format |
| `--full` | the original line with the NT hash replaced |
| `--only-cracked` | drop entries that are not in the pot file |

Input lines are recognised by shape, so real `secretsdump.py` / NTDS output
(`user:rid:lmhash:nthash:::`) works, as does a file of bare 32-character
hashes. `31D6CFE0...` is reported as `<BLANK_PASSWORD>` rather than as
uncracked, and is kept out of plain wordlist output.

---

## dictionary-manipulation/

Tools for mining an existing set of cracked passwords for the next round.

### extract-strings.py

Splits strings into runs of letters, digits and special characters — the
building blocks of the password set you are looking at.

```sh
extract-strings.py -i cracked.txt --out-dir parts/
extract-strings.py -i cracked.txt --categories letters -o words.txt
cat cracked.txt | extract-strings.py --categories numbers -o - --no-sort
```

Categories: `letters`, `short_letters` (1–2 characters), `numbers`,
`specials`. `--unicode` keeps accented letters as letters instead of treating
them as symbols. Output is sorted and deduplicated unless `--no-sort`.

### dict-extractor.py

Decomposes strings into their component dictionary words plus the leftovers —
`summerbreeze2026` becomes `summer`, `breeze` and `2026`.

```sh
dict-extractor.py -i cracked.txt --known-out words.txt --remaining-out rest.txt
dict-extractor.py -i cracked.txt --custom-dict english.txt --min-word-length 5
```

The matcher prefers the longest word but backtracks when the remainder cannot
be split.

### dict-compare.py

Separates dictionary words from everything else. The leftovers — names, site
codes, product names — are usually the targeted material worth keeping.

```sh
dict-compare.py -i cracked.txt -o not-words.txt
dict-compare.py -i cracked.txt --invert --custom-dict english.txt
```

Both the NLTK corpus and `/usr/share/dict/words` are archaic and have no
names, brands or plurals, so `--custom-dict` with a real cracked-password
corpus gives much better results.

### filter-by-length.py

```sh
filter-by-length.py -i words.txt --max-length 3 -o short.txt
filter-by-length.py -i words.txt --min-length 8 > long.txt
```

### rules-generator.py

Turns a list of strings into hashcat prefix and suffix rules, so a base
dictionary can be decorated with company names, years and site codes.

```sh
rules-generator.py -i tokens.txt -o corp.rule
rules-generator.py -i tokens.txt --suffix-only --no-comments > suffix.rule
hashcat -m 1000 hashes.txt base.txt -r corp.rule
```

hashcat's `^X` *prepends* and rule functions run left to right, so the prefix
rule for `corp` is `^p^r^o^c`. Strings containing whitespace or `#` cannot be
expressed as rule operands and are skipped with a warning
(`--allow-unsafe` to emit them anyway); strings longer than `--max-functions`
(default 31) are skipped because hashcat rejects the resulting rule.

---

## Workflows

**LM → NT.** LM halves crack almost instantly but give you uppercase only:

```sh
hashcat -m 3000 lm.txt rockyou.txt --potfile-path lm.pot
lm-hash-joiner.py lm.pot lm.txt --only-cracked --permute-case -m 3 > cands.txt
hashcat -m 1000 nt.txt cands.txt
```

**Mine what you already cracked.** The passwords you have broken tell you what
the rest look like:

```sh
nt-hash-joiner.py nt.pot domain.ntds --only-cracked > cracked.txt
dict-extractor.py -i cracked.txt --known-out words.txt --remaining-out rest.txt
extract-strings.py -i rest.txt --categories numbers,specials --out-dir parts/
rules-generator.py -i parts/numbers.txt --suffix-only --no-comments > numbers.rule
hashcat -m 1000 nt.txt words.txt -r numbers.rule
```

**Targeted base list for one organisation:**

```sh
multiple-words-joiner.py -i 'mega,corp,2026' --min-words 1 -o base.txt
leetspeak-generator.py -i 'megacorp' --level 2 --max-subs 2 >> base.txt
sort -u base.txt -o base.txt
hashcat -m 1000 nt.txt base.txt -r rules/best64.rule
```

---

## Option reference

Every flag of every tool, generated from `--help`. A test keeps this
section in step with the code, so a new flag that is not documented
here fails CI.

### Generators

**leetspeak-generator.py**

| option | description |
|---|---|
| `-i, --input INPUT` | Input phrase. Prompted for interactively when omitted. |
| `-o, --output OUTPUT` | Output file. Defaults to stdout. |
| `-l, --level {1,2,3}` | Substitution level: 1 digits, 2 +symbols, 3 +multi-character (default: 2). |
| `-m, --max-subs N` | Substitute at most N characters per candidate. Spaces do not count. Without this, every substitutable character is swapped in every combination. |
| `--rules` | Emit a hashcat .rule file of sXY substitutions instead of a wordlist, so the substitutions apply to a whole dictionary rather than one phrase. Multi-character substitutions are not expressible as rules and are skipped. |
| `--no-case` | Do not also vary upper/lower case (substitutions only). |
| `--max-candidates N` | Safety limit before --force is required (default 50,000,000). |
| `-q, --quiet` | Suppress progress and statistics on stderr. |
| `--force` | Skip the size confirmation prompt (for scripted runs). |
| `--min-length N` | Drop candidates shorter than N characters before writing them. |
| `--max-length N` | Drop candidates longer than N characters before writing them. |
| `--skip N` | Skip the first N candidates, like hashcat's -s. Use with --limit to split one job across machines. |
| `--limit N` | Stop after writing N candidates, like hashcat's -l. |
| `--gzip` | Write a gzip stream. hashcat 6.2.4+ reads gzipped wordlists directly. Implied by a .gz output path. |

**case-permutation.py**

| option | description |
|---|---|
| `-w, --word WORD` | A single input word. |
| `-i, --input, -f, --file INPUT` | File of words, one per line. Defaults to stdin when -w is not given. |
| `-o, --output OUTPUT` | Output file. Defaults to stdout. |
| `-m, --max-upper N` | Uppercase at most N characters per candidate. Turns 2^n growth into something manageable for long inputs. |
| `--no-c` | Do not hand off to the compiled case-permutation binary even if one is present. |
| `--rules` | Emit a hashcat .rule file instead of a wordlist. The rules reproduce the same candidates but apply to every word in a dictionary, so a 10k-word list costs 2^n rules rather than 10k x 2^n lines. See --positions. |
| `--positions N` | With --rules, how many character positions to toggle (default: the length of the longest input word). hashcat can address 36 positions. |
| `--common` | Skip the full permutation and emit only lower, UPPER, Capitalised, swapped and Title case. |
| `--max-candidates N` | Safety limit before --force is required (default 50,000,000). |
| `-q, --quiet` | Suppress progress and statistics on stderr. |
| `--force` | Skip the size confirmation prompt (for scripted runs). |
| `--min-length N` | Drop candidates shorter than N characters before writing them. |
| `--max-length N` | Drop candidates longer than N characters before writing them. |
| `--skip N` | Skip the first N candidates, like hashcat's -s. Use with --limit to split one job across machines. |
| `--limit N` | Stop after writing N candidates, like hashcat's -l. |
| `--gzip` | Write a gzip stream. hashcat 6.2.4+ reads gzipped wordlists directly. Implied by a .gz output path. |

**keyboard-walk.py**

| option | description |
|---|---|
| `-l, --length LENGTH` | Length of the walks. |
| `-o, --output OUTPUT` | Output file. Defaults to stdout. |
| `-k, --layout {azerty,dvorak,qwerty,qwertyshifted,qwertyshifted1,qwertyshifted2}` | Keyboard layout (default: qwerty). |
| `--max-candidates N` | Safety limit before --force is required (default 50,000,000). |
| `-q, --quiet` | Suppress progress and statistics on stderr. |
| `--force` | Skip the size confirmation prompt (for scripted runs). |
| `--min-length N` | Drop candidates shorter than N characters before writing them. |
| `--max-length N` | Drop candidates longer than N characters before writing them. |
| `--skip N` | Skip the first N candidates, like hashcat's -s. Use with --limit to split one job across machines. |
| `--limit N` | Stop after writing N candidates, like hashcat's -l. |
| `--gzip` | Write a gzip stream. hashcat 6.2.4+ reads gzipped wordlists directly. Implied by a .gz output path. |

**multiple-words-joiner.py**

| option | description |
|---|---|
| `-i, --input INPUT` | Comma separated list of words, e.g. 'cat,bird,dog'. |
| `-d, --dict FILE` | Dictionary file, one word per line. Repeat for each dictionary. |
| `-o, --output OUTPUT` | Output file. Defaults to stdout. |
| `-D, --delimiter DELIMITER` | String placed between words (default: none). |
| `-p, --prepend PREPEND` | Static string placed at the start of each candidate. It is separated from the first word by --delimiter; use --no-affix-delimiter to butt it straight up against the word. |
| `-a, --append APPEND` | Static string placed at the end of each candidate, separated from the last word by --delimiter. |
| `--no-affix-delimiter` | Concatenate --prepend and --append directly, with no delimiter between them and the words. |
| `--min-words N` | With -i, the fewest words per candidate (default: all of them). |
| `--max-words N` | With -i, the most words per candidate (default: all of them). |
| `--max-candidates N` | Safety limit before --force is required (default 50,000,000). |
| `-q, --quiet` | Suppress progress and statistics on stderr. |
| `--force` | Skip the size confirmation prompt (for scripted runs). |
| `--min-length N` | Drop candidates shorter than N characters before writing them. |
| `--max-length N` | Drop candidates longer than N characters before writing them. |
| `--skip N` | Skip the first N candidates, like hashcat's -s. Use with --limit to split one job across machines. |
| `--limit N` | Stop after writing N candidates, like hashcat's -l. |
| `--gzip` | Write a gzip stream. hashcat 6.2.4+ reads gzipped wordlists directly. Implied by a .gz output path. |

**swapcase.py**

| option | description |
|---|---|
| `-i, --input INPUT` | Input file, one word per line. Defaults to stdin. |
| `-o, --output OUTPUT` | Output file. Defaults to stdout. |
| `-m, --mode {capitalize,lower,swap,title,upper}` | Transformation to apply (default: swap). |
| `--keep-duplicates` | Do not drop candidates that are unchanged duplicates of each other (e.g. two inputs that upper-case to the same string). |
| `-q, --quiet` | Suppress progress and statistics on stderr. |
| `--min-length N` | Drop candidates shorter than N characters before writing them. |
| `--max-length N` | Drop candidates longer than N characters before writing them. |
| `--skip N` | Skip the first N candidates, like hashcat's -s. Use with --limit to split one job across machines. |
| `--limit N` | Stop after writing N candidates, like hashcat's -l. |
| `--gzip` | Write a gzip stream. hashcat 6.2.4+ reads gzipped wordlists directly. Implied by a .gz output path. |

### Hash joiners

**lm-hash-joiner.py**

| option | description |
|---|---|
| `-o, --output OUTPUT` | Output file. Defaults to stdout. |
| `--full` | Prefix each result with the original LM hash (HASH:PLAINTEXT). |
| `--only-cracked` | Omit entries where a half is missing, instead of emitting <HASH_NOT_FOUND>. |
| `--permute-case` | Also emit case permutations of each recovered password. LM is case-insensitive, so this is what makes the output usable against the matching NT hashes. |
| `-m, --max-upper N` | With --permute-case, uppercase at most N characters per candidate. Strongly recommended: without it a 14-character password expands to 16,384 candidates. |
| `-q, --quiet` | Suppress progress and statistics on stderr. |
| `--min-length N` | Drop candidates shorter than N characters before writing them. |
| `--max-length N` | Drop candidates longer than N characters before writing them. |
| `--skip N` | Skip the first N candidates, like hashcat's -s. Use with --limit to split one job across machines. |
| `--limit N` | Stop after writing N candidates, like hashcat's -l. |
| `--gzip` | Write a gzip stream. hashcat 6.2.4+ reads gzipped wordlists directly. Implied by a .gz output path. |

**nt-hash-joiner.py**

| option | description |
|---|---|
| `-o, --output OUTPUT` | Output file. Defaults to stdout. |
| `--full` | Keep the original line structure with the NT hash replaced. |
| `--user-pass` | Emit 'username:plaintext'. Needs a dcsync-style input line. |
| `--only-cracked` | Omit uncracked entries instead of emitting <HASH_NOT_FOUND>. |
| `-q, --quiet` | Suppress progress and statistics on stderr. |
| `--min-length N` | Drop candidates shorter than N characters before writing them. |
| `--max-length N` | Drop candidates longer than N characters before writing them. |
| `--skip N` | Skip the first N candidates, like hashcat's -s. Use with --limit to split one job across machines. |
| `--limit N` | Stop after writing N candidates, like hashcat's -l. |
| `--gzip` | Write a gzip stream. hashcat 6.2.4+ reads gzipped wordlists directly. Implied by a .gz output path. |

### dictionary-manipulation/

**extract-strings.py**

| option | description |
|---|---|
| `-i, --input INPUT` | Input file. Defaults to stdin. |
| `-o, --output OUTPUT` | Write a single category to this file (or stdout with '-'). Requires exactly one --categories entry. |
| `--out-dir OUT_DIR` | Directory for the per-category files (default: current directory). |
| `--categories CATEGORIES` | Comma separated subset of: letters, short_letters, numbers, specials (default: all). 'short_letters' splits runs of 1-2 letters out of 'letters'. |
| `--no-sort` | Leave output in input order instead of sorting and deduplicating. |
| `--unicode` | Treat accented and non-ASCII letters as letters rather than special characters. |
| `-q, --quiet` | Suppress progress and statistics on stderr. |

**dict-extractor.py**

| option | description |
|---|---|
| `-i, --input INPUT` | Input file. Defaults to stdin. |
| `--known-out KNOWN_OUT` | File for the extracted dictionary words (default: known_words.txt). |
| `--remaining-out REMAINING_OUT` | File for everything left over (default: remaining_text.txt). |
| `--custom-dict, --custom_dict CUSTOM_DICT` | Reference word list. Without it the NLTK corpus is used, falling back to the system word list. |
| `--min-word-length N` | Shortest substring treated as a word (default: 4). Lower values match far more aggressively and produce noisier output. |
| `--no-sort` | Leave output in input order instead of sorting and deduplicating. |
| `-q, --quiet` | Suppress progress and statistics on stderr. |

**dict-compare.py**

| option | description |
|---|---|
| `-i, --input INPUT` | Input file. Defaults to stdin. |
| `-o, --output OUTPUT` | Output file. Defaults to stdout. |
| `--custom-dict, --custom_dict CUSTOM_DICT` | Reference word list to compare against. Without it the NLTK corpus is used, falling back to the system word list. |
| `--invert` | Emit the words that ARE in the dictionary rather than the ones that are not. |
| `--split-words` | Treat each whitespace-separated token as a word. By default a whole line is one word, which is what you want for a password list. |
| `-q, --quiet` | Suppress progress and statistics on stderr. |

**filter-by-length.py**

| option | description |
|---|---|
| `-i, --input INPUT` | Input file. Defaults to stdin. |
| `-o, --output OUTPUT` | Output file. Defaults to stdout. |
| `--min-length N` | Shortest length to keep (default: 1). |
| `--max-length N` | Longest length to keep (default: no limit). |
| `--sort` | Sort and deduplicate the output. Requires -o. |
| `-q, --quiet` | Suppress progress and statistics on stderr. |

**rules-generator.py**

| option | description |
|---|---|
| `-i, --input INPUT` | Input file, one string per line. Defaults to stdin. |
| `-o, --output OUTPUT` | Output .rule file. Defaults to stdout. |
| `--prefix-only` | Emit only prefix rules. |
| `--suffix-only` | Emit only suffix rules. |
| `--no-comments` | Omit the '# Prefix Rules' / '# Suffix Rules' headers so the file can be fed straight to hashcat -r without editing. |
| `--keep-duplicates` | Do not drop repeated rules. |
| `--max-functions N` | Skip strings longer than N characters, since hashcat rejects rules with more than N functions (default: 31). |
| `--allow-unsafe` | Emit rules for strings containing whitespace or '#' anyway. hashcat will misparse them; off by default. |
| `-q, --quiet` | Suppress progress and statistics on stderr. |

---

## Development

```sh
pip install -r requirements-dev.txt
pytest -q
ruff check .
```

CI byte-compiles every script, lints, runs the tests on Python 3.10–3.13, and
compiles the C program checking it against the Python one.

## Licence

MIT — see [LICENSE](LICENSE).
