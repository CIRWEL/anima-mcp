#!/usr/bin/env python3
"""Retrain the deployed trajectory-expression student for live EISV semantics.

Run from the anima-mcp repository with the pinned training dependency:

    uv run --with scikit-learn==1.8.0 \
        scripts/retrain_trajectory_student.py \
        --eisv-lumen-root ~/projects/eisv-lumen

The source teacher set predates signed Valence and used cadence-dependent
derivative features. This adapter preserves its expression targets while
renaming the retired shape, recomputing V as E-I, and training only on window
state means. Hash checks make changes to that source contract explicit.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import sys
from pathlib import Path
from typing import Any


FEATURE_CONTRACT_VERSION = 2
NUMERIC_FEATURES = ["mean_E", "mean_I", "mean_S", "mean_V"]
N_ESTIMATORS = 20
MAX_DEPTH = 8
RANDOM_SEED = 42
SOURCE_REVISION = "07494045e01b44ef4ba72084a1c9cd10aef011b5"
SOURCE_HASHES = {
    "eisv_lumen/distillation/train_student.py": (
        "daaa169ba6e13c7e87af9a67fbba0b442d176e8ec3090e2e9233886a12f3c327"
    ),
    "eisv_lumen/distillation/export_student.py": (
        "404f09dcbccf22a52bbb725c1c4c0ad5a4479a3972c1bed2bb6cf33b42f318a3"
    ),
}
TEACHER_OUTPUTS_SHA256 = (
    "5ff53cd7767cbc5169537936eb143cb2d8ecd86c73058169fd7a5c0233fd4d54"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_hash(path: Path, expected: str) -> None:
    actual = _sha256(path)
    if actual != expected:
        raise SystemExit(
            f"source contract mismatch for {path}: expected {expected}, got {actual}"
        )


def _transform_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    transformed = []
    for source in rows:
        row = dict(source)
        if row["shape"] == "void_rising":
            row["shape"] = "valence_rising"
        row["mean_V"] = float(row["mean_E"]) - float(row["mean_I"])
        transformed.append(row)
    return transformed


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--eisv-lumen-root",
        type=Path,
        default=Path.home() / "projects" / "eisv-lumen",
        help="checkout containing the pinned eisv-lumen distillation code",
    )
    parser.add_argument(
        "--teacher-outputs",
        type=Path,
        help="teacher_outputs.json (defaults inside --eisv-lumen-root)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=repo_root / "data" / "student_model",
        help="JSON export destination",
    )
    args = parser.parse_args()

    source_root = args.eisv_lumen_root.expanduser().resolve()
    teacher_outputs = (
        args.teacher_outputs.expanduser().resolve()
        if args.teacher_outputs
        else source_root / "data" / "distillation" / "teacher_outputs.json"
    )
    output = args.output.expanduser().resolve()

    for relative_path, expected_hash in SOURCE_HASHES.items():
        _require_hash(source_root / relative_path, expected_hash)
    _require_hash(teacher_outputs, TEACHER_OUTPUTS_SHA256)

    sys.path.insert(0, str(repo_root / "src"))
    sys.path.insert(0, str(source_root))
    from anima_mcp.eisv.mapping import TrajectoryShape

    current_shapes = sorted(shape.value for shape in TrajectoryShape)
    train_student = importlib.import_module(
        "eisv_lumen.distillation.train_student"
    )
    train_student.NUMERIC_FEATURES[:] = NUMERIC_FEATURES
    train_student.SHAPE_NAMES[:] = current_shapes
    export_student = importlib.import_module(
        "eisv_lumen.distillation.export_student"
    )

    with teacher_outputs.open() as source:
        rows = _transform_rows(json.load(source))
    observed_shapes = {row["shape"] for row in rows}
    if observed_shapes != set(current_shapes):
        raise SystemExit(
            "transformed teacher shapes do not match live classifier: "
            f"expected {current_shapes}, got {sorted(observed_shapes)}"
        )

    models, metrics = train_student.train_student_models(
        rows,
        n_estimators=N_ESTIMATORS,
        max_depth=MAX_DEPTH,
        seed=RANDOM_SEED,
        verbose=True,
    )
    export_student.export_student_to_json(models, str(output))

    mappings_path = output / "mappings.json"
    with mappings_path.open() as source:
        mappings = json.load(source)
    mappings.update({
        "feature_contract_version": FEATURE_CONTRACT_VERSION,
        "sampling_semantics": "window_state_means",
        "valence_semantics": "signed_e_minus_i",
    })
    _write_json(mappings_path, mappings)

    import numpy
    import sklearn

    manifest = {
        "feature_contract_version": FEATURE_CONTRACT_VERSION,
        "metrics": metrics,
        "numeric_features": NUMERIC_FEATURES,
        "source": {
            "repository": "https://github.com/cirwel/eisv-lumen",
            "revision": SOURCE_REVISION,
            "source_files_sha256": SOURCE_HASHES,
            "teacher_outputs_sha256": TEACHER_OUTPUTS_SHA256,
        },
        "training": {
            "max_depth": MAX_DEPTH,
            "n_estimators": N_ESTIMATORS,
            "numpy_version": numpy.__version__,
            "seed": RANDOM_SEED,
            "sklearn_version": sklearn.__version__,
        },
        "transforms": [
            "shape:void_rising->valence_rising",
            "mean_V=mean_E-mean_I",
            "drop_per_second_derivative_features",
        ],
    }
    _write_json(output / "training_manifest.json", manifest)
    print(f"Wrote feature contract v{FEATURE_CONTRACT_VERSION} to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
