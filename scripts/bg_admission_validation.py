"""B-G1 / B-G2 admission validation harness. VALIDATION ONLY.

Drives the **real** tuner, the **real** `TidmadSandbox`, the **real**
admission gate and the **real** launch boundary. Nothing here stubs,
mocks or monkeypatches any of them: a validation that replaces the thing
it is validating proves only that the replacement works.

It exists because the tuner's CLI constructs `HyperparamTuningAgent()`
with no `sandbox_factory`, and no production field carries a measurement
(see the PR B design §4c.3). So a measurement fixture can only reach
admission through the existing factory seam. **That is a limitation, not
a feature**: it means these scenarios enter below `run_chain.sh`, and
B-G3 remains a separate gate before the D-B4 default flip.

The fixture is a **test input**. It never enters a registry, is never
promoted, and is stamped `validation_only=true` wherever it is recorded.
PR C owns acquisition, applicability and promotion.

Three scenarios, all `formal`, all PUNet, all under a validation-only
6 GiB ceiling. The only variable between bg1 and bg2b is `other_mib`:

    bg1    fixture, idle card         1,476 < 6,144 -> admitted
    bg2a   NO fixture                               -> policy_unavailable
    bg2b   fixture + >4,668 MiB held  >6,144        -> insufficient_headroom

The figures are B-G0's measured training peak, not the superseded 3,076
MiB A5 estimate for the same model name — see the PR B design §4d.3g.

`formal` is deliberate. Under `trial` a fixture that never reached
admission would still admit, and bg1 would pass while proving nothing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

#: Measured by B-G0 on this UUID, 2026-08-02, per phase. A5's figures
#: are historical reference only: they carry no GPU UUID, and B-G0
#: measured 1,476 MiB for a candidate A5 measured at 3,076 MiB — the
#: planner chose a different configuration, which is precisely why a
#: model name cannot stand in for applicability.
FIXTURE_REQUIREMENTS_MIB = {"training": 1_476, "inference": 2_716}
FIXTURE_SOURCE = "B-G0 bg0_measure_v2 — driver-visible peaks, samples_run2"

#: Validation-only. It neither changes nor validates the production
#: 28.0 GiB default; production configuration is B-G3/D-B4's subject.
VALIDATION_CEILING_GIB = 6.0


class ConfigMismatch(BaseException):
    """The realized configuration is not the one the fixture describes.

    Derives from `BaseException`, deliberately. The tuner wraps an
    attempt in `except Exception` and turns anything it catches into a
    retryable training failure — the first B-G1 returned a
    `status="error"` refusal and was retried three times into
    `max_fail_rounds`. A mismatch is not a candidate failure and must not
    be retried, so it must be uncatchable by that handler and is caught
    by this script instead.

    This changes no production retry policy. The defect was the harness
    borrowing the training-error contract for something that is not a
    training error.
    """

    def __init__(self, phase: str, expected: str, actual: str, realized: dict):
        self.phase, self.expected, self.actual, self.realized = phase, expected, actual, realized
        super().__init__(f"{phase}: config group(s) {expected} differ from the fixture")


class HarnessError(BaseException):
    """The harness cannot evaluate its own precondition."""


SCENARIOS = ("bg0", "bg1", "bg2a", "bg2b")

#: B-G0 is the only scenario that runs `trial`, and it must.
#: In `formal` with no fixture the gate correctly refuses, so a formal
#: B-G0 would refuse itself and never produce the measurement it exists
#: to collect. Every other scenario runs `formal` precisely so a missing
#: or inapplicable fixture cannot pass vacuously.
SCENARIO_MODE = {"bg0": "trial", "bg1": "formal", "bg2a": "formal", "bg2b": "formal"}


def config_hash(payload: dict[str, Any]) -> str:
    """A stable identity for the configuration a measurement describes."""
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:16]


#: What each phase actually receives, as executor parameter name ->
#: fixture group name. `execute_inference` takes `m_cfg` and `l_cfg` but
#: **no** `t_cfg` (`core/sandbox_executor.py:1339`) — inference never
#: sees the train config, so one whole-config digest cannot be the basis
#: for both gates. Comparing per group is phase-correct and more
#: informative than a digest, which can only say "different".
PHASE_GROUPS: dict[str, dict[str, str]] = {
    "training": {"m_cfg": "model_config", "t_cfg": "train_config", "l_cfg": "loss_config"},
    "inference": {"m_cfg": "model_config", "l_cfg": "loss_config"},
}


def realize_phase_config(phase: str, params: Mapping[str, Any]) -> dict[str, Any]:
    """The config groups `phase` actually received, keyed by fixture name.

    Reads the names the executor really takes. The first B-G1 read
    `model_config`/`train_config`/`loss_config` — names belonging to the
    *skill wrapper*, which renames them to `m_cfg`/`t_cfg`/`l_cfg` before
    calling the sandbox — got `None` for all three, and hashed that same
    all-`None` value every time: a guard that refused everything, which
    is as worthless as one that accepts everything and harder to notice
    because it looks strict.

    Raises:
        HarnessError: if `phase` is unknown, or a group the phase takes
            was not supplied. Absence is never normalized into a hash: an
            all-`None` digest is stable, wrong, and indistinguishable
            from a real mismatch.
    """
    wanted = PHASE_GROUPS.get(phase)
    if wanted is None:
        raise HarnessError(f"unknown phase {phase!r}; expected one of {sorted(PHASE_GROUPS)}")
    realized = {name: params.get(arg) for arg, name in wanted.items()}
    # `is None`, not falsiness: a group that arrived as an empty dict was
    # supplied and must be compared (and may legitimately differ from the
    # fixture), whereas a group that never arrived means the harness read
    # the wrong name and cannot evaluate its own precondition.
    missing = sorted(n for n, v in realized.items() if v is None)
    if missing:
        raise HarnessError(
            f"{phase}: could not read {missing} from the phase arguments "
            f"(saw {sorted(params)}) — the harness cannot evaluate its own precondition"
        )
    return realized


def compare_phase_config(
    phase: str, params: Mapping[str, Any], expected: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Check the realized phase config against the fixture.

    Returns:
        The realized record — `phase`, `config` and a **phase-scoped**
        `config_sha256`. That digest covers only the groups this phase
        receives, so the inference digest is deliberately not comparable
        to the fixture's whole-config hash; the per-group comparison is
        what decides, and it is exact.

    Raises:
        HarnessError: propagated from `realize_phase_config`.
        ConfigMismatch: if any group this phase receives differs.
    """
    realized = realize_phase_config(phase, params)
    record = {"phase": phase, "config": realized, "config_sha256": config_hash(realized)}
    if expected:
        differing = sorted(n for n, v in realized.items() if expected.get(n) != v)
        if differing:
            raise ConfigMismatch(phase, ",".join(differing), record["config_sha256"], record)
    return record


