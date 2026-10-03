"""Shared helpers for the password-cracking dictionary generators.

Every tool in this repository is still runnable on its own; this package only
holds the behaviour that was previously copy-pasted (or missing) across them:

* ``cli``      -- stdin/stdout defaults, stderr logging, sort helpers
* ``estimate`` -- candidate counting, output-size estimation, confirm prompts
* ``caseperm`` -- duplicate-free case permutation, shared by two tools
"""

__all__ = ["cli", "estimate", "caseperm"]
