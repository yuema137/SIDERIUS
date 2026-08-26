#!/usr/bin/env python
"""GPU-C co-residency probe — the per-leg training driver + result assembler.

Part of the arXiv launch-topology calibration (author ruling 2026-08-25):
the H100 campaign runs FOUR co-resident band chains per card, and every
watchdog / time-budget setting carries a 4-way co-residency factor that
must be MEASURED on the campaign card (the 1.85-2.13x pairwise RTX 5090
figure is a stale lower bound). ``gpu_c_coresidency_probe.sh`` is the
orchestrator; this file is its two mechanical halves:

``leg``
    Run ONE minimal REAL training workload on one band and time it. This
    is deliberately the zero-LLM half of ``scripts/run_comparison.py``'s
    Phase 1 baseline-trial path (``run_baseline_trial``): the paper-spec
    config from ``ml_models/legacy_baseline_configs.json``, ``epochs=1``,
    a snapshot SampleSet over the band's DataScope, executed through the
    REAL ``TidmadSandbox.execute_training`` subprocess on real TIDMAD
    data. No LLM, no inference, no scoring — the probe is resource
    calibration, and scores are explicitly out of scope. A background
    thread samples the leg's own process tree every few seconds and
    records the peak host anon-RSS (VmRSS sum) and peak device memory
    (``nvidia-smi --query-compute-apps`` rows owned by the tree).

``assemble``
    Read the solo-leg and quad-leg JSONs plus the orchestrator's host
    MemAvailable samples and write ``gpu_c_probe_result.json`` — per-leg
    wall times, the derived 4-way ``coresidency_factor`` (quad wall of
    the MATCHED band divided by its solo wall, so different band sizes
    never skew the ratio), per-chain VRAM peaks and host-RAM evidence —
    plus a human summary on stdout. The factor is what the operator
    copies into ``h100_posture.env`` (``H100_CORESIDENCY_FACTOR``) with
    a posture version bump.

Portability: the repository root is derived from this file's location
(never hardcoded), so the driver runs from any checkout path.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

#: The four campaign bands (must stay in step with the band launcher's map;
#: an unknown band is refused here exactly as it is there).
CAMPAIGN_BANDS = ("0-3", "4-9", "10-14", "15-19")

#: The matched band: the solo reference leg and the quad-leg chain whose
#: ratio defines the factor. One band compared against ITSELF, so the four
#: bands' different file counts cannot skew the ratio.
REFERENCE_BAND = "0-3"

LEGACY_CONFIGS_PATH = REPO_ROOT / "ml_models" / "legacy_baseline_configs.json"


# ---------------------------------------------------------------------------
# Process-tree sampling (leg mode)
# ---------------------------------------------------------------------------


def _descendant_pids(root_pid: int) -> set[int]:
    """The root's live descendant set, from one /proc scan (children incl.
    the sandbox's real training subprocess)."""
    ppid_of: dict[int, int] = {}
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/stat", encoding="utf-8", errors="replace") as fh:
                fields = fh.read().rsplit(")", 1)[-1].split()
            ppid_of[int(entry)] = int(fields[1])
        except (OSError, IndexError, ValueError):
            continue
    tree = {root_pid}
    grew = True
    while grew:
        grew = False
        for pid, ppid in ppid_of.items():
            if ppid in tree and pid not in tree:
                tree.add(pid)
                grew = True
    return tree


