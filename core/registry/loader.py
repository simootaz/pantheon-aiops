"""Discovers every `agents/*/manifest.yaml` and validates it into an AgentManifest.

A manifest that does not validate is a broken agent. Finding that out at dispatch
time - halfway through an investigation, with a half-built plan - is strictly
worse than finding out at import, so discovery is eager and validation is fatal.

The registry is the only thing that knows where agents live. Nothing else walks
`agents/`, so adding an agent means adding a directory with a manifest, and
`tests/unit/test_agent_runtime.py` asserts the roster on disk matches the one in
the repository map.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import ValidationError

from core.contracts.manifest import AgentManifest

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENTS_DIR = REPO_ROOT / "agents"

#: Directories under `agents/` that are scaffolding rather than an agent. The
#: leading underscore is the convention and it is load-bearing here.
SCAFFOLDING = ("_",)

MANIFEST_NAME = "manifest.yaml"


class ManifestError(RuntimeError):
    """A manifest is missing, unparseable, or does not satisfy the contract."""


def manifest_paths(root: Path | None = None) -> list[Path]:
    """Every manifest on disk, in a stable order."""
    base = root or AGENTS_DIR
    return sorted(
        path / MANIFEST_NAME
        for path in base.iterdir()
        if path.is_dir()
        and not path.name.startswith(SCAFFOLDING)
        and (path / MANIFEST_NAME).is_file()
    )


def load_manifest(path: Path) -> AgentManifest:
    """Parse and validate one manifest, or say precisely what is wrong with it.

    Pydantic's own error is kept in the message rather than summarised: the
    field path it reports is the fastest way to fix a manifest, and rewording it
    would lose that.
    """
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise ManifestError(f"{path}: not valid YAML: {error}") from error

    if not isinstance(raw, dict):
        raise ManifestError(f"{path}: expected a mapping, found {type(raw).__name__}")

    try:
        manifest = AgentManifest.model_validate(raw)
    except ValidationError as error:
        raise ManifestError(f"{path}: does not satisfy AgentManifest:\n{error}") from error

    if manifest.domain != path.parent.name:
        raise ManifestError(
            f"{path}: declares domain {manifest.domain!r} but lives in "
            f"{path.parent.name!r}. The folder is how the runtime finds the "
            "manifest, so the two cannot disagree."
        )
    return manifest


@lru_cache(maxsize=1)
def load_all() -> dict[str, AgentManifest]:
    """Every agent, keyed by codename. Cached: the roster does not change at runtime.

    Duplicate codenames are fatal rather than last-one-wins, because a duplicate
    means two agents answer to one name and dispatch becomes a coin toss.
    """
    manifests: dict[str, AgentManifest] = {}
    for path in manifest_paths():
        manifest = load_manifest(path)
        if manifest.codename in manifests:
            raise ManifestError(
                f"{path}: codename {manifest.codename!r} is already used by "
                f"agents/{manifests[manifest.codename].domain}/"
            )
        manifests[manifest.codename] = manifest
    return manifests


def for_codename(codename: str) -> AgentManifest:
    """One agent by name, or a message naming the ones that do exist."""
    manifests = load_all()
    if codename not in manifests:
        raise ManifestError(f"no agent named {codename!r}. Known agents: {sorted(manifests)}")
    return manifests[codename]


def for_domain(domain: str) -> AgentManifest:
    """One agent by the folder it lives in, which is how a class finds its own."""
    for manifest in load_all().values():
        if manifest.domain == domain:
            return manifest
    raise ManifestError(
        f"no agent in agents/{domain}/. Known domains: "
        f"{sorted(m.domain for m in load_all().values())}"
    )
