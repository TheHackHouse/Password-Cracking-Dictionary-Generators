# Password Cracking Dictionary Generators

Scripts for building targeted wordlists. Use them when you already have a
rough idea of the password (a company name, a site code, a season plus a
year) and need a candidate list built around it.

The output is meant as a base dictionary to run hashcat rules against. On its
own it won't crack much.

## Common options

All the tools share these, so they can be piped together.

| | |
|---|---|
| `-i`, `--input` | input file, stdin if not given |
| `-o`, `--output` | output file, stdout if not given |
| `-q`, `--quiet` | no progress or statistics |
| `--force` | skip the size confirmation prompt |
| `-j`, `--jobs N` | worker processes, `0` for one per CPU core |

Candidates are written to stdout. Counts, warnings and prompts are written to
stderr, so `tool ... > list.txt` gives a clean wordlist.

Generators print the candidate count and output size before they start. Above
50 million candidates they ask for confirmation. Change the threshold with
`--max-candidates` or skip the prompt with `--force`.

Output is UTF-8 with `\n` line endings on all platforms. `-o list.txt` and
`> list.txt` write the same bytes. Input bytes that aren't valid UTF-8 are
passed through unchanged (rockyou and most other big lists contain some).

### Large files

Input given with `-i` is read a line at a time, so it can be bigger than RAM.
Memory use on a 2 GB list was about 25 MB. These cases do hold data in memory:

- `swapcase.py` when dropping duplicates (the default), and `--unique` in the
  hash joiners
- the second and later dictionaries in `multiple-words-joiner.py`
- the reference word list in `dict-compare.py` and `dict-extractor.py`
- words piped to `case-permutation.py` on stdin. It makes two passes, one to
  count and one to generate. With `-i FILE` it reads the file twice instead.

Sorting uses the system `sort -u` if there is one. On Windows without it, the
tools use their own external merge sort. Neither needs the file to fit in
memory.

## Multiple cores

Tools that process a list line by line accept `-j/--jobs N`. `-j 0` uses
every core.

```sh
swapcase.py -i huge.txt --keep-duplicates -j 0 -o swapped.txt
dict-extractor.py -i cracked.txt -j 16 --known-out words.txt --remaining-out rest.txt
keyboard-walk.py -l 9 -j 16 -o walks9.txt
```

Output is identical to a single-process run, byte for byte and in the same
order. `--skip` and `--limit` select the same candidates whatever `--jobs` is
set to.

| tool | what is split across workers |
|---|---|
| `swapcase.py` | the input list (needs `--keep-duplicates`) |
| `filter-by-length.py`, `dict-compare.py`, `extract-strings.py`, `dict-extractor.py` | the input list |
| `nt-hash-joiner.py`, `lm-hash-joiner.py` | the hash file (not with `--unique`) |
| `case-permutation.py` | the word list given with `-i FILE` |
| `multiple-words-joiner.py` | the first dictionary in `-d` mode |
| `keyboard-walk.py` | the walks, grouped by their first few keys |

Notes:

- Use it for large inputs. Each worker takes a fraction of a second to start,
  so a list of a few MB runs faster with one process. On a 2 GB list, 16
  workers were 7 to 16 times faster depending on the tool.
- Output is written by a single process, so disk speed is the ceiling. Above
  about 1 GB/s of output, adding workers makes no difference.
- Memory depends on the number of workers. Expect 30 to 60 MB each. Every
  worker also loads its own copy of the pot file, reference word list or
  extra dictionaries, so a large pot file with 32 workers is held 32 times.
- Jobs that can't be split print a warning and run in one process. That
  covers anything that drops duplicates, `case-permutation.py` reading stdin,
  and a single word or dictionary entry whose output is too big to build in
  memory at once.
- Workers read plain files directly. stdin and `.gz` input is read by one
  process and handed out in blocks, which is slower.
- `keyboard-walk.py --skip N` with `--jobs` doesn't generate the skipped
  walks. It works out where to start.

## Install

There is no install step. These are Python 3.10+ scripts. Keep the
`wordlistlib/` directory next to them.

```sh
gcc -O3 -march=native -o case-permutation case-permutation.c   # optional, faster case permutation
pip install -r requirements.txt   # optional, nltk for dict-compare/dict-extractor
```

`dict-compare.py` and `dict-extractor.py` need a reference word list. They
look for one in this order: `--custom-dict`, the NLTK corpus if `nltk` is
installed, then `/usr/share/dict/words`.

