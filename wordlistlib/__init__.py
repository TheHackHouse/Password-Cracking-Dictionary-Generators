"""Shared helpers for the password-cracking dictionary generators.

Every tool in this repository is still runnable on its own; this package only
holds the behaviour that was previously copy-pasted (or missing) across them:

* ``cli``      -- stdin/stdout defaults, stderr logging, sort helpers
* ``estimate`` -- candidate counting, output-size estimation, confirm prompts
* ``caseperm`` -- duplicate-free case permutation, shared by two tools
* ``parallel`` -- --jobs: the same output, in the same order, on many cores
* ``vocab``    -- the reference word list for the dictionary tools
"""

__all__ = ["cli", "estimate", "caseperm", "parallel", "vocab"]
