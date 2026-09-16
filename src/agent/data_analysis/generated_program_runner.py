"""Dependency-light in-sandbox ABI runner for untrusted generated analysis."""

from __future__ import annotations

import argparse
import importlib.util
import json
import random
from pathlib import Path
from types import MappingProxyType

import numpy as np


def _load_analyze(source_path: Path):
    spec = importlib.util.spec_from_file_location("generated_analysis_program", source_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("generated analysis source could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    analyze = getattr(module, "analyze", None)
    if not callable(analyze):
        raise TypeError("generated analysis source does not expose analyze")
    return analyze


def _load_inputs(raw_inputs: dict) -> MappingProxyType:
    loaded = {}
    for binding_id, item in raw_inputs.items():
        path = Path(item["path"])
        with np.load(path, allow_pickle=False) as archive:
            arrays = {}
            for name in archive.files:
                value = np.asarray(archive[name])
                if value.dtype.hasobject:
                    raise ValueError("object-dtype materialized arrays are forbidden")
                value.setflags(write=False)
                arrays[name] = value
        loaded[binding_id] = MappingProxyType(
            {
                "descriptor": MappingProxyType(
                    {key: value for key, value in item.items() if key != "path"}
                ),
                "arrays": MappingProxyType(arrays),
            }
        )
    return MappingProxyType(loaded)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--request", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    request = json.loads(Path(args.request).read_text(encoding="utf-8"))
    if request["determinism"] == "deterministic":
        seed = request["seed"]
        random.seed(seed)
        np.random.seed(seed)
    analyze = _load_analyze(Path(args.source))
    payload = analyze(
        _load_inputs(request["inputs"]),
        request["parameters"],
        request["output_directory"],
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
