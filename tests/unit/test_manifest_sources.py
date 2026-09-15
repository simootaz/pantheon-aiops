"""Turning a pull request's files into reviewable before/after pairs.

The tests that matter are the ones about what must NOT happen: a reordered file
reported as a wholesale replacement, a `values.yaml` reviewed as a manifest, and
a file that failed to parse quietly reviewed as unchanged.

Phase: 4 - Delivery Flow
"""

from __future__ import annotations

import base64

import pytest

from agents.manifest_review.sources import (
    Identity,
    UnreadableManifest,
    decode,
    documents,
    extract,
    looks_like_manifest_file,
    pair,
)

DEPLOYMENT = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: checkout
  namespace: shop
spec:
  replicas: 3
"""

SERVICE = """
apiVersion: v1
kind: Service
metadata:
  name: checkout
  namespace: shop
spec:
  ports: [{port: 80}]
"""


def _encoded(text: str) -> dict[str, str]:
    return {"encoding": "base64", "content": base64.b64encode(text.encode()).decode()}


# --- what counts as a manifest ----------------------------------------------------------


def test_a_yaml_file_without_apiversion_and_kind_is_not_a_manifest() -> None:
    """`.gitlab-ci.yml`, a Helm `values.yaml` and a `docker-compose.yml` are all
    YAML and none is a Kubernetes object. Reviewing one as though it were
    produces findings about fields it was never going to have."""
    values = "replicaCount: 3\nimage:\n  tag: v2\n"

    assert documents(values) == []


def test_apiversion_and_kind_together_are_the_test() -> None:
    """The API's own rule, not a heuristic about names."""
    assert documents("kind: Deployment\nmetadata: {name: x}\n") == []
    assert documents("apiVersion: apps/v1\nmetadata: {name: x}\n") == []
    assert len(documents(DEPLOYMENT)) == 1


def test_a_document_with_no_name_is_not_reviewable() -> None:
    """Nothing can be paired across two revisions without an identity, and a
    document paired with the wrong one produces a finding about a change nobody
    made."""
    assert documents("apiVersion: apps/v1\nkind: Deployment\nspec: {replicas: 3}\n") == []


def test_several_documents_in_one_file_are_all_found() -> None:
    """`---` separators are how manifests are normally written."""
    found = documents(f"{DEPLOYMENT}---{SERVICE}")

    assert [document["kind"] for document in found] == ["Deployment", "Service"]


def test_empty_documents_between_separators_are_dropped_not_refused() -> None:
    """A file legitimately holds a trailing `---`, and Helm templates leave
    empty documents behind. That is not a parse failure."""
    assert len(documents(f"---\n{DEPLOYMENT}\n---\n")) == 1


def test_a_python_object_tag_is_refused_rather_than_constructed() -> None:
    """`safe_load_all`, never `load_all`.

    These documents come from a pull request - which is to say, from whoever
    opened it. Full YAML loading constructs arbitrary Python objects from a
    document, so a manifest reviewer using it is a remote code execution
    triggered by opening a PR against the repository it watches.

    The payload here RESOLVES a name rather than calling anything, so the test
    distinguishes the two loaders without running a command either way. The
    plant that swapped in `UnsafeLoader` passed every other test in this file.
    """
    hostile = DEPLOYMENT.replace("  replicas: 3", "  replicas: !!python/name:os.system")

    with pytest.raises(UnreadableManifest, match="not valid YAML"):
        documents(hostile, path="k8s/hostile.yaml")


def test_invalid_yaml_is_reported_rather_than_returned_empty() -> None:
    """A skipped file is a file reviewed as unchanged, and the run comes back
    clean having looked at nothing."""
    with pytest.raises(UnreadableManifest, match="not valid YAML"):
        documents("apiVersion: apps/v1\n  kind: [unclosed\n", path="k8s/broken.yaml")


def test_only_yaml_files_are_worth_opening() -> None:
    """A cheap first pass, so a pull request touching a hundred Go files costs
    no requests."""
    assert looks_like_manifest_file("k8s/base/deploy.yaml")
    assert looks_like_manifest_file("K8S/Deploy.YML")
    assert not looks_like_manifest_file("main.go")


# --- pairing is by identity, never by position -----------------------------------------


def test_reordering_a_file_changes_nothing() -> None:
    """The failure this exists to prevent. Pairing the first document in the old
    file with the first in the new reports a Deployment replaced by a Service
    every time somebody sorts a file - a diff full of enormous findings, none of
    them real."""
    before = documents(f"{DEPLOYMENT}---{SERVICE}")
    after = documents(f"{SERVICE}---{DEPLOYMENT}")

    changes = pair(before, after)

    assert len(changes) == 2
    for change in changes:
        assert change.before == change.after, f"{change.identity} was reported as changed"


