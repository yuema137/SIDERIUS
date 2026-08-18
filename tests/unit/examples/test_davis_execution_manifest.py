"""DAVIS clip/execution manifests + window transform (D14-3 C2/C3).

PIN — the committed artifacts are byte-immutable for the PR.
STRUCTURE — clips obey the frozen rule per sequence, scopes are disjoint at
the SEQUENCE level (the leakage guard), gate subsets are strict nested
first-clip-per-sequence subsets.
TRANSFORM — the frozen decode/resize/window rule on SYNTHETIC frames
(portable), and the committed probe hashes reproduced in a SECOND process
where the machine-local dataset exists.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import pytest
import torch
from PIL import Image

from execute_tools.davis_data_path import (
    CLIP_CAPS,
    CONTEXT_FRAMES,
    FRAME_HEIGHT,
    FRAME_WIDTH,
    FUTURE_FRAMES,
    WINDOW_FRAMES,
    DavisClip,
    clip_starts,
    decode_frame,
    load_davis_clips,
    load_davis_sequences,
    load_window,
    window_probe_sha256,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFESTS = REPO_ROOT / "examples" / "davis_future_prediction" / "data" / "manifests"
DATA_DIR_ENV = "SIDERIUS_DAVIS_DATA_DIR"

#: BYTE-IMMUTABLE pins for the life of PR D14-3.
PINNED = {
    "clips.csv": "0d0e3eab8a093b7b3313a91512442ed7ad97bc244f300628858a7fba229829d2",
    "execution.json": "14436b87bdee5aedf5a8c694059c9aaf8d82a1819e799993068d4f3e966f4c23",
    "gate2_train.csv": "18853f8384dd2e925802b64cc49df94c07f942e08b1ebc7472b5082618e6bfff",
    "gate2_validation.csv": "6b3b658dbcae61fdec0763578de6fd8a2704a6e29c74f73faa9e30f23e0ba9d1",
    "gate2_final.csv": "31cd94337240f25b4d1088e6706efc419f4f9a3f7c46b20b52e86c923d762c7f",
}


def _data_root() -> Path | None:
    value = os.environ.get(DATA_DIR_ENV)
    if value is None:
        default = Path("/home/klz/Data/DAVIS_2017")
        return default if (default / "DAVIS" / "JPEGImages" / "480p").is_dir() else None
    root = Path(value)
    if not (root / "DAVIS" / "JPEGImages" / "480p").is_dir():
        pytest.fail(f"{DATA_DIR_ENV}={value} is set but has no DAVIS/JPEGImages/480p")
    return root


class TestPins:
    @pytest.mark.parametrize("name", sorted(PINNED))
    def test_committed_artifact_matches_pin(self, name):
        digest = hashlib.sha256((MANIFESTS / name).read_bytes()).hexdigest()
        assert digest == PINNED[name], f"{name} drifted from its committed pin"


class TestClipManifest:
    def test_counts_match_the_frozen_caps_over_the_frozen_sequences(self):
        """60 train x 8 + 15 validation x 4 + 15 final x 4 = 600 — every
        sequence is long enough for its cap, so any drift (a lost sequence,
        a changed cap, a short-sequence skip) changes this count."""
        clips = load_davis_clips(MANIFESTS / "clips.csv")
        by_scope: dict[str, list[DavisClip]] = defaultdict(list)
        for scope in ("train", "validation", "final"):
            by_scope[scope] = list(load_davis_clips(MANIFESTS / "clips.csv", scope=scope))
        assert len(clips) == 600
        assert len(by_scope["train"]) == 60 * CLIP_CAPS["train"]
        assert len(by_scope["validation"]) == 15 * CLIP_CAPS["validation"]
        assert len(by_scope["final"]) == 15 * CLIP_CAPS["final"]

    def test_sequences_are_scope_disjoint_and_match_the_frozen_split(self):
        """THE leakage guard at manifest level: a sequence appears under
        exactly one scope, and the scope it appears under is the PR0-frozen
        one."""
        sequences = {
            r.sequence_name: r.scope for r in load_davis_sequences(MANIFESTS / "sequences.csv")
        }
        seen: dict[str, set[str]] = defaultdict(set)
        text = (MANIFESTS / "clips.csv").read_text(encoding="utf-8").splitlines()[1:]
        for line in text:
            name, _start, scope = line.split(",")
            seen[name].add(scope)
        for name, scopes in seen.items():
            assert scopes == {sequences[name]}, f"{name} crosses scopes: {scopes}"
        assert set(seen) == set(sequences)

    @pytest.mark.parametrize("scope", ["train", "validation", "final"])
    def test_each_sequence_obeys_the_pure_rule_for_its_cap(self, scope):
        """Re-derivation: for every sequence, the committed starts equal
        clip_starts(frames_implied, cap). frames_implied is recovered from
        the LAST start (L = last start when n > 1), so this holds without
        touching the dataset."""
        rows = load_davis_clips(MANIFESTS / "clips.csv", scope=scope)
        per_sequence: dict[str, list[int]] = defaultdict(list)
        for clip in rows:
            per_sequence[clip.sequence_name].append(clip.start_frame)
        cap = CLIP_CAPS[scope]
        for name, starts in per_sequence.items():
            assert starts == sorted(starts), name
            implied_frames = starts[-1] + WINDOW_FRAMES
            assert tuple(starts) == clip_starts(implied_frames, cap), name

    @pytest.mark.parametrize("scope", ["train", "validation", "final"])
    def test_gate_subset_is_the_first_clip_of_every_sequence(self, scope):
        parent = load_davis_clips(MANIFESTS / "clips.csv", scope=scope)
        subset = load_davis_clips(MANIFESTS / f"gate2_{scope}.csv", scope=scope)
        expected_sequences = sorted({c.sequence_name for c in parent})
        assert [c.sequence_name for c in subset] == expected_sequences
        assert all(c.start_frame == 0 for c in subset), "first clip is always start 0"
        assert set(subset) <= set(parent)


def _synthetic_sequence(root: Path, name: str, frames: int) -> None:
    seq = root / "DAVIS" / "JPEGImages" / "480p" / name
    seq.mkdir(parents=True, exist_ok=True)
    for i in range(frames):
        Image.new("RGB", (854, 480), (i % 255, 40, 80)).save(seq / f"{i:05d}.jpg", "JPEG")


class TestFrozenTransformSynthetic:
    def test_frame_shape_dtype_range(self, tmp_path):
        _synthetic_sequence(tmp_path, "seq", 1)
        t = decode_frame(tmp_path / "DAVIS" / "JPEGImages" / "480p" / "seq" / "00000.jpg")
        assert t.shape == (3, FRAME_HEIGHT, FRAME_WIDTH) and t.dtype == torch.float32
        assert 0.0 <= float(t.min()) and float(t.max()) <= 1.0

    def test_window_splits_context_and_target_at_the_frozen_boundary(self, tmp_path):
        _synthetic_sequence(tmp_path, "seq", WINDOW_FRAMES)
        context, target = load_window(tmp_path, DavisClip(sequence_name="seq", start_frame=0))
        assert context.shape == (3, CONTEXT_FRAMES, FRAME_HEIGHT, FRAME_WIDTH)
        assert target.shape == (3, FUTURE_FRAMES, FRAME_HEIGHT, FRAME_WIDTH)
        # EXACT identity, no tolerance: every window slice must equal the
        # independently decoded frame at that index — which pins the 8|4
        # split and the ordering at once (JPEG lossiness cancels because
        # both sides decode the same bytes through the same rule).
        frames_dir = tmp_path / "DAVIS" / "JPEGImages" / "480p" / "seq"
        for i in range(CONTEXT_FRAMES):
            assert torch.equal(context[:, i], decode_frame(frames_dir / f"{i:05d}.jpg")), i
        for j in range(FUTURE_FRAMES):
            index = CONTEXT_FRAMES + j
            assert torch.equal(target[:, j], decode_frame(frames_dir / f"{index:05d}.jpg")), j

    def test_missing_frame_fails_closed(self, tmp_path):
        _synthetic_sequence(tmp_path, "seq", 5)  # shorter than a window
        with pytest.raises(FileNotFoundError, match="materialize exactly"):
            load_window(tmp_path, DavisClip(sequence_name="seq", start_frame=0))


class TestRealProbeParity:
    @pytest.fixture()
    def data_root(self) -> Path:
        root = _data_root()
        if root is None:
            pytest.skip(f"real DAVIS frames not present (set {DATA_DIR_ENV})")
        return root

    def test_committed_probes_reproduce_in_this_process(self, data_root):
        probes = json.loads((MANIFESTS / "execution.json").read_text(encoding="utf-8"))["probes"]
        for key, expected in list(probes.items())[:3]:
            name, start = key.rsplit(":", 1)
            clip = DavisClip(sequence_name=name, start_frame=int(start))
            assert window_probe_sha256(data_root, clip) == expected

    def test_committed_probes_reproduce_in_a_second_process(self, data_root):
        probes = json.loads((MANIFESTS / "execution.json").read_text(encoding="utf-8"))["probes"]
        key, expected = next(iter(probes.items()))
        name, start = key.rsplit(":", 1)
        code = (
            "from execute_tools.davis_data_path import DavisClip, window_probe_sha256;"
            f"print(window_probe_sha256({str(data_root)!r}, "
            f"DavisClip(sequence_name={name!r}, start_frame={int(start)})))"
        )
        out = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, cwd=REPO_ROOT
        )
        assert out.returncode == 0, out.stderr[-800:]
        assert out.stdout.strip().splitlines()[-1] == expected
