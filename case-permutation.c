/*
 * case-permutation.c -- the fast twin of case-permutation.py
 *
 * Compile with:
 *     gcc -O3 -march=native -o case-permutation case-permutation.c
 *
 * Usage mirrors the Python tool:
 *     ./case-permutation -w megacorp -o perms.txt
 *     ./case-permutation -w megacorp --max-upper 2
 *     ./case-permutation megacorp perms.txt      (legacy positional form)
 *
 * Statistics and prompts go to stderr, so `./case-permutation -w word > f.txt`
 * always yields a clean wordlist.
 */

#include <ctype.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define MAX_LENGTH 63            /* 63 cased chars is already 2^63 candidates */
#define OUT_BUFSIZ (1 << 20)     /* 1 MB stdio buffer: console streaming was slow */

static void usage(const char *prog) {
    fprintf(stderr,
        "Usage: %s [-w WORD] [-o FILE] [-m N] [--force] [WORD] [FILE]\n"
        "\n"
        "  -w, --word WORD      Word to permute (prompted for if omitted).\n"
        "  -o, --output FILE    Output file. Defaults to stdout.\n"
        "  -m, --max-upper N    Uppercase at most N characters per candidate.\n"
        "      --force          Skip the size confirmation prompt.\n"
        "  -q, --quiet          Suppress statistics on stderr.\n"
        "  -h, --help           Show this message.\n",
        prog);
}

/* Binomial coefficient with overflow clamping. */
static unsigned long long binom(int n, int k) {
    if (k < 0 || k > n) return 0ULL;
    if (k > n - k) k = n - k;
    unsigned long long result = 1ULL;
    for (int i = 1; i <= k; i++) {
        unsigned long long factor = (unsigned long long)(n - k + i);
        if (result > ULLONG_MAX / factor) return 0ULL;  /* overflow */
        result = result * factor / (unsigned long long)i;
    }
    return result;
}

static void human_size(double bytes, char *out, size_t out_len) {
    const char *units[] = {"Bytes", "KB", "MB", "GB", "TB"};
    int unit = 0;
    while (bytes >= 1024.0 && unit < 4) { bytes /= 1024.0; unit++; }
    snprintf(out, out_len, unit == 0 ? "%.0f %s" : "%.2f %s", bytes, units[unit]);
}

