"""Deterministic verdict-parity corpus for the six TIDMAD health checks.

Step 08a / C1 (capture-first). This module owns ONE thing: a fixed set of
reproducible check invocations covering every class of the §3.1 verdict
derivation table, so that

  * ``goldens/generate_verdict_parity_manifest.py`` can freeze TODAY's
    behaviour as committed evidence BEFORE any 08a behavioural change, and
  * ``test_check_verdict.py`` can replay the SAME invocations at any later
    08a head and compare against that frozen manifest.

Design authority: ``docs/design/generic_framework_upgrade/
step_08_health_check_task_profile/pr_08a_check_input_contract.md`` §3.1, §4.1.

Two properties make the manifest trustworthy:

1. **The expected verdict is computed here, never by production code.**
   ``classify_expected_verdict`` is an INDEPENDENT transcription of the
   design's §3.1 table. When the production derivation lands on
   ``HealthCheckResult``, the parity test compares production against this
   transcription — not against itself. (Test-architecture rule 25: expected
   values must not be produced by the implementation under test.)
2. **Every recorded field is normalised to be path- and platform-stable.**
   Reasons and metrics embed absolute HDF5 paths from a temporary
   directory; those are rewritten to ``<WORKDIR>`` so the manifest is a
   byte-stable artifact. Non-finite floats become explicit sentinels
   because JSON cannot carry them.

The inputs are the SHAPES the existing per-check unit tests already use
(constant int8 collapse, varied int8, missing file, missing dataset,
sinusoid, empty context) — this module invents no new scientific case, it
only makes them reproducible outside a pytest ``tmp_path``.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

import h5py
import numpy as np

from execute_tools.dataset_config import resolve_dataset_profile, tidmad_topology
from execute_tools.health_checks.amplitude_collapse import AmplitudeCollapseCheck
from execute_tools.health_checks.output_diversity import OutputDiversityCheck
from execute_tools.health_checks.output_std import OutputStdCheck
from execute_tools.health_checks.pearson_dispersion import PearsonDispersionCheck
from execute_tools.health_checks.per_file_output_std import PerFileOutputStdCheck
from execute_tools.health_checks.schemas import HealthCheckContext, HealthCheckResult
from execute_tools.health_checks.spectral_peak_ratio import SpectralPeakRatioCheck

WORKDIR_TOKEN = "<WORKDIR>"
"""Placeholder substituted for the temporary fixture directory."""

_NAN = "__nan__"
_POS_INF = "__inf__"
_NEG_INF = "__-inf__"

_PEEK = 8_192
"""Fixture peek width. Large enough for ``spectral_peak_ratio``'s
``2 * _NOISE_HALF_WIDTH + 1 = 101`` sample floor, small enough to keep the
whole corpus well under a second."""


# ---------------------------------------------------------------------------
# Fixture writers — the HDF5 shapes the per-check tests already use
# ---------------------------------------------------------------------------


def _write_channel(path: Path, channel: str, data: np.ndarray) -> None:
    """Write ``timeseries/<channel>/timeseries`` — the walk ``_peek`` performs."""
    with h5py.File(str(path), "w") as f:
        ts = f.require_group("timeseries")
        grp = ts.require_group(channel)
        grp.create_dataset("timeseries", data=data, chunks=True)


def _output_channel() -> str:
    return tidmad_topology(resolve_dataset_profile()).channels.input_channel


def _target_channel() -> str:
    return tidmad_topology(resolve_dataset_profile()).channels.target_channel


def _varied(n: int = _PEEK, seed: int = 42) -> np.ndarray:
    """Healthy-looking int8: many distinct symbols, non-trivial dispersion."""
    rng = np.random.default_rng(seed)
    return rng.integers(-40, 40, size=n, dtype=np.int8)


def _constant(n: int = _PEEK, value: int = -1) -> np.ndarray:
    """The canonical class-127 collapse shape."""
    return np.full(n, value, dtype=np.int8)


def _sinusoid(n: int = _PEEK) -> np.ndarray:
    """Strong single-tone int8 — a well-defined spectral peak."""
    t = np.arange(n) / 10_000_000.0
    return np.clip(60 * np.sin(2 * np.pi * 1000 * t), -128, 127).astype(np.int8)


def _ctx(**overrides: Any) -> HealthCheckContext:
    base: dict[str, Any] = {"model_name": "m", "run_name": "r", "round_index": 1}
    base.update(overrides)
    return HealthCheckContext(**base)


# ---------------------------------------------------------------------------
# Case definitions
# ---------------------------------------------------------------------------

# A case builder receives the workdir and returns (skill, ctx, config).
CaseBuilder = Callable[[Path], tuple[Any, HealthCheckContext, dict[str, Any] | None]]


def _peek_based_cases(
    check_factory: Callable[[], Any], slug: str, config: dict[str, Any]
) -> dict[str, CaseBuilder]:
    """The five input classes shared by the three ``peek_and_aggregate`` checks.

    They share one code path (``_multi_file_peek.peek_and_aggregate``), so
    they share one case shape; the per-check thresholds differ, which is why
    the config is supplied by the caller.
    """

    def healthy(workdir: Path):
        p = workdir / f"{slug}_healthy.h5"
        _write_channel(p, _output_channel(), _varied())
        return check_factory(), _ctx(denoised_paths={0: str(p)}), dict(config)

    def collapsed(workdir: Path):
        p = workdir / f"{slug}_collapsed.h5"
        _write_channel(p, _output_channel(), _constant())
        return check_factory(), _ctx(denoised_paths={0: str(p)}), dict(config)

    def not_applicable(workdir: Path):
        # Neither denoised_paths nor denoised_filename_fn, and no explicit
        # peek_file_indices → the documented NA fallback in
        # _multi_file_peek.py:253-261.
        return check_factory(), _ctx(), dict(config)

    def all_io_failed(workdir: Path):
        # EXPLICIT peek_file_indices → the NA fallback does NOT trigger
        # (§2.1 asymmetry); aggregation runs over only-io-failed rows.
        cfg = dict(config)
        cfg["peek_file_indices"] = [0, 1]
        ctx = _ctx(
            denoised_paths={
                0: str(workdir / "absent_a.h5"),
                1: str(workdir / "absent_b.h5"),
            }
        )
        return check_factory(), ctx, cfg

    def partial_io_failed(workdir: Path):
        p = workdir / f"{slug}_collapsed.h5"
        _write_channel(p, _output_channel(), _constant())
        cfg = dict(config)
        cfg["peek_file_indices"] = [0, 1]
        ctx = _ctx(denoised_paths={0: str(p), 1: str(workdir / "absent_c.h5")})
        return check_factory(), ctx, cfg

    return {
        f"{slug}__pass_healthy": healthy,
        f"{slug}__fail_collapsed": collapsed,
        f"{slug}__na_no_path_configured": not_applicable,
        f"{slug}__all_io_failed": all_io_failed,
        f"{slug}__partial_io_failed": partial_io_failed,
    }


def _per_file_output_std_cases() -> dict[str, CaseBuilder]:
    def measured(workdir: Path):
        p = workdir / "pfstd_varied.h5"
        _write_channel(p, _output_channel(), _varied())
        ctx = _ctx(denoised_paths={0: str(p)})
        return PerFileOutputStdCheck(), ctx, {"peek_samples": _PEEK}

    def not_applicable(workdir: Path):
        # No denoised_paths, no denoised_filename_fn, no configured indices
        # → _resolve_files returns [] → the in-check NA return.
        return PerFileOutputStdCheck(), _ctx(), {"peek_samples": _PEEK}

    def all_io_failed(workdir: Path):
        ctx = _ctx(
            denoised_paths={
                0: str(workdir / "absent_a.h5"),
                1: str(workdir / "absent_b.h5"),
            }
        )
        return PerFileOutputStdCheck(), ctx, {"peek_samples": _PEEK}

    def partial_io_failed(workdir: Path):
        p = workdir / "pfstd_varied.h5"
        _write_channel(p, _output_channel(), _varied())
        ctx = _ctx(denoised_paths={0: str(p), 1: str(workdir / "absent_b.h5")})
        return PerFileOutputStdCheck(), ctx, {"peek_samples": _PEEK}

    return {
        "per_file_output_std__pass_measured": measured,
        "per_file_output_std__na_no_files": not_applicable,
        "per_file_output_std__all_io_failed": all_io_failed,
        "per_file_output_std__partial_io_failed": partial_io_failed,
    }


def _spectral_peak_ratio_cases() -> dict[str, CaseBuilder]:
    def measured(workdir: Path):
        p = workdir / "spectral_sine.h5"
        _write_channel(p, _output_channel(), _sinusoid())
        ctx = _ctx(denoised_paths={0: str(p)})
        return SpectralPeakRatioCheck(), ctx, {"peek_samples": _PEEK}

    def not_applicable(workdir: Path):
        return SpectralPeakRatioCheck(), _ctx(), {"peek_samples": _PEEK}

    def all_io_failed(workdir: Path):
        ctx = _ctx(denoised_paths={0: str(workdir / "absent_a.h5")})
        return SpectralPeakRatioCheck(), ctx, {"peek_samples": _PEEK}

    def missing_dataset(workdir: Path):
        # A real HDF5 file whose channel0001 walk is absent → KeyError,
        # the second io-failure class the per-check tests exercise.
        p = workdir / "spectral_wrong_shape.h5"
        with h5py.File(str(p), "w") as f:
            f.create_group("wrong_group")
        ctx = _ctx(denoised_paths={0: str(p)})
        return SpectralPeakRatioCheck(), ctx, {"peek_samples": _PEEK}

    return {
        "spectral_peak_ratio__pass_measured": measured,
        "spectral_peak_ratio__na_no_files": not_applicable,
        "spectral_peak_ratio__all_io_failed": all_io_failed,
        "spectral_peak_ratio__all_io_failed_missing_dataset": missing_dataset,
    }


def _pearson_dispersion_cases() -> dict[str, CaseBuilder]:
    def _pair(workdir: Path, index: int, seed: int) -> tuple[str, str]:
        d = workdir / f"pearson_denoised_{index}.h5"
        t = workdir / f"pearson_target_{index}.h5"
        _write_channel(d, _output_channel(), _varied(seed=seed))
        _write_channel(t, _target_channel(), _varied(seed=seed + 100))
        return str(d), str(t)

    def measured(workdir: Path):
        d0, t0 = _pair(workdir, 0, seed=1)
        d1, t1 = _pair(workdir, 1, seed=2)
        targets = {0: t0, 1: t1}
        ctx = _ctx(
            denoised_paths={0: d0, 1: d1},
            target_path_fn=lambda fi: targets[fi],
        )
        return PearsonDispersionCheck(), ctx, {"peek_samples": _PEEK}

    def na_no_target_fn(workdir: Path):
        p = workdir / "pearson_denoised_only.h5"
        _write_channel(p, _output_channel(), _varied())
        # target_path_fn absent → the FIRST NA axis (a declared context
        # input is missing), distinct from "no files".
        return PearsonDispersionCheck(), _ctx(denoised_paths={0: str(p)}), {"peek_samples": _PEEK}

    def na_no_files(workdir: Path):
        ctx = _ctx(target_path_fn=lambda fi: str(workdir / f"target_{fi}.h5"))
        return PearsonDispersionCheck(), ctx, {"peek_samples": _PEEK}

    def all_io_failed(workdir: Path):
        ctx = _ctx(
            denoised_paths={0: str(workdir / "absent_a.h5")},
            target_path_fn=lambda fi: str(workdir / "absent_target.h5"),
        )
        return PearsonDispersionCheck(), ctx, {"peek_samples": _PEEK}

    return {
        "pearson_dispersion__pass_measured": measured,
        "pearson_dispersion__na_no_target_path_fn": na_no_target_fn,
        "pearson_dispersion__na_no_files": na_no_files,
        "pearson_dispersion__all_io_failed": all_io_failed,
    }


def _build_case_table() -> dict[str, CaseBuilder]:
    cases: dict[str, CaseBuilder] = {}
    cases.update(
        _peek_based_cases(
            OutputDiversityCheck,
            "output_diversity",
            {"min_unique_int8_values": 5, "peek_samples": _PEEK},
        )
    )
    cases.update(
        _peek_based_cases(
            OutputStdCheck,
            "output_std",
            {"min_std_mv": 1.0, "peek_samples": _PEEK},
        )
    )
    cases.update(
        _peek_based_cases(
            AmplitudeCollapseCheck,
            "amplitude_collapse",
            {"collapse_threshold": 0.95, "peek_samples": _PEEK},
        )
    )
    cases.update(_per_file_output_std_cases())
    cases.update(_spectral_peak_ratio_cases())
    cases.update(_pearson_dispersion_cases())
    return cases


CASES: dict[str, CaseBuilder] = _build_case_table()
"""case_id → builder. Iteration order is the manifest order (sorted below)."""

CASE_IDS: tuple[str, ...] = tuple(sorted(CASES))


# ---------------------------------------------------------------------------
# Normalisation — makes a live result comparable to a committed manifest
# ---------------------------------------------------------------------------


def _normalise_scalar(value: Any, workdir: str) -> Any:
    if isinstance(value, str):
        return value.replace(workdir, WORKDIR_TOKEN)
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        if math.isnan(value):
            return _NAN
        if value == math.inf:
            return _POS_INF
        if value == -math.inf:
            return _NEG_INF
        return value
    if isinstance(value, np.generic):
        return _normalise_scalar(value.item(), workdir)
    return value


def normalise(value: Any, workdir: str) -> Any:
    """Recursively make ``value`` JSON-stable: paths tokenised, NaN/Inf named.

    ``strict`` JSON is the point — ``json.dumps(..., allow_nan=False)`` on
    the result must succeed, so a manifest can never carry a token no other
    reader can parse.
    """
    if isinstance(value, dict):
        return {
            str(k): normalise(v, workdir)
            for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))
        }
    if isinstance(value, list | tuple):
        return [normalise(v, workdir) for v in value]
    return _normalise_scalar(value, workdir)


# ---------------------------------------------------------------------------
# The INDEPENDENT expected-verdict classifier (design §3.1)
# ---------------------------------------------------------------------------

_NA_MARKER = "not applicable"
"""The exact production marker, lowercase, as emitted at
``_multi_file_peek.py:260``, ``spectral_peak_ratio.py:62``,
``per_file_output_std.py:53``, ``pearson_dispersion.py:56,65``."""


def classify_expected_verdict(passed: bool, reason: str, metrics: dict[str, Any]) -> str:
    """Transcribe the design §3.1 table. **Never call production code here.**

    | today's result                                    | verdict        |
    |---------------------------------------------------|----------------|
    | passed, reason empty or non-NA                     | passed         |
    | passed, reason carries the production NA marker    | inapplicable   |
    | failed, ``exception_type`` present, or all-io-failed | error        |
    | failed otherwise                                   | failed         |
    """
    if passed:
        return "inapplicable" if _NA_MARKER in reason.lower() else "passed"
    if "exception_type" in metrics:
        return "error"
    attempted = metrics.get("n_files_attempted")
    io_failed = metrics.get("n_files_io_failed")
    if isinstance(attempted, int) and attempted > 0 and io_failed == attempted:
        return "error"
    return "failed"


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


TIDMAD_VALUE_SCALE: dict[str, Any] = {
    "value_scale_units_per_sample": 40.0 / 128.0,
    "value_scale_unit": "mV",
}
"""What composition injects for TIDMAD since Step 08b C5.

