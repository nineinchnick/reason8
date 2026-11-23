"""Where the repository and the local data directory are.

The data directory defaults to ``data/`` at the repository root and can be overridden with the
``REASON8_DATA_DIR`` environment variable (useful in git worktrees that share one cache).
"""

from __future__ import annotations

import os
from pathlib import Path

#: The checkout this package runs from.
REPO_ROOT = Path(__file__).resolve().parents[1]


def data_dir() -> Path:
    """Root of the local, git-ignored data cache."""
    env = os.environ.get("REASON8_DATA_DIR")
    if env:
        return Path(env)
    return REPO_ROOT / "data"
