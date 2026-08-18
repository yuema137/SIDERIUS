"""D14-1 C2a — the pre-relocation TIDMAD parity evidence (capture + compare).

Child design FROZEN rev 2, §5 C2a/C2b and §6: the expected values for the
TIDMAD relocation live in ONE committed, immutable manifest, generated at a
recorded pre-relocation commit. Tests READ that manifest; nothing regenerates
expected values at test runtime — after C2b the compat re-export makes "the
old implementation" the new one, so any old-vs-new runtime comparison would
compare the new code with itself (the self-reference trap #221 caught four
times).

Capture (run ONCE, at the pre-relocation head; the command is recorded in the
manifest itself):

    .venv/bin/python -m tests.helpers.d14_tidmad_parity --write

The evidence grid (child §6):

  * training epoch streams — sha256 over every ``(model_input, target)``
    pair's bytes in dataset iteration order, for the frozen grid
    ``epoch_seed ∈ {5, 6}`` × ``train_portion ∈ {None, 0.5}`` (the
    freeze-subsample distinction IS the seed choice — the call site derives
    ``base_seed`` vs ``base_seed + ep`` before construction, so pinning both
    seeds pins both behaviours);
  * validation-family materialization — row count, per-file ranges, and the
    same content hash;
  * deliverable bytes — sha256 of a ``create_abra_file`` write from
    deterministic arrays through the derived TIDMAD spec.

Fixture identity is pinned too (the generated HDF5 files' hashes): the
two-family fixture is seed-deterministic, so a drifted fixture is detected
as such rather than surfacing as false parity failures.

Scope note (recorded deviation, child ledger C2a): the child's manifest list
named run/scoring record content as a fourth family. Those records are
already golden-pinned by their own suites (REC goldens, the scoring suites,
the #221 serialization oracle), which must pass UNCHANGED through the
relocation — duplicating them here would create a second authority for the
same bytes. The manifest therefore owns exactly the three families above.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = (
    REPO_ROOT / "tests" / "unit" / "execute_tools" / "goldens" / "d14_tidmad_parity_manifest.json"
)

#: The frozen capture grid (child §6). Changing it invalidates the manifest.
EPOCH_SEEDS = (5, 6)
TRAIN_PORTIONS = (None, 0.5)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _dataset_stream_sha(dataset: Any) -> str:
    """sha256 over every (model_input, target) pair, iteration order."""
    h = hashlib.sha256()
    for i in range(len(dataset)):
        model_input, target = dataset[i]
        h.update(model_input.tobytes())
        h.update(target.tobytes())
    return h.hexdigest()


def build_evidence(tmp_dir: Path) -> dict[str, Any]:
    """Compute the full evidence dict against the CURRENT implementation.

    At capture time (pre-relocation commit) this defines the expected values;
    at comparison time (C2b onward) the same function produces the actuals.
    The asymmetry that keeps this honest is WHERE the expected side comes
    from: the committed manifest, never a second runtime call.
    """
    import random

    import numpy as np

    from execute_tools.array2h5 import create_abra_file
    from execute_tools.dataset_config import bind_dataset_profile
    from execute_tools.deliverable_spec import derive_tidmad_deliverable_spec
    from execute_tools.train_engine_sandbox import TIDMADEpochDataset
    from tests.helpers.two_family_profile import write_two_family_fixture

    fx = write_two_family_fixture(tmp_dir)
    evidence: dict[str, Any] = {
        "fixture": {
            "training_files": {
                str(i): _sha256_file(Path(fx.training_path(i))) for i in range(fx.num_files)
            },
            "validation_files": {
                str(i): _sha256_file(Path(fx.validation_path(i))) for i in range(fx.num_files)
            },
        },
        "training_streams": {},
        "validation": {},
        "deliverable": {},
    }

    with bind_dataset_profile(fx.profile):
        sample_set = fx.full_sample_set()
        for seed in EPOCH_SEEDS:
            for portion in TRAIN_PORTIONS:
                ds = TIDMADEpochDataset(
                    data_dir=fx.data_dir,
                    sample_set=sample_set,
                    seg_size=fx.seg_size,
                    train_portion=portion,
                    rng=random.Random(seed),
                    profile=fx.profile,
                )
                key = f"seed={seed}|portion={portion}"
                evidence["training_streams"][key] = {
                    "rows": len(ds),
                    "stream_sha256": _dataset_stream_sha(ds),
                }

        val = TIDMADEpochDataset(
            data_dir=fx.data_dir,
            sample_set=sample_set,
            seg_size=fx.seg_size,
            train_portion=None,
            rng=None,
            profile=fx.profile,
            file_family="validation",
        )
        evidence["validation"] = {
            "rows": len(val),
            "file_row_ranges": {str(k): list(v) for k, v in sorted(val.file_row_ranges.items())},
            "stream_sha256": _dataset_stream_sha(val),
        }

        # Deliverable: deterministic arrays through the derived TIDMAD spec,
        # exactly the writer the relocation moves behind the seam.
        spec = derive_tidmad_deliverable_spec(fx.profile)
        rows = fx.segments_per_file * fx.ml_segs_per_psd
        n = max(rows, 1) * fx.seg_size
        rng = np.random.default_rng(1234)
        storage_np = np.dtype(spec.storage.storage_dtype)
        denoised = rng.integers(0, 255, size=n, dtype=np.uint8).astype(storage_np)
        injected = rng.integers(0, 255, size=n, dtype=np.uint8).astype(storage_np)
        out_path = tmp_dir / "d14_parity_deliverable.h5"
        create_abra_file(str(out_path), denoised, injected, indexed=False, storage=spec.storage)
        evidence["deliverable"] = {
            "n_values": int(n),
            "file_sha256": _sha256_file(out_path),
        }

    return evidence


def write_manifest() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        evidence = build_evidence(Path(td))
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    manifest = {
        "_provenance": {
            "generated_from_commit": head,
            "generation_command": ".venv/bin/python -m tests.helpers.d14_tidmad_parity --write",
            "grid": {"epoch_seeds": list(EPOCH_SEEDS), "train_portions": list(TRAIN_PORTIONS)},
            "immutable": (
                "BYTE-IMMUTABLE for the life of PR D14-1 (child design §5 C2a). "
                "Expected values are READ from this file, never recomputed."
            ),
        },
        "evidence": evidence,
    }
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"wrote {MANIFEST_PATH} from {head}")


def load_manifest() -> dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text())


if __name__ == "__main__":
    if "--write" in sys.argv:
        write_manifest()
    else:
        print(__doc__)