Supplied here so the 27 frozen cases keep replaying the SAME arithmetic they
were captured under. Before C5 the factor was a literal inside four check
modules and this corpus inherited it silently; the number is unchanged —
only its owner is."""


def run_case(case_id: str, workdir: Path) -> HealthCheckResult:
    """Build this case's fixtures under ``workdir`` and run its check."""
    skill, ctx, config = CASES[case_id](workdir)
    return skill.run(ctx, {**TIDMAD_VALUE_SCALE, **(config or {})})


def record_case(case_id: str, workdir: Path) -> dict[str, Any]:
    """Run one case and return its normalised, JSON-stable manifest row."""
    result = run_case(case_id, workdir)
    token = str(workdir)
    metrics = normalise(result.metrics, token)
    row = {
        "case_id": case_id,
        "check_name": result.check_name,
        "passed": result.passed,
        "reason": _normalise_scalar(result.reason, token),
        "metrics_keyset": sorted(result.metrics),
        "metrics": metrics,
        "expected_verdict": classify_expected_verdict(result.passed, result.reason, result.metrics),
    }
    # Fail loudly here rather than writing a manifest no reader can load.
    json.dumps(row, allow_nan=False, sort_keys=True)
    return row


def record_all(workdir: Path) -> list[dict[str, Any]]:
    """Every case, in deterministic (sorted) case-id order."""
    rows: list[dict[str, Any]] = []
    for case_id in CASE_IDS:
        case_dir = workdir / case_id
        case_dir.mkdir(parents=True, exist_ok=True)
        rows.append(record_case(case_id, case_dir))
    return rows