## Generators

### leetspeak-generator.py

Leetspeak variations of a phrase. Substitutions come in three levels:

| level | adds |
|---|---|
| 1 | digit swaps: `a→4 e→3 i→1 o→0 s→5` |
| 2 | symbol swaps: `a→@ b→8 c→( g→6 h→# i→! l→1 s→$ t→7 z→2` |
| 3 | multi-character: `d→|) k→|< m→/\/\ u→|_| v→\/ x→><` and more |

Upper and lower case of each letter are included. Spaces are tried as `-`,
`_` and ` `.

```sh
leetspeak-generator.py -i "mega corp" --level 1 -o base.txt
leetspeak-generator.py -i "mega corp" --level 3 --max-subs 2 > base.txt
```

`--max-subs N` caps how many characters are substituted in one candidate.
People usually swap one to three characters, so a cap of 2 or 3 gives a
smaller and more realistic list. For `mega corp`:

| options | candidates |
|---|---|
| `--level 1` | 2,592 |
| `--level 3` | 20,736 |
| `--level 3 --max-subs 2` | 10,560 |

The count and size printed before the run are exact.

### case-permutation.py / case-permutation.c

Every upper and lower case combination of a word. Digits and symbols are left
as they are, so the output has no duplicate lines.

```sh
case-permutation.py -w megacorp -o perms.txt
case-permutation.py -w megacorp --max-upper 2      # at most 2 capitals
case-permutation.py --common -i words.txt          # lower/UPPER/Title/swapped
cat words.txt | case-permutation.py > cased.txt
```

The number of candidates doubles with every letter. For long words, use
`--max-upper N` to limit how many letters are capitalised, or `--common` to
get only the lower, UPPER, Capitalised, sWAPPED and Title Case forms.

The C version takes the same flags, writes the same output and is faster. If
the compiled binary is next to the script, `case-permutation.py -w` runs it
automatically. Pass `--no-c` to stop that.

```sh
gcc -O3 -march=native -o case-permutation case-permutation.c
./case-permutation -w megacorp -m 2 -o perms.txt
```

### keyboard-walk.py

Sequences of adjacent keys such as `1q2w3e`, `qwerty` and `zaqwsx`.

```sh
keyboard-walk.py -l 4 -k qwerty -o walks4.txt
keyboard-walk.py -l 6 -k qwertyshifted2 --force > walks6.txt
```

Layouts: `qwerty`, `qwertyshifted`, `qwertyshifted1`, `qwertyshifted2`,
`dvorak`, `azerty`.

Adjacency is worked out on a grid where the number row is shifted one key to
the left, so `1` is above `q` and `2` is above `w`. Each key has up to eight
neighbours.

Counts grow about 6.6 times per extra character on qwerty:

| length | walks |
|---|---|
| 4 | 11,844 |
| 6 | 514,286 |
| 8 | 22,570,032 |

Check the count the tool prints before starting a long run.

### multiple-words-joiner.py

Joins words into candidates. With `-i` it writes every ordering of the words
you give it. With `-d` it takes one word from each dictionary.

```sh
# every ordering of the three words
multiple-words-joiner.py -i 'mega,corp,2026' -o list.txt

# every ordering of one, two or three of them
multiple-words-joiner.py -i 'mega,corp,2026' --min-words 1 -o list.txt

# one word from each dictionary, hyphenated, with a trailing !
multiple-words-joiner.py -d names.txt -d years.txt -D '-' -a '!' -o list.txt
```

`-d` can be repeated. The first dictionary is read from disk as it goes and
can be any size, so put the largest one first. The others are loaded into
memory. Duplicate lines in the first dictionary are not removed. Run
`sort -u` on it first if that matters.

`--prepend` and `--append` are joined to the words with `--delimiter`, so
`-p corp -D -` gives `corp-mega-2025`. Add `--no-affix-delimiter` to get
`corpmega-2025`.

### swapcase.py

Applies one case change to every word in a list. The default swaps the case
of each character, which is what you get when someone types with caps lock
on.

```sh
swapcase.py -i dictionary.txt -o swapped.txt
cat dictionary.txt | swapcase.py --mode title > titled.txt
```

Modes: `swap` (default), `upper`, `lower`, `title`, `capitalize`. To get
every case combination of a word, use `case-permutation.py`.