int main(int argc, char *argv[]) {
    char word[MAX_LENGTH + 1] = {0};
    const char *output_file = NULL;
    int max_upper = -1;           /* -1 means "no cap" */
    int force = 0;
    int quiet = 0;
    int have_word = 0;

    for (int i = 1; i < argc; i++) {
        const char *arg = argv[i];
        if (!strcmp(arg, "-h") || !strcmp(arg, "--help")) {
            usage(argv[0]);
            return EXIT_SUCCESS;
        } else if (!strcmp(arg, "--force")) {
            force = 1;
        } else if (!strcmp(arg, "-q") || !strcmp(arg, "--quiet")) {
            quiet = 1;
        } else if (!strcmp(arg, "-w") || !strcmp(arg, "--word")) {
            if (++i >= argc) { fprintf(stderr, "error: %s needs a value\n", arg); return EXIT_FAILURE; }
            if (strlen(argv[i]) > MAX_LENGTH) {
                fprintf(stderr, "error: word is %zu characters; the limit is %d\n",
                        strlen(argv[i]), MAX_LENGTH);
                return EXIT_FAILURE;
            }
            strcpy(word, argv[i]);
            have_word = 1;
        } else if (!strcmp(arg, "-o") || !strcmp(arg, "--output")) {
            if (++i >= argc) { fprintf(stderr, "error: %s needs a value\n", arg); return EXIT_FAILURE; }
            output_file = argv[i];
        } else if (!strcmp(arg, "-m") || !strcmp(arg, "--max-upper")) {
            if (++i >= argc) { fprintf(stderr, "error: %s needs a value\n", arg); return EXIT_FAILURE; }
            max_upper = atoi(argv[i]);
            if (max_upper < 0) { fprintf(stderr, "error: --max-upper cannot be negative\n"); return EXIT_FAILURE; }
        } else if (arg[0] == '-' && arg[1] != '\0') {
            fprintf(stderr, "error: unknown option %s\n", arg);
            usage(argv[0]);
            return EXIT_FAILURE;
        } else if (!have_word) {                 /* legacy: ./case-permutation word out.txt */
            if (strlen(arg) > MAX_LENGTH) {
                fprintf(stderr, "error: word is %zu characters; the limit is %d\n",
                        strlen(arg), MAX_LENGTH);
                return EXIT_FAILURE;
            }
            strcpy(word, arg);
            have_word = 1;
        } else if (!output_file) {
            output_file = arg;
        } else {
            fprintf(stderr, "error: unexpected argument %s\n", arg);
            return EXIT_FAILURE;
        }
    }

    if (!have_word) {
        fprintf(stderr, "Please enter the word (up to %d characters): ", MAX_LENGTH);
        if (!fgets(word, sizeof(word), stdin)) {
            fprintf(stderr, "error: could not read input\n");
            return EXIT_FAILURE;
        }
        word[strcspn(word, "\n")] = '\0';
        if (word[0] == '\0') {
            fprintf(stderr, "error: no input provided\n");
            return EXIT_FAILURE;
        }
    }

    int length = (int)strlen(word);

    /* Collect the positions that actually have two case forms. Digits and
       symbols have one, and expanding them would emit duplicate lines. */
    int positions[MAX_LENGTH];
    int cased = 0;
    for (int i = 0; i < length; i++) {
        unsigned char c = (unsigned char)word[i];
        if (tolower(c) != toupper(c)) positions[cased++] = i;
        word[i] = (char)tolower(c);
    }

    unsigned long long total;
    if (max_upper < 0 || max_upper >= cased) {
        max_upper = -1;
        total = (cased >= 63) ? 0ULL : (1ULL << cased);
    } else {
        total = 0ULL;
        for (int k = 0; k <= max_upper; k++) total += binom(cased, k);
    }

    if (total == 0ULL) {
        fprintf(stderr, "error: %d cased characters is too many to enumerate; use --max-upper\n", cased);
        return EXIT_FAILURE;
    }

    if (!quiet) {
        char size_text[32];
        human_size((double)total * (double)(length + 1), size_text, sizeof(size_text));
        fprintf(stderr, "Total permutations: %llu\n", total);
        fprintf(stderr, "Output size: ~%s\n", size_text);
    }

    if (!force && total > 50000000ULL) {
        if (isatty(STDIN_FILENO)) {
            fprintf(stderr, "Do you want to continue? (y/N): ");
            int answer = fgetc(stdin);
            if (answer != 'y' && answer != 'Y') {
                fprintf(stderr, "Aborted.\n");
                return EXIT_SUCCESS;
            }
        } else {
            fprintf(stderr, "error: %llu permutations exceeds the safety limit; re-run with --force\n", total);
            return EXIT_FAILURE;
        }
    }

    FILE *out = stdout;
    if (output_file) {
        out = fopen(output_file, "w");
        if (!out) { perror("error opening output file"); return EXIT_FAILURE; }
    }
    static char outbuf[OUT_BUFSIZ];
    setvbuf(out, outbuf, _IOFBF, sizeof(outbuf));

    /* Candidates are packed into one large block and written in bulk. A
       per-candidate fwrite costs a call plus a memcpy each time, which at
       millions of candidates is a measurable share of the runtime. */
    static char block[OUT_BUFSIZ];
    size_t block_used = 0;
    const size_t record = (size_t)length + 1;
    const size_t block_limit = sizeof(block) - record;
#define EMIT()                                                   \
    do {                                                         \
        if (block_used > block_limit) {                          \
            fwrite(block, 1, block_used, out);                   \
            block_used = 0;                                      \
        }                                                        \
        memcpy(block + block_used, candidate, record);           \
        block_used += record;                                    \
    } while (0)

    /* Iterate over bitmasks instead of recursing. Bit i maps to the cased
       position counted from the RIGHT, so the last character varies fastest
       and the emission order matches itertools.product in the Python twin --
       the two produce byte-identical files. Makes --max-upper a popcount
       test. */
    char candidate[MAX_LENGTH + 2];
    memcpy(candidate, word, (size_t)length);
    candidate[length] = '\n';
    candidate[length + 1] = '\0';

    if (max_upper < 0) {
        /* Unrestricted: walk every bitmask. Bit i maps to the cased position
           counted from the RIGHT, so the last character varies fastest and
           the order matches itertools.product in the Python twin -- the two
           produce byte-identical files. */
        unsigned long long masks = 1ULL << cased;
        for (unsigned long long mask = 0; mask < masks; mask++) {
            for (int i = 0; i < cased; i++) {
                int p = positions[cased - 1 - i];
                candidate[p] = (mask >> i) & 1ULL
                    ? (char)toupper((unsigned char)word[p])
                    : word[p];
            }
            EMIT();
        }
    } else {
        /* Capped: enumerate combinations directly rather than filtering 2^n
           masks by popcount, which is what makes `-m 2` on a long word cheap.
           Order matches itertools.combinations in the Python twin. */
        int idx[MAX_LENGTH];
        for (int k = 0; k <= max_upper; k++) {
            if (k > cased) break;
            for (int i = 0; i < k; i++) idx[i] = i;
            while (1) {
                for (int i = 0; i < cased; i++) candidate[positions[i]] = word[positions[i]];
                for (int i = 0; i < k; i++) {
                    int p = positions[idx[i]];
                    candidate[p] = (char)toupper((unsigned char)word[p]);
                }
                EMIT();

                if (k == 0) break;
                int i = k - 1;
                while (i >= 0 && idx[i] == cased - k + i) i--;
                if (i < 0) break;
                idx[i]++;
                for (int j = i + 1; j < k; j++) idx[j] = idx[j - 1] + 1;
            }
        }
    }

    if (block_used) fwrite(block, 1, block_used, out);
#undef EMIT

    if (out != stdout) {
        fclose(out);
        if (!quiet) fprintf(stderr, "Wrote %llu permutations to %s\n", total, output_file);
    }
    return EXIT_SUCCESS;
}
