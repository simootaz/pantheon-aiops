"""Pantheon HTTP and WebSocket API.

The version is read from installed package metadata, never written down here.
`pyproject.toml` is the single declaration; anything that restates it is a copy
that will eventually disagree with it — as this file did, reporting 0.1.0 from
`/health` while the repository was tagged v0.2.0.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _installed_version

#: The distribution name in pyproject.toml. Metadata is keyed by it.
DISTRIBUTION = "pantheon-aiops"

try:
    __version__ = _installed_version(DISTRIBUTION)
except PackageNotFoundError:  # pragma: no cover - only outside an installed env
    # Deliberately not a plausible version. If this ever reaches a running
    # service it should look obviously wrong rather than pass for a release,
    # and tests/unit/test_version.py asserts the real path resolves.
    __version__ = "0.0.0+not-installed"

__all__ = ["DISTRIBUTION", "__version__"]