Duplicates are dropped by default, which keeps every distinct output in
memory. For lists larger than RAM, pass `--keep-duplicates` and run `sort -u`
on the result.

## Hash joiners

### lm-hash-joiner.py

Puts cracked LM hash halves back together into full passwords.

```sh
hashcat -m 3000 lm-halves.txt rockyou.txt --potfile-path lm.pot
lm-hash-joiner.py lm.pot lm-hashes.txt --only-cracked --permute-case -m 2 \
  > nt-candidates.txt
hashcat -m 1000 nt-hashes.txt nt-candidates.txt
```

LM uppercases the password before hashing, so everything recovered is
uppercase and won't match the NT hash directly. `--permute-case` writes the
case variants. `-m/--max-upper` limits how many letters are capitalised in
each candidate. Without it a 14-character password produces 16,384
candidates.

The half `AAD3B435B51404EE` is an empty half, meaning the password is shorter
than 8 characters. It resolves to an empty string. If both halves are
`AAD3B435B51404EE`, no LM hash was stored (LM is disabled, or the password is
longer than 14 characters). Those entries are skipped and counted as "no LM
hash stored".

Pot files can be in hashcat format (`<16 hex>:<plain>`) or John format
(`$LM$<16 hex>:<plain>`). The hash file can be bare 32-character hashes or
`secretsdump.py` style lines, where the LM hash is the third field.
`$HEX[...]` plaintexts are decoded. Leading and trailing spaces in a
plaintext are kept. `--unique` writes a password once when several accounts
share it.

### nt-hash-joiner.py

Looks up NT hashes in a pot file and writes the plaintexts.

```sh
nt-hash-joiner.py nt.pot domain.ntds --user-pass -o cracked.txt
nt-hash-joiner.py nt.pot domain.ntds --only-cracked > wordlist.txt
```

| flag | output |
|---|---|
| *(none)* | plaintext only, for use as a wordlist |
| `--user-pass` | `username:plaintext`, for reporting |
| `--full` | the original line with the NT hash replaced |
| `--only-cracked` | leave out entries that are not in the pot file |
| `--unique` | write each distinct line once |

Accepted hash file formats:

- `secretsdump.py` / NTDS lines (`user:rid:lmhash:nthash:::`)
- `user:hash` (the `hashcat --username` format)
- one 32-character hash per line

The empty-password hash `31D6CFE0...` is written as `<BLANK_PASSWORD>` in
`--user-pass` and `--full` output and left out of plain wordlist output.
`$HEX[...]` plaintexts are decoded. Leading and trailing spaces in a
plaintext are kept.

## dictionary-manipulation/

Tools for pulling useful material out of passwords you have already cracked.

### extract-strings.py

Splits each string into runs of letters, digits and special characters, and
writes each type to its own file.

```sh
extract-strings.py -i cracked.txt --out-dir parts/
extract-strings.py -i cracked.txt --categories letters -o words.txt
cat cracked.txt | extract-strings.py --categories numbers -o - --no-sort
```

Categories: `letters`, `short_letters`, `numbers`, `specials`.
`short_letters` is runs of 1 or 2 letters. `--unicode` counts accented
letters as letters. Without it they count as special characters. Output is
sorted and deduplicated unless you pass `--no-sort`.

### dict-extractor.py

Splits strings into dictionary words and whatever is left over.
`summerbreeze2026` puts `summer` and `breeze` in the words file and `2026` in
the leftovers file.

```sh
dict-extractor.py -i cracked.txt --known-out words.txt --remaining-out rest.txt
dict-extractor.py -i cracked.txt --custom-dict english.txt --min-word-length 5
```

It picks the split that covers the most characters with dictionary words,
using the fewest words. Each leftover piece goes on its own line.

### dict-compare.py

Splits a list into dictionary words and non-dictionary words. By default it
writes the non-dictionary ones (names, site codes, product names), which are
usually the more useful for a targeted list. `--invert` writes the dictionary
words.

```sh
dict-compare.py -i cracked.txt -o not-words.txt
dict-compare.py -i cracked.txt --invert --custom-dict english.txt
```

The NLTK corpus and `/usr/share/dict/words` are dated and have no names,
brands or plurals. A word list built from real cracked passwords, passed with
`--custom-dict`, works better.

### filter-by-length.py

Keeps the lines whose length is within a range.