def test_a_rename_is_one_removal_and_one_addition() -> None:
    """Which is what it is. Nothing here can tell a rename from a delete plus a
    create, and inventing the link would be inventing an intention."""
    before = documents(DEPLOYMENT)
    after = documents(DEPLOYMENT.replace("name: checkout", "name: checkout-v2"))

    changes = pair(before, after)

    assert len(changes) == 2
    assert {(c.before is None, c.after is None) for c in changes} == {(True, False), (False, True)}


def test_the_same_name_in_two_namespaces_is_two_objects() -> None:
    """`default/checkout` and `staging/checkout` are two objects, and pairing
    them would report every promotion as a change to one workload."""
    staging = documents(DEPLOYMENT.replace("namespace: shop", "namespace: staging"))

    changes = pair(documents(DEPLOYMENT), staging)

    assert len(changes) == 2


def test_an_api_version_migration_is_not_a_replacement() -> None:
    """`apps/v1beta1` to `apps/v1` is the same Deployment moving. Keying on the
    version would report it as one object deleted and another created - the
    loudest possible finding for the most routine possible change."""
    before = documents(DEPLOYMENT.replace("apps/v1", "apps/v1beta1"))

    changes = pair(before, documents(DEPLOYMENT))

    (change,) = changes
    assert change.before is not None and change.after is not None


def test_pairing_is_ordered_so_two_runs_agree() -> None:
    """A caller comparing two runs of this must get the same list - the same
    reason `core/orchestrator/hypotheses.py` sorts its ranking."""
    documents_in = documents(f"{DEPLOYMENT}---{SERVICE}")

    once = [str(change.identity) for change in pair(documents_in, [])]
    twice = [str(change.identity) for change in pair(list(reversed(documents_in)), [])]

    assert once == twice == sorted(once)


def test_an_added_file_has_no_before_and_a_deleted_one_no_after() -> None:
    """What makes a whole-file deletion review as the removal of everything in
    it."""
    added = pair([], documents(DEPLOYMENT))
    deleted = pair(documents(DEPLOYMENT), [])

    assert added[0].before is None and added[0].after is not None
    assert deleted[0].before is not None and deleted[0].after is None


# --- decoding what GitHub sends ------------------------------------------------------------


def test_a_base64_file_is_decoded() -> None:
    assert "kind: Deployment" in decode(_encoded(DEPLOYMENT))


def test_an_encoding_this_reader_does_not_know_is_refused() -> None:
    """Returning empty text would review as "everything was removed"."""
    with pytest.raises(UnreadableManifest, match="does not"):
        decode({"encoding": "none", "content": ""})


def test_undecodable_bytes_are_reported_rather_than_swallowed() -> None:
    with pytest.raises(UnreadableManifest, match="could not decode"):
        decode({"encoding": "base64", "content": base64.b64encode(b"\xff\xfe").decode()})


# --- the whole extraction ---------------------------------------------------------------------


def test_a_changed_file_becomes_one_change_carrying_both_sides() -> None:
    after = DEPLOYMENT.replace("replicas: 3", "replicas: 1")

    extraction = extract([("k8s/deploy.yaml", DEPLOYMENT, after)])

    (change,) = extraction.changes
    assert change.identity == Identity(kind="Deployment", name="checkout", namespace="shop")
    assert change.before is not None and change.before["spec"]["replicas"] == 3
    assert change.after is not None and change.after["spec"]["replicas"] == 1
    assert extraction.complete


def test_a_change_renders_as_the_pair_aegis_reads() -> None:
    """The shape has to match `Aegis.investigate`, or the two halves of this
    pipeline pass their own tests and do not fit together."""
    extraction = extract([("k8s/deploy.yaml", DEPLOYMENT, DEPLOYMENT)])

    assert set(extraction.changes[0].as_pair()) == {"before", "after"}


def test_a_file_that_will_not_parse_is_named_rather_than_skipped() -> None:
    """One bad file in twenty must not cost the review of the other nineteen -
    and a caller that ignores the list is reporting a clean run over files
    nothing read, which is why `complete` exists to be checked."""
    extraction = extract(
        [
            ("k8s/good.yaml", DEPLOYMENT, DEPLOYMENT),
            ("k8s/broken.yaml", "kind: [unclosed\n", "kind: [unclosed\n"),
        ]
    )

    assert extraction.unreadable == ["k8s/broken.yaml"]
    assert not extraction.complete
    assert len(extraction.changes) == 1, "the readable file was still reviewed"


def test_a_pull_request_touching_no_manifests_extracts_nothing() -> None:
    """And that is a clean result, not a failure."""
    extraction = extract([("README.md", "# hi", "# hello")])

    assert extraction.changes == []
    assert extraction.complete
