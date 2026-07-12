"""A tiny ``.env`` loader (standard library only, no dependencies).

Reads ``KEY=value`` lines from a ``.env`` file into the process environment so
credentials (``BINANCE_API_KEY`` / ``BINANCE_API_SECRET``) can live in a local,
git-ignored file instead of being exported by hand. By default it does **not**
override variables already set in the real environment (the shell wins).

Supported syntax: blank lines and ``#`` comments are ignored; an optional
``export`` prefix is stripped; the value is split on the first ``=``; matching
single or double quotes around the value are removed.
"""

from __future__ import annotations

import os
from typing import Dict, MutableMapping, Optional


def load_dotenv(
    path: str = ".env",
    environ: Optional[MutableMapping[str, str]] = None,
    override: bool = False,
) -> Dict[str, str]:
    """Load ``path`` into ``environ`` (defaults to ``os.environ``).

    Args:
        path: The ``.env`` file to read. A missing file is a no-op.
        environ: Target mapping to populate (defaults to the process environment).
        override: If ``True``, values in the file replace existing variables;
            otherwise existing variables are kept (the default).

    Returns:
        A dict of the keys that were actually set by this call.
    """
    env = os.environ if environ is None else environ
    loaded: Dict[str, str] = {}

    if not os.path.isfile(path):
        return loaded

    with open(path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):].lstrip()
            if "=" not in line:
                continue

            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]

            if not key:
                continue
            if not override and key in env:
                continue

            env[key] = value
            loaded[key] = value

    return loaded