```sh
filter-by-length.py -i words.txt --max-length 3 -o short.txt
filter-by-length.py -i words.txt --min-length 8 > long.txt
```

### rules-generator.py

Converts a list of strings into hashcat prefix and suffix rules. Use it to
add company names, years or site codes to every word in a base dictionary.

```sh
rules-generator.py -i tokens.txt -o corp.rule
rules-generator.py -i tokens.txt --suffix-only --no-comments > suffix.rule
hashcat -m 1000 hashes.txt base.txt -r corp.rule
```

`^X` prepends a character and rules run left to right, so the prefix rule for
`corp` is `^p^r^o^c`.

Strings can contain any printable ASCII character, including spaces and `#`.
Strings with tabs, control characters or non-ASCII characters are skipped
with a warning. Pass `--hex-escape` to write those characters as `\xNN`
bytes, which needs a hashcat version that supports `\xNN` in rules. Strings
that need more than 31 rule functions are skipped because hashcat rejects
them. `--max-functions` changes that limit.

## Workflows

### LM to NT

LM halves crack quickly but only give you the uppercase password.

```sh
hashcat -m 3000 lm.txt rockyou.txt --potfile-path lm.pot
lm-hash-joiner.py lm.pot lm.txt --only-cracked --permute-case -m 3 > cands.txt
hashcat -m 1000 nt.txt cands.txt
```

### Reuse what you have cracked

Cracked passwords show what the remaining ones are likely to look like.

```sh
nt-hash-joiner.py nt.pot domain.ntds --only-cracked > cracked.txt
dict-extractor.py -i cracked.txt --known-out words.txt --remaining-out rest.txt
extract-strings.py -i rest.txt --categories numbers,specials --out-dir parts/
rules-generator.py -i parts/numbers.txt --suffix-only --no-comments > numbers.rule
hashcat -m 1000 nt.txt words.txt -r numbers.rule
```

### Base list for one organisation

```sh
multiple-words-joiner.py -i 'mega,corp,2026' --min-words 1 -o base.txt
leetspeak-generator.py -i 'megacorp' --level 2 --max-subs 2 >> base.txt
sort -u base.txt -o base.txt
hashcat -m 1000 nt.txt base.txt -r rules/best64.rule
```

## Option reference

All flags for each tool, taken from `--help`. A test fails if a flag is
missing from this file.

### Generators

**leetspeak-generator.py**

| option | description |
|---|---|
| `-i, --input INPUT` | Input phrase. Prompted for interactively when omitted. |
| `-o, --output OUTPUT` | Output file. Defaults to stdout. |
| `-l, --level {1,2,3}` | Substitution level: 1 digits, 2 +symbols, 3 +multi-character (default: 2). |
| `-m, --max-subs N` | Substitute at most N characters per candidate. Spaces do not count. Without this, every substitutable character is swapped in every combination. |
| `--rules` | Emit a hashcat .rule file of sXY substitutions instead of a wordlist, so the substitutions apply to a whole dictionary rather than one phrase. With a phrase (-i or stdin) only its letters are covered; without one, every letter is. Multi-character substitutions are not expressible as rules and are skipped. |
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
| `-j, --jobs N` | Worker processes to use (default: 1). 0 means one per CPU core. The output is the same, in the same order, whatever the value. |
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
| `-j, --jobs N` | Worker processes to use (default: 1). 0 means one per CPU core. The output is the same, in the same order, whatever the value. |
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
| `-d, --dict FILE` | Dictionary file, one word per line. Repeat for each dictionary. The first is streamed and may be any size (its duplicate lines are not removed); the others are loaded into memory. |
| `-o, --output OUTPUT` | Output file. Defaults to stdout. |
| `-D, --delimiter DELIMITER` | String placed between words (default: none). |
| `-p, --prepend PREPEND` | Static string placed at the start of each candidate. It is separated from the first word by --delimiter; use --no-affix-delimiter to butt it straight up against the word. |
| `-a, --append APPEND` | Static string placed at the end of each candidate, separated from the last word by --delimiter. |
| `--no-affix-delimiter` | Concatenate --prepend and --append directly, with no delimiter between them and the words. |
| `--min-words N` | With -i, the fewest words per candidate (default: all of them, or 1 when --max-words is given). |
| `--max-words N` | With -i, the most words per candidate (default: all of them). |
| `--max-candidates N` | Safety limit before --force is required (default 50,000,000). |
| `-j, --jobs N` | Worker processes to use (default: 1). 0 means one per CPU core. The output is the same, in the same order, whatever the value. |
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
| `--keep-duplicates` | Do not drop candidates that are duplicates of each other (e.g. two inputs that upper-case to the same string). Dropping them means remembering every distinct output, so use this for lists larger than memory and run sort -u afterwards. |
| `-j, --jobs N` | Worker processes to use (default: 1). 0 means one per CPU core. The output is the same, in the same order, whatever the value. |
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
| `--unique` | Write each distinct line once. Accounts that share a password otherwise repeat it. Holds the distinct lines in memory. |
| `-j, --jobs N` | Worker processes to use (default: 1). 0 means one per CPU core. The output is the same, in the same order, whatever the value. |
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
| `--user-pass` | Emit 'username:plaintext'. Needs input lines that carry a username (dump lines or user:hash). |
| `--only-cracked` | Omit uncracked entries instead of emitting <HASH_NOT_FOUND>. |
| `--unique` | Write each distinct line once. Accounts that share a password otherwise repeat it. Holds the distinct lines in memory. |
| `-j, --jobs N` | Worker processes to use (default: 1). 0 means one per CPU core. The output is the same, in the same order, whatever the value. |
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
| `-j, --jobs N` | Worker processes to use (default: 1). 0 means one per CPU core. The output is the same, in the same order, whatever the value. |
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
| `-j, --jobs N` | Worker processes to use (default: 1). 0 means one per CPU core. The output is the same, in the same order, whatever the value. |
| `-q, --quiet` | Suppress progress and statistics on stderr. |

