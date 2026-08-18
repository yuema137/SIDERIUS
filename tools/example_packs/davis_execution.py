"""DAVIS EXECUTION-level artifacts (D14-3 C2/C3).

Derives, from the PR0-frozen `sequences.csv` and the SHA-pinned frames:

* ``data/manifests/clips.csv`` — the frozen clip identities
  ``(sequence_name, start_frame, scope)`` from
  `execute_tools.davis_data_path.clip_starts` (the pure rule) over each
  sequence's ON-DISK frame count; scope inherited from the sequence, so
  sequence-disjointness is structural.
* ``data/manifests/execution.json`` — the frozen decode/resize rule in
  machine-readable form + per-clip window probe hashes (every 6th train
  sequence's FIRST clip = 10 probes).
* ``data/manifests/gate2_{train,validation,final}.csv`` — the nested Gate
  subsets: the FIRST clip of every sequence in that scope.

Regenerate::

    .venv/bin/python -m tools.example_packs.davis_execution \
        --data-root /home/klz/Data/DAVIS_2017
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from execute_tools.davis_data_path import (
    CLIP_CAPS,
    CLIPS_MANIFEST_HEADER,
    CONTEXT_FRAMES,
    FRAME_HEIGHT,
    FRAME_WIDTH,
    FUTURE_FRAMES,
    WINDOW_FRAMES,
    DavisClip,
    clip_starts,
    count_sequence_frames,
    load_davis_sequences,
    window_probe_sha256,
)
from tools.example_packs._common import repo_root, write_json, write_text

PACK_DIRNAME = "davis_future_prediction"
MANIFEST_RELDIR = Path("data") / "manifests"
CLIPS_MANIFEST_NAME = "clips.csv"
EXECUTION_MANIFEST_NAME = "execution.json"
#: Probe subset: the first clip of every Nth train sequence.
PROBE_SEQUENCE_STRIDE = 6


def derive_clip_rows(data_root: Path, sequences) -> list[tuple[str, int, str]]:
    """``[(sequence_name, start_frame, scope)]`` sorted (scope, name, start)."""
    rows: list[tuple[str, int, str]] = []
    skipped: list[str] = []
    for row in sequences:
        frames = count_sequence_frames(data_root, row.sequence_name)
        starts = clip_starts(frames, CLIP_CAPS[row.scope])
        if not starts:
            skipped.append(f"{row.sequence_name}({frames} frames)")
        rows.extend((row.sequence_name, start, row.scope) for start in starts)
    if skipped:
        # Never silent: a too-short sequence contributing zero clips is
        # reported to the operator running the generator.
        print(f"[clips] {len(skipped)} sequence(s) shorter than one window: {skipped}")
    return sorted(rows, key=lambda r: (r[2], r[0], r[1]))


def render_clips_csv(rows: list[tuple[str, int, str]]) -> str:
    body = "".join(f"{name},{start},{scope}\n" for name, start, scope in rows)
    return CLIPS_MANIFEST_HEADER + "\n" + body


def first_clip_per_sequence(
    rows: list[tuple[str, int, str]], scope: str
) -> list[tuple[str, int, str]]:
    seen: set[str] = set()
    out: list[tuple[str, int, str]] = []
    for name, start, row_scope in rows:
        if row_scope != scope or name in seen:
            continue
        seen.add(name)
        out.append((name, start, row_scope))
    return out


def build_execution_manifest(data_root: Path, rows: list[tuple[str, int, str]]) -> dict[str, Any]:
    train_firsts = first_clip_per_sequence(rows, "train")
    probes = {
        f"{name}:{start}": window_probe_sha256(
            data_root, DavisClip(sequence_name=name, start_frame=start)
        )
        for name, start, _scope in train_firsts[::PROBE_SEQUENCE_STRIDE]
    }
    return {
        "schema_version": 1,
        "transform": {
            "decode": "PIL.convert('RGB'); no EXIF transpose",
            "interpolation": "bilinear",
            "resize_to": [FRAME_WIDTH, FRAME_HEIGHT],
            "resize_mode": "direct (declared aspect distortion 1.779 -> 1.75; no crop)",
            "normalize": "div255",
            "layout": "CHW per frame; window stacks on a new time axis",
            "dtype": "float32",
            "authority": "execute_tools/davis_data_path.py::decode_frame,load_window",
        },
        "window": {
            "context_frames": CONTEXT_FRAMES,
            "future_frames": FUTURE_FRAMES,
            "window_frames": WINDOW_FRAMES,
            "context_shape": [3, CONTEXT_FRAMES, FRAME_HEIGHT, FRAME_WIDTH],
            "target_shape": [3, FUTURE_FRAMES, FRAME_HEIGHT, FRAME_WIDTH],
        },
        "clip_rule": {
            "caps": CLIP_CAPS,
            "rule": "n=min(cap,L+1) starts round(i*L/(n-1)) over [0,L], L=frames-12; n==1 -> [0]",
            "authority": "execute_tools/davis_data_path.py::clip_starts",
        },
        "probe_hash": "sha256(context.bytes + target.bytes), float32 CHW-stacked",
        "probes": probes,
    }


def write_execution_artifacts(pack_root: Path, data_root: Path) -> dict[str, int]:
    manifest_dir = pack_root / MANIFEST_RELDIR
    sequences = load_davis_sequences(manifest_dir / "sequences.csv")
    rows = derive_clip_rows(data_root, sequences)
    write_text(manifest_dir / CLIPS_MANIFEST_NAME, render_clips_csv(rows))
    written = {CLIPS_MANIFEST_NAME: len(rows)}
    for scope in ("train", "validation", "final"):
        subset = first_clip_per_sequence(rows, scope)
        name = f"gate2_{scope}.csv"
        write_text(manifest_dir / name, render_clips_csv(subset))
        written[name] = len(subset)
    execution = build_execution_manifest(data_root, rows)
    write_json(manifest_dir / EXECUTION_MANIFEST_NAME, execution)
    written[EXECUTION_MANIFEST_NAME] = len(execution["probes"])
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--data-root",
        type=Path,
        required=True,
        help="machine-local DAVIS root (containing DAVIS/JPEGImages/480p)",
    )
    parser.add_argument("--root", type=Path, default=None, help="pack root (default: examples/…)")
    args = parser.parse_args(argv)
    pack_root = args.root or (repo_root() / "examples" / PACK_DIRNAME)
    for name, count in write_execution_artifacts(pack_root, args.data_root.resolve()).items():
        print(f"wrote {name} ({count})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