def _tree_vmrss_gib(pids: set[int]) -> float:
    total_kib = 0
    for pid in pids:
        try:
            with open(f"/proc/{pid}/status", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if line.startswith("VmRSS:"):
                        total_kib += int(line.split()[1])
                        break
        except (OSError, ValueError):
            continue
    return total_kib / (1024.0**2)


def _tree_vram_gib(pids: set[int]) -> float | None:
    try:
        out = subprocess.run(
            [
                "nvidia-smi",
                "--query-compute-apps=pid,used_gpu_memory",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout
    except Exception:
        return None
    total_mib = 0.0
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 2 or not parts[0].isdigit():
            continue
        if int(parts[0]) in pids:
            with contextlib.suppress(ValueError):
                total_mib += float(parts[1])
    return total_mib / 1024.0 if total_mib else None


class _TreeSampler(threading.Thread):
    """Every ``interval`` seconds: peak anon-RSS + peak VRAM of OUR tree."""

    def __init__(self, interval: float = 5.0) -> None:
        super().__init__(daemon=True)
        self.interval = interval
        self.peak_rss_gib = 0.0
        self.peak_vram_gib: float | None = None
        self._stop = threading.Event()

    def run(self) -> None:  # pragma: no cover - timing thread
        me = os.getpid()
        while not self._stop.is_set():
            pids = _descendant_pids(me)
            self.peak_rss_gib = max(self.peak_rss_gib, _tree_vmrss_gib(pids))
            vram = _tree_vram_gib(pids)
            if vram is not None:
                self.peak_vram_gib = max(self.peak_vram_gib or 0.0, vram)
            self._stop.wait(self.interval)

    def stop(self) -> None:
        self._stop.set()


# ---------------------------------------------------------------------------
# leg — one minimal real training workload
# ---------------------------------------------------------------------------


def run_leg(args: argparse.Namespace) -> int:
    # Heavy imports deferred so `assemble` and `--help` stay light.
    from core.sandbox_executor import TidmadSandbox
    from execute_tools.dataset_config import DataScope
    from execute_tools.sample_set_builder import build_sample_set

    with open(LEGACY_CONFIGS_PATH, encoding="utf-8") as fh:
        legacy = json.load(fh)
    if args.model not in legacy:
        print(f"[probe-leg] no legacy config for model {args.model!r}", file=sys.stderr)
        return 2
    cfg = legacy[args.model]
    m_cfg = dict(cfg["model_cfg"])
    t_cfg = dict(cfg["train_cfg"])
    l_cfg = dict(cfg["loss_cfg"])
    t_cfg["epochs"] = 1  # paper-spec baseline depth; the probe measures, never tunes

    scope = DataScope.from_cli(args.band)
    workspace = os.path.abspath(args.workspace)
    os.makedirs(workspace, exist_ok=True)
    run_name = f"gpu_c_probe_{args.leg_label}_band{args.band}"
    exp_id = f"{run_name}_{int(time.time())}"

    sample_set = build_sample_set(
        is_trial=True,
        trial_strategy="snapshot",
        trial_portion=1.0,
        seed=0,
        scope=scope,
    )
    sandbox = TidmadSandbox(
        metadata_source="local",
        run_name=run_name,
        workspace=workspace,
        progress_bar=False,
        file_index=6,  # unused in sample-set mode but required by the constructor
        data_scope=scope,
    )

    print(
        f"[probe-leg] band={args.band} model={args.model} "
        f"train_portion={args.train_portion} workspace={workspace}"
    )
    sampler = _TreeSampler()
    sampler.start()
    t0 = time.time()
    result = sandbox.execute_training(
        exp_id=exp_id,
        run_name=run_name,
        model_type=args.model,
        m_cfg=m_cfg,
        t_cfg=t_cfg,
        l_cfg=l_cfg,
        sample_set=sample_set,
        train_portion=args.train_portion,
        train_base_seed=42,
    )
    wall = time.time() - t0
    sampler.stop()

    status = result.get("status") if isinstance(result, dict) else "unknown"
    leg = {
        "leg_label": args.leg_label,
        "band": args.band,
        "model": args.model,
        "train_portion": args.train_portion,
        "status": status,
        "wall_seconds": round(wall, 2),
        "peak_tree_anon_rss_gib": round(sampler.peak_rss_gib, 3),
        "peak_tree_vram_gib": (
            round(sampler.peak_vram_gib, 3) if sampler.peak_vram_gib is not None else None
        ),
        "started_unix": round(t0, 2),
        "ended_unix": round(t0 + wall, 2),
        "workspace": workspace,
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(leg, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"[probe-leg] {args.leg_label} band={args.band} status={status} wall={wall:.1f}s")
    if status != "success":
        msg = result.get("message") if isinstance(result, dict) else result
        print(f"[probe-leg] training did not succeed: {msg}", file=sys.stderr)
        return 1
    return 0


# ---------------------------------------------------------------------------
# assemble — derive the factor and write gpu_c_probe_result.json
# ---------------------------------------------------------------------------


def _load_leg(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def assemble(args: argparse.Namespace) -> int:
    work = Path(args.work_dir)
    solo = _load_leg(work / "leg_solo.json")
    quad_legs = {band: _load_leg(work / f"leg_quad_band{band}.json") for band in CAMPAIGN_BANDS}

    failures = [
        f"{leg['leg_label']}_band{leg['band']}"
        for leg in (solo, *quad_legs.values())
        if leg.get("status") != "success"
    ]

    # Host MemAvailable samples recorded by the orchestrator ("<unix> <kib>").
    host_samples_path = work / "host_memavailable_samples.txt"
    min_memavailable_gib: float | None = None
    if host_samples_path.exists():
        values = []
        for line in host_samples_path.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1].isdigit():
                values.append(int(parts[1]))
        if values:
            min_memavailable_gib = round(min(values) / (1024.0**2), 3)

    solo_wall = float(solo["wall_seconds"])
    matched_quad_wall = float(quad_legs[REFERENCE_BAND]["wall_seconds"])
    factor = round(matched_quad_wall / solo_wall, 3) if solo_wall > 0 else None

    result = {
        "probe": "gpu_c_coresidency",
        "reference_band": REFERENCE_BAND,
        "solo_leg": solo,
        "quad_legs": {band: quad_legs[band] for band in CAMPAIGN_BANDS},
        "coresidency_factor": factor,
        "coresidency_factor_definition": (
            f"quad wall of band {REFERENCE_BAND} / solo wall of band {REFERENCE_BAND} "
            "(matched band, so band sizes cannot skew the ratio)"
        ),
        "per_chain_peak_vram_gib": {
            band: quad_legs[band].get("peak_tree_vram_gib") for band in CAMPAIGN_BANDS
        },
        "per_chain_peak_anon_rss_gib": {
            band: quad_legs[band].get("peak_tree_anon_rss_gib") for band in CAMPAIGN_BANDS
        },
        "sum_of_per_chain_rss_peaks_gib": round(
            sum(
                float(quad_legs[band].get("peak_tree_anon_rss_gib") or 0.0)
                for band in CAMPAIGN_BANDS
            ),
            3,
        ),
        "min_host_memavailable_gib_during_quad": min_memavailable_gib,
        "failed_legs": failures,
        "generated_unix": round(time.time(), 2),
    }
    out = Path(args.out)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, sort_keys=True)
        fh.write("\n")

    print("=" * 68)
    print("GPU-C CO-RESIDENCY PROBE RESULT")
    print("=" * 68)
    print(f"  solo   band {REFERENCE_BAND}: {solo_wall:.1f}s")
    for band in CAMPAIGN_BANDS:
        leg = quad_legs[band]
        print(
            f"  quad   band {band}: {float(leg['wall_seconds']):.1f}s  "
            f"vram_peak={leg.get('peak_tree_vram_gib')} GiB  "
            f"rss_peak={leg.get('peak_tree_anon_rss_gib')} GiB"
        )
    print(f"  4-way coresidency_factor (matched band {REFERENCE_BAND}): {factor}")
    print(f"  min host MemAvailable during quad leg: {min_memavailable_gib} GiB")
    if failures:
        print(f"  FAILED LEGS: {failures} — factor is NOT usable evidence")
    else:
        print("  Copy the factor into sdsc_submission_scripts/h100_posture.env:")
        print(f"    H100_CORESIDENCY_FACTOR={factor}   (+ bump H100_POSTURE_VERSION)")
    print(f"  Full result: {out}")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    leg = sub.add_parser("leg", help="run one minimal real training leg and time it")
    leg.add_argument("--band", required=True, choices=CAMPAIGN_BANDS)
    leg.add_argument("--leg-label", required=True, help="solo | quad (result-file naming)")
    leg.add_argument("--workspace", required=True)
    leg.add_argument("--out", required=True, help="leg JSON output path")
    leg.add_argument("--model", default="wavenet", help="legacy baseline model (default wavenet)")
    leg.add_argument(
        "--train-portion",
        type=float,
        default=0.05,
        help="per-epoch subsample fraction (default 0.05 — minimal but real)",
    )

    asm = sub.add_parser("assemble", help="derive the factor from the recorded legs")
    asm.add_argument("--work-dir", required=True, help="the probe run directory with leg JSONs")
    asm.add_argument("--out", required=True, help="gpu_c_probe_result.json path")

    args = parser.parse_args()
    if args.cmd == "leg":
        return run_leg(args)
    return assemble(args)


if __name__ == "__main__":
    sys.exit(main())