**dict-compare.py**

| option | description |
|---|---|
| `-i, --input INPUT` | Input file. Defaults to stdin. |
| `-o, --output OUTPUT` | Output file. Defaults to stdout. |
| `--custom-dict, --custom_dict CUSTOM_DICT` | Reference word list to compare against. Without it the NLTK corpus is used, falling back to the system word list. |
| `--invert` | Emit the words that ARE in the dictionary rather than the ones that are not. |
| `--split-words` | Treat each whitespace-separated token as a word. By default a whole line is one word, which is what you want for a password list. |
| `-j, --jobs N` | Worker processes to use (default: 1). 0 means one per CPU core. The output is the same, in the same order, whatever the value. |
| `-q, --quiet` | Suppress progress and statistics on stderr. |

**filter-by-length.py**

| option | description |
|---|---|
| `-i, --input INPUT` | Input file. Defaults to stdin. |
| `-o, --output OUTPUT` | Output file. Defaults to stdout. |
| `--min-length N` | Shortest length to keep (default: 1). |
| `--max-length N` | Longest length to keep (default: no limit). |
| `--sort` | Sort and deduplicate the output. Requires -o. |
| `-j, --jobs N` | Worker processes to use (default: 1). 0 means one per CPU core. The output is the same, in the same order, whatever the value. |
| `-q, --quiet` | Suppress progress and statistics on stderr. |

**rules-generator.py**

| option | description |
|---|---|
| `-i, --input INPUT` | Input file, one string per line. Defaults to stdin. |
| `-o, --output OUTPUT` | Output .rule file. Defaults to stdout. |
| `--prefix-only` | Emit only prefix rules. |
| `--suffix-only` | Emit only suffix rules. |
| `--no-comments` | Omit the '# Prefix Rules' / '# Suffix Rules' header lines. hashcat ignores them either way; this is for tools that do not. |
| `--keep-duplicates` | Do not drop repeated rules. |
| `--max-functions N` | Skip strings that need more than N rule functions, since hashcat rejects longer rules (default: 31). That is one function per character, or per byte for characters written as hex. |
| `--hex-escape, --allow-unsafe` | Emit strings containing tabs, control characters or non-ASCII characters, writing those as \xNN hex bytes. Needs a hashcat version that supports \xNN in rules; off by default, and such strings are skipped. Spaces and '#' never need this. (--allow-unsafe is the old name for this option.) |
| `-q, --quiet` | Suppress progress and statistics on stderr. |

## Development

```sh
pip install -r requirements-dev.txt
pytest -q
ruff check .
```

CI compiles every script, runs ruff and the tests on Python 3.10 to 3.13 on
Linux and Windows, then builds the C program and checks that its output
matches the Python version.

## Licence

MIT. See [LICENSE](LICENSE).
