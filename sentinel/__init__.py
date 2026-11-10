"""SAAF Sentinel: reusable hardening checks for SAAF agent repositories.

Two layers:

* ``sentinel.static_checks`` — zero-config AST/regex checks (SEN0xx).
* ``sentinel.contract``      — "hostile model" contract tests driven by a small
  per-repo adapter (CT0xx).

Standard library only, Python 3.11+.
"""

__version__ = "0.1.0"
