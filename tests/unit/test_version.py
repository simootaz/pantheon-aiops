"""One version, declared once, agreed everywhere.

`/health` reported 0.1.0 while the repository was tagged v0.2.0, because the
number was written down in five places and only the tag moved. Copies of a fact
do not stay equal; they only look equal until someone changes one.

`pyproject.toml` is the single declaration. Everything Python reads it back
through package metadata at runtime. The three non-Python manifests cannot do
that, so they are held equal by the guards below instead.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

import json
import re
import subprocess
import tomllib
from importlib.metadata import version as installed_version
from pathlib import Path

import pytest

import api
from tests.mechanism import read_data, read_mechanism

ROOT = Path(__file__).resolve().parents[2]
#: A release tag: v1.2.3, optionally with a pre-release suffix.
TAG = re.compile(r"^v(\d+\.\d+\.\d+.*)$")


def declared_version() -> str:
    """The one place a human writes the version down."""
    parsed = tomllib.loads(read_data(ROOT / "pyproject.toml"))
    version: str = parsed["project"]["version"]
    return version


def tags_at_head() -> list[str]:
    result = subprocess.run(
        ["git", "tag", "--points-at", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(f"git tag failed, so the tag guard cannot run: {result.stderr.strip()}")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


# There is deliberately no test that pyproject.toml agrees with the *installed*
# metadata. `uv run` re-syncs the environment before every invocation, so the two
# cannot disagree under this project's tooling — planting a mismatch simply
# reinstalls and the test goes green. An unfailable guard is worse than no guard,
# so it was removed rather than left as decoration. The loop is closed anyway:
# the API is asserted to read metadata, and /health is asserted against
# pyproject, which forces the middle equality.


def test_the_api_reports_the_installed_package_version() -> None:
    """Behaviour, not a substring: the value must come from metadata.

    Asserting the source file contains no version literal would be satisfied by
    a comment mentioning one. Comparing the imported value against what the
    installed distribution actually reports cannot be.
    """
    assert api.__version__ == installed_version(api.DISTRIBUTION)
    assert api.__version__ != "0.0.0+not-installed", (
        "the package metadata did not resolve, so the API is serving its "
        "not-installed placeholder as if it were a release"
    )


def test_the_health_endpoint_serves_that_same_version() -> None:
    """The endpoint that was wrong. Asserted through the real app."""
    from fastapi.testclient import TestClient

    from api.main import create_app

    with TestClient(create_app()) as client:
        body = client.get("/health").json()

    assert body["version"] == declared_version(), (
        f"/health reports {body['version']!r}, pyproject declares {declared_version()!r}"
    )


def test_every_manifest_that_restates_the_version_agrees() -> None:
    """Helm and the dashboard cannot read Python metadata, so they are checked.

    All three sat at 0.1.0 through the v0.2.0 tag.
    """
    expected = declared_version()

    chart = read_mechanism(ROOT / "deploy/helm/pantheon/Chart.yaml")
    chart_version = re.search(r"^version:\s*(\S+)", chart, re.MULTILINE)
    app_version = re.search(r'^appVersion:\s*"?([^"\s]+)"?', chart, re.MULTILINE)
    assert chart_version and app_version, "Chart.yaml no longer declares both versions"
    assert chart_version.group(1) == expected, (
        f"Chart.yaml version is {chart_version.group(1)}, pyproject declares {expected}"
    )
    assert app_version.group(1) == expected, (
        f"Chart.yaml appVersion is {app_version.group(1)}, pyproject declares {expected}"
    )

    package = json.loads(read_data(ROOT / "dashboard/package.json"))
    assert package["version"] == expected, (
        f"dashboard/package.json is {package['version']}, pyproject declares {expected}"
    )


def test_a_release_tag_on_this_commit_matches_the_declared_version() -> None:
    """The guard that would have caught v0.2.0 being cut over a 0.1.0 tree.

    Only fires when a release tag actually points at HEAD, so ordinary commits
    are unaffected. CI fetches tags (see ci-python.yml) — without that this
    would pass vacuously in exactly the place it needs to work.
    """
    releases = [match.group(1) for tag in tags_at_head() if (match := TAG.match(tag))]
    if not releases:
        return

    expected = declared_version()
    mismatched = [version for version in releases if version != expected]
    assert not mismatched, (
        f"tagged v{mismatched[0]} but the tree declares {expected}. Bump the "
        "version in pyproject.toml and re-run the release step in CONTRIBUTING."
    )


def test_every_python_image_installs_the_project() -> None:
    """An image without distribution metadata serves the placeholder version.

    The dependency stage uses `--no-install-project` on purpose, so dependency
    layers cache independently of source changes. The consequence is that
    nothing installs the project, `importlib.metadata` finds no distribution,
    and `/health` reports `0.0.0+not-installed` from a container that is
    otherwise working perfectly.

    That is not hypothetical: it is what a running container reported until the
    install line was added. The placeholder did its job - it looked obviously
    wrong instead of passing for a release - but only because someone looked.
    """
    docker = ROOT / "deploy" / "docker"
    offenders = []
    for path in sorted(docker.glob("Dockerfile.*")):
        body = read_mechanism(path)
        if "--no-install-project" not in body:
            continue
        if "uv pip install" not in body:
            offenders.append(f"{path.name}: caches deps but never installs the project")
        elif "COPY pyproject.toml README.md LICENSE" not in body:
            offenders.append(f"{path.name}: installs the project without its readme or licence")

    assert not offenders, "images that would serve the not-installed placeholder: " + "; ".join(
        offenders
    )
