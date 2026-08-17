"""Export core/contracts/ to a single JSON Schema document.

This is step one of the codegen pipeline. The emitted schema is the one artifact
both the Go and the TypeScript generators consume, so there is exactly one place
where drift can occur - see docs/adr/0002-codegen-from-json-schema.md.

Output is byte-for-byte deterministic: keys are sorted and indentation is fixed,
because codegen/verify.sh diffs this file and any instability would surface as
phantom drift.

Usage:
    python -m codegen.export_schemas [--output DIR] [--check]

Phase: 0 - Scaffold & Tooling
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from pydantic.json_schema import models_json_schema

from core.contracts import EXPORTED_MODELS

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "core" / "contracts" / "export"
SCHEMA_FILENAME = "pantheon.schema.json"

SCHEMA_TITLE = "PantheonContracts"
SCHEMA_ID = "https://github.com/simootaz/pantheon-aiops/core/contracts/export/pantheon.schema.json"


def _property_name(model_name: str) -> str:
    """Turn a model name into the snake_case key used in the index object."""
    out: list[str] = []
    for index, char in enumerate(model_name):
        if char.isupper() and index > 0:
            out.append("_")
        out.append(char.lower())
    return "".join(out)


def build_schema() -> dict[str, Any]:
    """Build the combined JSON Schema for every exported contract model.

    The document is an index object whose properties point at each top-level
    model. Generators need a reachable root to emit types from; without it they
    would silently produce nothing for models that are only referenced from
    ``$defs``.
    """
    _, definitions = models_json_schema(
        [(model, "serialization") for model in EXPORTED_MODELS],
        ref_template="#/$defs/{model}",
    )

    properties = {
        _property_name(model.__name__): {"$ref": f"#/$defs/{model.__name__}"}
        for model in EXPORTED_MODELS
    }

    # Key order here is deliberate and load-bearing: the banner must sit at the
    # top of the file so the artifact announces itself as generated. Sorting the
    # whole document instead would bury it under `$defs`, which is thousands of
    # lines long. Determinism comes from _deep_sorted plus this fixed order, not
    # from json.dumps(sort_keys=True).
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_ID,
        "title": SCHEMA_TITLE,
        "description": (
            "Generated from core/contracts/ by codegen/export_schemas.py. Do not edit by hand."
        ),
        "type": "object",
        # Without this, TypeScript generators bolt an
        # `[property: string]: unknown` index signature onto the index type.
        "additionalProperties": False,
        "properties": _deep_sorted(properties),
        "$defs": _deep_sorted(definitions.get("$defs", {})),
    }


def _deep_sorted(value: Any) -> Any:
    """Recursively sort every mapping's keys, leaving list order intact.

    Gives byte-stable output without needing json.dumps(sort_keys=True), which
    would also reorder the top-level document and bury the generated banner.
    """
    if isinstance(value, dict):
        return {key: _deep_sorted(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_deep_sorted(item) for item in value]
    return value


def _display_path(path: Path) -> str:
    """Repo-relative when possible, absolute otherwise.

    codegen/verify.sh writes into a temp directory outside the repo, so this
    must not assume the target is under REPO_ROOT.
    """
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def render(schema: dict[str, Any]) -> str:
    """Serialise with a trailing newline, preserving the order given.

    Deliberately **not** `sort_keys=True`. Canonical ordering already comes from
    `_deep_sorted`, which sorts every nested mapping; sorting here as well would
    also reorder the top-level document and bury the generated banner beneath
    `$defs`, which runs to thousands of lines. A generated artifact that
    announces itself only halfway down is one a reader has already begun
    editing - and `test_generated_artifacts_declare_they_are_generated` fails if
    that happens.
    """
    return json.dumps(schema, indent=2, sort_keys=False, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Write the schema, or check the committed copy against a fresh build."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory to write the schema into.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if the committed schema differs from a fresh build.",
    )
    args = parser.parse_args(argv)

    rendered = render(build_schema())
    target: Path = args.output / SCHEMA_FILENAME

    if args.check:
        if not target.is_file():
            print(f"missing: {target}", file=sys.stderr)
            return 1
        if target.read_text(encoding="utf-8") != rendered:
            print(f"drift: {target} differs from core/contracts/", file=sys.stderr)
            return 1
        return 0

    args.output.mkdir(parents=True, exist_ok=True)
    target.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"wrote {_display_path(target)} ({len(EXPORTED_MODELS)} top-level models)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
