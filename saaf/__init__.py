import sys

if sys.version_info < (3, 12):
    raise SystemExit(f"SAAF requires Python 3.12 or newer; this is Python {sys.version.split()[0]}.")