def phase_config_diff(
    phase: str, expected: Mapping[str, Any] | None, realized: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    """Per-group expected-vs-realized differences, for the evidence file.

    Restricted to the groups `phase` actually receives. Iterating a fixed
    three would report a phantom `train_config` diff on every inference
    mismatch — inference never gets one — so the evidence would
    contradict the phase-correctness this check exists to establish.
    """
    expected = expected or {}
    return {
        group: {"expected": expected.get(group), "realized": realized.get(group)}
        for group in PHASE_GROUPS[phase].values()
        if expected.get(group) != realized.get(group)
    }


def phase_evidence(
    sandbox: Any, phase: str, realized: Mapping[str, Any], expected: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Full evidence for one phase, recorded whether it passes or fails.

    Two gaps this closes, both found in the B-G1 rerun:

    1. **The permit path was silent.** Production logs only refusals, so
       "admitted" rested on the *absence* of a refusal — and a gate that
       never ran at all would look exactly the same. So this calls
       production's own `_admission_refusal` and records what it
       returns.

       Honest about what that is: it is a **second** evaluation, taken
       immediately before the production call inside `super()`, against
       the same sandbox and the same device state. It is not the
       production call's own return value, and it is not a mock or a
       reimplementation — it is the real function. `_admission_refusal`
       returns a dict or `None` and has no side effects, so evaluating
       it twice is safe.

    2. **`realized` was stored only on mismatch.** On a match the
       evidence recorded the expectation and not the observation, so a
       PASS had to be verified by recomputing from the experiment record
       outside the harness. Now both are always written, and a matching
       diff is written as an explicit `{}` rather than omitted — absent
       and empty must not look alike.
    """
    from core.sandbox_executor import _admission_refusal, _phase_requirement

    requirement_mib, provenance = _phase_requirement(sandbox, phase)
    refusal = _admission_refusal(sandbox, phase=phase)
    admission = refusal.get("admission", {}) if isinstance(refusal, dict) else {}
    return {
        "phase": phase,
        "gate_evaluated": True,
        "admission_result": "refused" if refusal is not None else "admitted",
        "reason_code": admission.get("reason_code"),
        "detail": admission.get("detail"),
        "requirement_mib": requirement_mib,
        "requirement_provenance": provenance,
        "admission_mode": getattr(sandbox, "admission_mode", None),
        "expected_config": dict(expected) if expected else None,
        "expected_config_sha256": config_hash(dict(expected)) if expected else None,
        "realized_config": realized.get("config"),
        "realized_config_sha256": realized.get("config_sha256"),
        "config_diff": phase_config_diff(phase, expected, realized.get("config", {})),
        "witness_note": (
            "admission_result is a harness-side call to the real "
            "core.sandbox_executor._admission_refusal immediately before the "
            "production call; it is not the production call's own return value"
        ),
    }


def load_fixture(path: str) -> dict:
    """B-G0's recorded fixture, read from disk rather than reconstructed.

    Rebuilding it in code would mean two descriptions of one
    measurement, and the one the harness used would drift from the one
    the run produced. The file is the record.
    """
    fixture = json.loads(Path(path).read_text())
    missing = [
        k
        for k in ("device_uuid", "model_type", "config_sha256", "config", "phases")
        if not fixture.get(k)
    ]
    if missing:
        raise SystemExit(f"fixture {path} is missing required fields: {missing}")
    if not fixture.get("validation_only"):
        raise SystemExit(
            f"fixture {path} is not marked validation_only — this harness must "
            "never consume a record that claims production authority"
        )
    return fixture


def fixture_mismatch(fixture: dict, *, device_uuid: str, model_type: str) -> str | None:
    """Why this fixture does not describe this candidate, or None.

    Checked **before** any GPU child starts. A shared model name is not
    applicability: if the planner produced a different configuration, the
    measurement describes something else and the scenario cannot
    conclude.
    """
    if fixture.get("model_type") != model_type:
        return f"model_type {fixture.get('model_type')!r} != candidate {model_type!r}"
    if fixture.get("device_uuid") != device_uuid:
        return f"fixture measured on {fixture.get('device_uuid')!r}, this host is {device_uuid!r}"
    phases = fixture.get("phases") or {}
    if set(phases) != {"training", "inference"}:
        return (
            "the fixture must carry a measurement for BOTH phases; a training "
            "figure may not stand in for inference"
        )
    for phase, entry in phases.items():
        if entry.get("provenance") != "measured":
            return f"{phase} provenance {entry.get('provenance')!r} is not authoritative"
        if entry.get("measurement_type") != "driver_visible_peak":
            return f"{phase} is {entry.get('measurement_type')!r}, not a driver-visible peak"
    return None


CANDIDATE_SCRIPTS = ("train_engine_sandbox.py", "inference_single.py")


def summarize_record(record: Any) -> dict[str, Any]:
    """One record's admission-relevant fields, dict or model alike.

    `all_records` returns validated `ExperimentRecord` objects, not the
    raw dicts the tuner assembled — calling `.get()` on one raised
    `AttributeError` *after* B-G0's science had completed, losing the
    evidence write while the measurement itself survived only because
    the sampler is independent. Accepting both shapes is the fix; the
    lesson is that a summariser must not assume which side of a
    validation boundary its input came from.
    """

    def field(name: str) -> Any:
        if isinstance(record, Mapping):
            return record.get(name)
        return getattr(record, name, None)

    memory = field("memory")
    if memory is not None and not isinstance(memory, Mapping):
        memory = getattr(memory, "__dict__", {}) or {}
    return {
        "status": field("status"),
        "reason_code": (memory or {}).get("reason_code"),
        "counts_toward_attempt_budget": field("counts_toward_attempt_budget"),
        "counts_toward_completed_rounds": field("counts_toward_completed_rounds"),
        "denoising_score": field("denoising_score"),
    }


def candidate_gpu_children() -> list[str]:
    """Candidate training/inference processes actually running.

    Deliberately **not** "any GPU process": in bg2b the holder is on the
    card legitimately, so the claim under test is the absence of a
    *candidate* child.

    And deliberately not a `pgrep` text match. A shell whose command line
    merely *mentions* these script names — an operator's own inspection
    command, or this harness's launcher — matches the pattern while
    running nothing. That false positive was observed during the B-G0
    dry run, and in the no-child proof it would have produced a false
    FAIL: "a phase started" concluded from a grep hitting its own
    argument list.

    So each candidate PID is confirmed from `/proc/<pid>/cmdline`: some
    argument must *end with* one of the script names, and argv[0] must
    be a Python interpreter. A `bash -c` wrapper fails both.
    """
    found: list[str] = []
    self_pid = os.getpid()
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid == self_pid:
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
        except (OSError, PermissionError):
            continue
        argv = [a for a in raw.decode(errors="replace").split("\0") if a]
        if not argv:
            continue
        if "python" not in Path(argv[0]).name:
            continue
        if any(Path(a).name in CANDIDATE_SCRIPTS for a in argv):
            found.append(f"{pid} {' '.join(argv)}")
    return found


def compute_apps() -> list[str]:
    try:
        return [
            ln
            for ln in subprocess.run(
                [
                    "nvidia-smi",
                    "--query-compute-apps=pid,used_gpu_memory,gpu_uuid",
                    "--format=csv,noheader",
                ],
                capture_output=True,
                text=True,
                timeout=20,
            ).stdout.splitlines()
            if ln.strip()
        ]
    except Exception:
        return []


def make_sandbox_factory(
    fixture: dict | None, *, mode: str = "formal", witness: list[dict] | None = None
):
    """A factory returning a REAL TidmadSandbox carrying the fixture.

    The sandbox is genuine — the same class production uses, with the
    same arguments. Only the three admission attributes are set on it,
    which is the existing consumer boundary and the only way a
    measurement can reach the gate today.
    """
    from core.sandbox_executor import TidmadSandbox

    class _ValidationSandbox(TidmadSandbox):
        """A real `TidmadSandbox` with the admission fields declared.

        It adds **one** behaviour beyond the production class: a
        precondition at each GPU phase entry that the *realized*
        configuration matches the fixture. Everything else delegates to
        `super()`, so the phase itself runs production code.

        Why here and not in the harness before launching: the realized
        config is only known after the planner runs and
        `plan_overrides` are applied and `max_epochs` is clamped. The
        harness could *predict* it — the transformations are
        deterministic — but a prediction is not an observation, and this
        is the last point before a **candidate** GPU child exists. (It is
        not the last point before *any* GPU child: the preflight VRAM
        probe already spawned one at `isolated_probe.py:451`, reached
        from `ml_hyperparameter_tune_agent.py:3418`.) A mismatch raises
        and launches nothing.

        The declaration of the four admission fields exists because
        production has no typed home for them; supplying one is B-G3's
        job (see the PR B design §4c.3). The comparison itself lives in
        the module-level `compare_phase_config`, so it is testable
        without constructing a sandbox.
        """

        admission_mode: str
        measured_requirements: dict[str, dict[str, object]]
        expected_config: dict[str, object] | None = None
        realized: dict[str, Any]

        def _config_precondition(self, phase: str, params: dict) -> None:
            """Check the config, then witness the gate — before launch.

            Order matters: a config mismatch must raise before anything
            is recorded as admitted, otherwise the evidence would show a
            permit for a candidate that never ran.
            """
            self.realized = compare_phase_config(phase, params, self.expected_config)
            if witness is not None:
                witness.append(phase_evidence(self, phase, self.realized, self.expected_config))

        def execute_training(self, **params):
            self._config_precondition("training", params)
            return super().execute_training(**params)

        def execute_inference(self, **params):
            self._config_precondition("inference", params)
            return super().execute_inference(**params)

    def _factory(**kwargs):
        sandbox = _ValidationSandbox(**kwargs)
        sandbox.admission_mode = mode
        sandbox.expected_config = fixture.get("config") if fixture is not None else None
        sandbox.measured_requirements = (
            {
                phase: {
                    "requirement_mib": entry["requirement_mib"],
                    "provenance": entry["provenance"],
                }
                for phase, entry in fixture["phases"].items()
            }
            if fixture is not None
            else {}
        )
        return sandbox

    return _factory


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="VALIDATION-ONLY B-G admission harness")
    p.add_argument("--scenario", required=True, choices=SCENARIOS)
    p.add_argument("--device_uuid", required=True)
    p.add_argument("--force_model", default="punet")
    p.add_argument("--run_name", required=True)
    p.add_argument("--workspace", required=True)
    p.add_argument("--evidence_dir", required=True)
    p.add_argument("--provider", default="openai")
    p.add_argument("--model_id", default="gpt-5.5")
    p.add_argument("--reflect_provider", default="openai")
    p.add_argument("--reflect_model_id", default="gpt-5.5")
    p.add_argument("--data_scope", default="6")
    p.add_argument(
        "--fixture_path",
        default=None,
        help="B-G0 fixture JSON; required for bg1 and bg2b",
    )
    p.add_argument("--dry_run", action="store_true", help="preflight checks only, no run")
    return p


def preflight(args: argparse.Namespace) -> tuple[str, dict[str, Any]]:
    """Conditions that must hold before anything is launched."""
    ev: dict[str, Any] = {
        "scenario": args.scenario,
        "device_uuid": args.device_uuid,
        "validation_only": True,
        "validation_ceiling_gib": VALIDATION_CEILING_GIB,
        "ceiling_note": (
            "validation-only; does not change or validate the production "
            "28.0 GiB default (B-G3/D-B4 owns that)"
        ),
        "candidate_children_before": candidate_gpu_children(),
        "compute_apps_before": compute_apps(),
    }
    if ev["candidate_children_before"]:
        return "INCONCLUSIVE", ev | {"reason": "a candidate GPU child was already running"}
    if args.scenario != "bg2b" and ev["compute_apps_before"]:
        return "INCONCLUSIVE", ev | {"reason": "the GPU was not idle at start"}
    return "OK", ev


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence_dir = Path(args.evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    out = evidence_dir / f"{args.scenario}_evidence.json"

    # The validation ceiling is applied through the existing override,
    # so no production default is edited.
    os.environ["SIDERIUS_PAIR_VRAM_CEILING_GIB"] = str(VALIDATION_CEILING_GIB)

    verdict, ev = preflight(args)
    if verdict != "OK":
        out.write_text(json.dumps(ev | {"verdict": verdict}, indent=2))
        print(f"[bg] {verdict}: {ev.get('reason')}", file=sys.stderr)
        return 2

    fixture = None if args.scenario in {"bg0", "bg2a"} else load_fixture(args.fixture_path)
    ev["fixture"] = fixture

    if fixture is not None:
        mismatch = fixture_mismatch(
            fixture, device_uuid=args.device_uuid, model_type=args.force_model
        )
        if mismatch is not None:
            # No re-planning, no retry: a mismatch means the measurement
            # describes something else, and forcing a verdict would be
            # inventing applicability.
            ev |= {"verdict": "INCONCLUSIVE", "reason": f"fixture mismatch: {mismatch}"}
            out.write_text(json.dumps(ev, indent=2))
            print(f"[bg] INCONCLUSIVE: fixture mismatch: {mismatch}", file=sys.stderr)
            return 2

    if args.dry_run:
        ev |= {"verdict": "DRY_RUN", "reason": "preflight and fixture checks only"}
        out.write_text(json.dumps(ev, indent=2))
        print("[bg] DRY_RUN complete — nothing launched")
        return 0

    # --- real run: real agent, real sandbox, real gate ----------------
    from agent.schemas.hyperparam_tuning import HyperparamTuningInput
    from agent.schemas.storage import LocalStorageConfig, StorageConfig
    from execute_tools.dataset_config import DataScope
    from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
        HyperparamTuningAgent,
    )

    mode = SCENARIO_MODE[args.scenario]
    ev["admission_mode"] = mode
    # Per-phase evidence, appended by the sandbox at each GPU-phase
    # entry. Held here so it survives every exit path below — a witness
    # only written on success would be missing exactly when a refusal
    # needs explaining.
    witness: list[dict] = []
    agent = HyperparamTuningAgent(
        sandbox_factory=make_sandbox_factory(fixture, mode=mode, witness=witness)
    )
    tuning_input = HyperparamTuningInput(
        model_type=args.force_model,
        llm_provider=args.provider,
        llm_model_id=args.model_id,
        reflect_provider=args.reflect_provider,
        reflect_model_id=args.reflect_model_id,
        storage=StorageConfig(
            local=LocalStorageConfig(run_name=args.run_name, workspace=args.workspace)
        ),
        is_trial=True,
        max_rounds=1,
        attempts_per_formal_round=1,
        # VALIDATION ONLY. Production keeps its default of 3
        # (`hyperparam_tuning.py:1058`); this is a per-run input, not a
        # default change, and no production retry semantics move.
        #
        # A B-G scenario is one deterministic admission decision. The
        # first B-G2a proved why this matters: the refusal is a
        # statement about the machine, so every retry re-derived the
        # identical `policy_unavailable` and burned a planning call
        # each time — 3 attempts, 3 LLM calls, one fact. Retrying is
        # right for a campaign, where the environment can change
        # between rounds; it is meaningless inside a scenario whose
        # whole purpose is to hold the environment fixed.
        max_fail_rounds=1,
        max_epochs=1,
        formal_portion=0.02,
        formal_train_portion=1.0,
        formal_eval_portion=0.02,
        formal_vram_budget_gb=12.0,
        # Same conversion the tuner CLI performs (`main()`): the schema
        # wants a parsed DataScope and a list of indices, not the CLI's
        # string spec. Mirrored rather than reimplemented so the harness
        # cannot drift from the launcher's own interpretation.
        # Full-group `plan_overrides` from the fixture's recorded config.
        # Partial overrides would drop the fields they omit rather than
        # inherit them, because the merge replaces each group wholesale.
        plan_overrides=(
            {
                "model_cfg": fixture["config"]["model_config"],
                "train_cfg": fixture["config"]["train_config"],
                "loss_cfg": fixture["config"]["loss_config"],
            }
            if fixture is not None
            else {}
        ),
        data_scope=DataScope.from_cli(args.data_scope),
        health_gate_files=DataScope.from_cli(args.data_scope).file_indices,
    )
    ev["tuner_parent_pid"] = os.getpid()
    # Register the parent PID so the sampler can label it by identity
    # rather than by matching a script name (FU-B-15). Without this,
    # B-G0 and B-G1 produced no P0_TUNER_PARENT sample at all and
    # "parent held 0 MiB" rested on absence from NVML. Written to the
    # samples dir if the sampler is already running there, and to the
    # evidence dir either way.
    for target in (evidence_dir / "samples", evidence_dir):
        try:
            target.mkdir(parents=True, exist_ok=True)
            (target / "tuner_parent.pid").write_text(str(os.getpid()))
        except OSError:
            pass
    ev["expected_config_sha256"] = fixture.get("config_sha256") if fixture else None
    ev["expected_config"] = fixture.get("config") if fixture else None
    try:
        result = agent.run(tuning_input)
    except ConfigMismatch as mismatch:
        expected = (fixture or {}).get("config") or {}
        realized = mismatch.realized["config"]
        ev |= {
            "verdict": "INCONCLUSIVE",
            "reason": str(mismatch),
            "realized": mismatch.realized,
            "phases": witness,
            "config_diff": phase_config_diff(mismatch.phase, expected, realized),
            "candidate_children_after": candidate_gpu_children(),
            "compute_apps_after": compute_apps(),
        }
        out.write_text(json.dumps(ev, indent=2, default=str))
        print(f"[bg] INCONCLUSIVE: {mismatch}")
        return 2
    except HarnessError as bug:
        ev |= {"verdict": "HARNESS_ERROR", "reason": str(bug), "phases": witness}
        out.write_text(json.dumps(ev, indent=2, default=str))
        print(f"[bg] HARNESS_ERROR: {bug}", file=sys.stderr)
        return 3

    ev |= {
        "candidate_children_after": candidate_gpu_children(),
        "compute_apps_after": compute_apps(),
        "phases": witness,
        "run_status": getattr(result, "status", None),
        "records": [summarize_record(r) for r in (getattr(result, "all_records", None) or [])],
    }
    out.write_text(json.dumps(ev, indent=2, default=str))
    print(f"[bg] evidence written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
