"""Tests for the schema exporter, the root of the codegen pipeline.

This module sat at 0% coverage through all of Phase 0 while being the thing
every generated artifact descends from. `make codegen` exercised it; pytest
never did, so nothing checked the properties the pipeline depends on -
determinism above all, since `verify.sh` diffs its output and any instability
would surface as drift that is not a contract change.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from codegen.export_schemas import (
    SCHEMA_FILENAME,
    _property_name,
    build_schema,
    main,
    render,
)
from core.contracts import EXPORTED_MODELS

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_property_name_converts_to_snake_case() -> None:
    """Index keys, so they only have to be stable and unique.

    `A2UISurface` becomes `a2_u_i_surface` rather than `a2ui_surface`, because
    the splitter breaks on every capital. Ugly, asserted rather than glossed
    over: these keys are internal to the index object and changing the rule
    would churn every generated artifact for no gain.
    """
    assert _property_name("Evidence") == "evidence"
    assert _property_name("AgentManifest") == "agent_manifest"
    assert _property_name("RootCauseHypothesis") == "root_cause_hypothesis"
    assert _property_name("A2UISurface") == "a2_u_i_surface"


def test_every_exported_model_appears_in_the_index() -> None:
    """Generators need a reachable root, or models in `$defs` emit nothing."""
    schema = build_schema()
    assert schema["type"] == "object"
    assert len(schema["properties"]) == len(EXPORTED_MODELS)

    defs = schema["$defs"]
    for model in EXPORTED_MODELS:
        assert model.__name__ in defs, f"{model.__name__} is not in $defs"


def test_the_index_forbids_additional_properties() -> None:
    """Without this the TypeScript generator adds an index signature."""
    assert build_schema()["additionalProperties"] is False


def test_render_is_deterministic() -> None:
    """verify.sh diffs this output; instability would look exactly like drift."""
    first = render(build_schema())
    second = render(build_schema())
    assert first == second


def test_render_preserves_top_level_order() -> None:
    """render must NOT sort - the banner has to stay at the top of the file.

    Canonical ordering comes from `_deep_sorted`. Sorting again here would push
    `$defs` above the banner, and `$defs` is thousands of lines. This test
    exists because that change was attempted and the generated-artifact guard
    caught it.
    """
    rendered = render({"b": 1, "a": 2})
    assert rendered.startswith('{\n  "b"'), "render reordered its input"
    assert rendered.endswith("\n")


def test_the_banner_is_the_first_thing_in_the_document() -> None:
    """Where a reader will actually see it, before touching anything."""
    head = render(build_schema())[:400].lower()
    assert "generated" in head
    assert "do not edit" in head


def test_nested_mappings_are_canonically_ordered() -> None:
    """Byte-stability comes from _deep_sorted, not from json.dumps."""
    defs = build_schema()["$defs"]
    assert list(defs) == sorted(defs), "$defs is not canonically ordered"

    evidence = build_schema()["$defs"]["Evidence"]["properties"]
    assert list(evidence) == sorted(evidence)


def test_render_round_trips_as_json() -> None:
    parsed: dict[str, Any] = json.loads(render(build_schema()))
    assert parsed["title"] == "PantheonContracts"


def test_discriminated_unions_survive_export() -> None:
    """The evidence and event unions are the pipeline's hardest cases.

    A nullable enum once broke Go generation outright; unions are the shape that
    works, so the export must keep emitting them as `oneOf` with a discriminator.
    """
    defs = build_schema()["$defs"]

    envelope = defs["EventEnvelope"]["properties"]["event"]
    assert "oneOf" in envelope
    assert envelope["discriminator"]["propertyName"] == "type"

    evidence = defs["Evidence"]["properties"]["payload"]
    assert "oneOf" in evidence
    assert evidence["discriminator"]["propertyName"] == "kind"


def test_main_writes_the_schema(tmp_path: Path) -> None:
    assert main(["--output", str(tmp_path)]) == 0
    written = tmp_path / SCHEMA_FILENAME
    assert written.is_file()
    assert json.loads(written.read_text(encoding="utf-8"))["$defs"]


def test_check_passes_against_freshly_written_output(tmp_path: Path) -> None:
    main(["--output", str(tmp_path)])
    assert main(["--output", str(tmp_path), "--check"]) == 0


def test_check_reports_drift_rather_than_raising(tmp_path: Path) -> None:
    """The failure mode that mattered: the drift detector must *report*.

    An earlier version of verify.sh raised instead of reporting, so it had never
    actually worked. Exercised here in both directions.
    """
    target = tmp_path / SCHEMA_FILENAME
    main(["--output", str(tmp_path)])

    target.write_text(
        target.read_text(encoding="utf-8").replace('"title"', '"tampered"', 1), encoding="utf-8"
    )
    assert main(["--output", str(tmp_path), "--check"]) == 1


def test_check_reports_a_missing_file(tmp_path: Path) -> None:
    assert main(["--output", str(tmp_path), "--check"]) == 1


def test_committed_schema_matches_the_contracts() -> None:
    """The committed artifact is current. `make codegen-verify` covers the rest."""
    committed = (REPO_ROOT / "core" / "contracts" / "export" / SCHEMA_FILENAME).read_text(
        encoding="utf-8"
    )
    assert committed == render(build_schema()), "run `make codegen` and commit the result"


@pytest.mark.parametrize("model", EXPORTED_MODELS, ids=lambda m: m.__name__)
def test_each_exported_model_is_closed_in_the_schema(model: type) -> None:
    """Closed models are what stop the TS generator reopening every interface."""
    definition = build_schema()["$defs"][model.__name__]
    assert definition.get("additionalProperties") is False, (
        f"{model.__name__} does not emit additionalProperties: false"
    )
