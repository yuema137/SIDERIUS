"""PR-05a Stage-B + Checkpoint C — the tuner CONSUMES the run-bound profile.

Design: `docs/design/generic_framework_upgrade/step_05a_tuner_data_selection.md`
§8 (one rung, three atomic subcases) and §9 (Checkpoint C).

Every test here drives the REAL `HyperparamTuningAgent.run()`. Nothing calls
`_validate_data_config`, `validate_runtime_config` or the accounting
expression directly — §9 is explicit that a helper-only test cannot discharge
Checkpoint C, because the question is not "does the helper honour a profile"
(Step 02 already answers that) but "does production supply one".

What is real
------------
    run()
      -> resolve_dataset_profile()      REAL, the run-scope binding
      -> validate_runtime_config(...)   REAL
      -> scope_is_partial               REAL
      -> _validate_history_and_lock     REAL
      -> _validate_data_config          REAL
      -> build_sample_set               REAL
      -> legacy single_file accounting  REAL

Stubbed, and why each is downstream of the property: the LLM bridge (no API
key, no plan semantics under test), the sandbox subprocess layer (no GPU, no
training — every site under test runs before it), and the HealthGate runner
(policy, not dataset authority).

Scenario set — TWO scenarios, ONE Checkpoint C
-----------------------------------------------
`trial`/`formal` and `single_file` are selected by disjoint control flow at
`:4293-4298`, so no single invocation can reach both. §9 anticipates exactly
this and says two scenarios still constitute one checkpoint.

    C1  contrast trial run        -> B1 legality, B2 scope
    C2  contrast single_file run  -> B3 accounting

Each subcase varies ONE profile fact and holds the others at TIDMAD's values,
so a site that happened to be migrated while another was not cannot hide
behind a profile that moved everything at once.
"""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from execute_tools.dataset_config import (
    NUM_FILES,
    TIDMAD_PROFILE,
    DatasetProfile,
    bind_dataset_profile,
    tidmad_topology,
)
from nodes.ml_hyperparameter_tune_agent import HyperparamTuningAgent
from tests.helpers.scoring_stubs import stub_scoring
from tests.unit.agent.tune_ml_hyperparam_agent.test_tuning_agent import (
    FAKE_PLAN_RESPONSE,
    FAKE_PLAN_WITH_TRIAL,
    FAKE_REFLECT_RESPONSE,
    FAKE_SCORE_VECTOR_RESULT,
    _make_trial_input,
    _mock_run_skill,
    _synth_reference,
)

# ---------------------------------------------------------------------------
# Contrast profiles — each moves exactly ONE fact away from TIDMAD
# ---------------------------------------------------------------------------


def _profile(**dataset_overrides) -> DatasetProfile:
    """A TIDMAD-shaped profile with the named dataset facts replaced.

    Built through the real constructors, so the declared file sets are
    validated against the topology rather than mutated past the validator.
    """
    dataset = tidmad_topology(TIDMAD_PROFILE).dataset.model_copy(update=dataset_overrides)
    num_files = dataset.num_files
    if num_files >= tidmad_topology(TIDMAD_PROFILE).dataset.num_files:
        anchors = list(TIDMAD_PROFILE.anchor_selection_files)
        peek = list(TIDMAD_PROFILE.health_peek_files)
    else:
        anchors = [0, num_files // 2, num_files - 1]
        peek = [1, num_files // 2, num_files - 2]
    return TIDMAD_PROFILE.model_copy(
        update={
            "dataset": dataset,
            "anchor_selection_files": anchors,
            "health_peek_files": peek,
        }
    )


# B1 — legality. ONLY psd_segment_length moves. 40,000 divides TIDMAD's
# 10,000,000 exactly and leaves remainder 20,000 against 1,500,000, so the
# same planned segmentation size is legal under one topology and not the
# other.
CONTRAST_PSD = 1_500_000
LEGALITY_PROFILE = _profile(psd_segment_length=CONTRAST_PSD)
PLANNED_SEGMENTATION_SIZE = 40_000

# Hardcoded, not re-derived from `valid_segmentation_sizes()`: deriving the
# expectation from the code under test would pass for any list.
EXPECTED_CONTRAST_REJECTION = (
    "psd_segment_length (1500000) must be divisible by "
    "segmentation_size (40000). "
    "Remainder: 20000. "
    "Valid segmentation_size values: [100, 120, 125, 150, 160, 200, 240, 250, "
    "300, 375, 400, 480, 500, 600, 625, 750, 800, 1000, 1200, 1250, 1500, "
    "1875, 2000, 2400, 2500, 3000, 3125, 3750, 4000, 5000, 6000, 6250, 7500, "
    "9375, 10000, 12000, 12500, 15000, 15625, 18750, 20000, 25000, 30000, "
    "31250, 37500, 46875, 50000, 60000, 62500, 75000, 93750, 100000]."
)

# B2 — scope. ONLY num_files moves.
CONTRAST_NUM_FILES = 7
SCOPE_PROFILE = _profile(num_files=CONTRAST_NUM_FILES)

# B3 — accounting. ONLY segments_per_file moves. 57 is deliberately nothing
# like TIDMAD's 200 and is not derivable from any other declared number.
CONTRAST_SEGMENTS_PER_FILE = 57
ACCOUNTING_PROFILE = _profile(segments_per_file=CONTRAST_SEGMENTS_PER_FILE)


# ---------------------------------------------------------------------------
# Harness — the REAL tuner, under a bound profile
# ---------------------------------------------------------------------------


def _run_tuner(
    tmp_path,
    *,
    profile,
    is_trial,
    plan=None,
    seed_history=None,
    input_overrides=None,
    resolver=None,
):
    """Drive `HyperparamTuningAgent.run()` with ``profile`` bound.

    Args:
        profile: bound for the whole run via the real `ContextVar` transport.
        is_trial: the operator flag; ``False`` selects the legacy
            ``single_file`` route (with a plan that carries no ``is_trial``).
        plan: the LLM plan the stub returns.
        seed_history: records `sandbox.get_summary()` reports as pre-existing.
        input_overrides: extra `HyperparamTuningInput` fields.
        resolver: when given, replaces the tuner module's
            `resolve_dataset_profile`. Used only by the transport mutation.

    Returns a dict of everything the run made observable.
    """
    configs_dir = str(tmp_path / "configs")
    os.makedirs(configs_dir, exist_ok=True)
    saved_records: list = list(seed_history or [])

    agent_input = _make_trial_input(tmp_path, max_rounds=1, is_trial=is_trial)
    # One attempt, one fail-round. Without this the defaults retry a
    # deterministic legality rejection 15 times, which says nothing extra and
    # costs ten times the wall clock.
    agent_input.attempts_per_round = 1
    agent_input.attempts_per_formal_round = 1
    agent_input.max_fail_rounds = 1
    # HealthGate off by default here, and NOT for convenience. The shipped
    # `configs/health_checks.yaml` declares monitored files as TIDMAD file
    # indices ([3, 10, 17]); under a 7-file contrast topology
    # `validate_health_scope` rejects them as out of scope before any 05a
    # site runs. That is the HealthGate/YAML genericity gap this PR records
    # and defers (design §19.1 Finding 2) — the same remediation, for the
    # same reason, that Step 02b's Checkpoint C used. A test that worked
    # around it silently would be hiding a routed finding.
    agent_input.health_gate_enabled = False
    for field, value in (input_overrides or {}).items():
        setattr(agent_input, field, value)

    resolver_patch = (
        patch("nodes.ml_hyperparameter_tune_agent.resolve_dataset_profile", side_effect=resolver)
        if resolver is not None
        else patch("os.environ", os.environ)  # inert no-op stand-in
    )

    with (
        patch("nodes.ml_hyperparameter_tune_agent.LLMBridge") as MockBridge,
        patch("nodes.ml_hyperparameter_tune_agent.TidmadSandbox") as MockSandbox,
        patch("nodes.ml_hyperparameter_tune_agent.runtime._run_skill", side_effect=_mock_run_skill),
        patch("nodes.ml_hyperparameter_tune_agent.load_anchor_map") as mock_anchor,
        patch(
            "nodes.ml_hyperparameter_tune_agent.load_reference_scores",
            return_value=_synth_reference(),
        ),
        patch(
            "nodes.ml_hyperparameter_tune_agent.round_health.get_gates_for_position",
            return_value=[],
        ),
        patch("os.path.exists", return_value=True),
        resolver_patch,
    ):
        mock_brain = MockBridge.return_value
        mock_brain.plan.return_value = plan if plan is not None else FAKE_PLAN_RESPONSE
        mock_brain.reflect.return_value = FAKE_REFLECT_RESPONSE
        mock_anchor.return_value = {"anchors": {}, "s_max": 1.0}

        mock_sandbox = MockSandbox.return_value
        mock_sandbox.get_summary.side_effect = lambda: list(saved_records)
        mock_sandbox.save_record.side_effect = lambda r: saved_records.append(r)
        mock_sandbox.dirs = {"configs": configs_dir, "data": configs_dir}
        stub_scoring(mock_sandbox, *FAKE_SCORE_VECTOR_RESULT)

        agent = HyperparamTuningAgent()
        with bind_dataset_profile(profile):
            error = None
            try:
                output = agent.run(agent_input)
            except Exception as exc:  # surfaced to the caller, never swallowed
                output, error = None, exc

    lock_path = tmp_path / "run_invariants_lock.json"
    return {
        "records": [r for r in saved_records if r not in (seed_history or [])],
        "output": output,
        "error": error,
        "lock": json.loads(lock_path.read_text()) if lock_path.exists() else None,
        "trial_configs": [
            json.loads((Path(configs_dir) / n).read_text())
            for n in sorted(os.listdir(configs_dir))
            if n.startswith("trial_config_")
        ],
    }


def _failure_reasons(result) -> list[str]:
    return [r["failure_reason"] for r in result["records"] if r.get("status") == "error"]


# ---------------------------------------------------------------------------
# C1 / B1 — legality follows the bound profile
# ---------------------------------------------------------------------------


# The plan both B1 cases and the legality transport guard use: identical in
# every respect except the segmentation size, which is the only thing whose
# legality the bound topology decides.
LEGALITY_PLAN = {
    **FAKE_PLAN_WITH_TRIAL,
    "model_config": {
        **FAKE_PLAN_WITH_TRIAL["model_config"],
        "segmentation_size": PLANNED_SEGMENTATION_SIZE,
    },
}


class TestB1Legality:
    """Varies ONLY `psd_segment_length`."""

    def test_a_size_legal_under_tidmad_is_rejected_under_the_bound_topology(self, tmp_path):
        """The defect this closes, stated as a behaviour.

        40,000 divides TIDMAD's PSD length. Under a bound topology whose PSD
        length it does not divide, the attempt must be rejected — and with
        the BOUND topology's numbers in the diagnostic, not TIDMAD's. A tuner
        still reading the singleton accepts this attempt outright.
        """
        result = _run_tuner(tmp_path, profile=LEGALITY_PROFILE, is_trial=True, plan=LEGALITY_PLAN)

        reasons = _failure_reasons(result)
        assert reasons, (
            "the attempt was accepted under a topology whose PSD length "
            f"{CONTRAST_PSD} is not divisible by {PLANNED_SEGMENTATION_SIZE} — "
            "legality was decided against the ambient TIDMAD topology"
        )
        assert reasons[0] == EXPECTED_CONTRAST_REJECTION

    def test_the_same_size_is_accepted_under_tidmad(self, tmp_path):
        """The control.

        Without it, a test that rejected EVERY size would look like proof.
        """
        result = _run_tuner(tmp_path, profile=TIDMAD_PROFILE, is_trial=True, plan=LEGALITY_PLAN)

        assert not _failure_reasons(result), (
            "a legal TIDMAD segmentation size was rejected — the migration "
            "changed the legality verdict rather than its authority"
        )
        assert result["output"] is not None and result["output"].status == "completed"


# ---------------------------------------------------------------------------
# C1 / B2 — scope follows the bound profile
# ---------------------------------------------------------------------------


class TestB2Scope:
    """Varies ONLY `num_files`.

    Both scope consumers are asserted, because they compute the SAME
    predicate from the same fact and a half-migration makes them disagree:

    * `validate_runtime_config` resolves the DataScope and decides
      full-vs-partial (design §19.1 Finding 1);
    * the tuner's own `scope_is_partial`;
    * `_validate_history_and_lock`'s `full_scope`, which decides what an
      UNSTAMPED legacy record is assumed to have been produced under.
    """

    def test_the_stamped_scope_is_the_bound_topology(self, tmp_path):
        """The run-invariants lock is the persisted, operator-visible form."""
        result = _run_tuner(tmp_path, profile=SCOPE_PROFILE, is_trial=True)

        assert result["error"] is None, f"run failed: {result['error']}"
        assert result["lock"] is not None, "no run-invariants lock was stamped"
        assert result["lock"]["resolved_data_scope"] == list(range(CONTRAST_NUM_FILES))

    def test_an_explicit_full_scope_is_not_misread_as_partial(self, tmp_path, capsys):
        """The exact incoherence Step 02b recorded and 05a closes.

        Files 0-6 are the WHOLE of a 7-file topology. Against TIDMAD's 20 they
        look like a subset, and a partial scope may only use the `snapshot`
        formal strategy — operator configuration is a contract there, not
        something the tuner normalizes. So with `formal_strategy="anchors"` a
        tuner whose scope resolution still reads the singleton refuses this
        run outright with that diagnostic, while the migrated one classifies
        the scope as full and proceeds.

        Both scope predicates are asserted, because a half-migration makes
        them disagree rather than fail:
          * `validate_runtime_config`'s — the verdict;
          * the tuner's own `scope_is_partial` — the "[DATASCOPE] Partial
            scope active" line, which is its only observable.
        """
        from execute_tools.dataset_config import DataScope

        result = _run_tuner(
            tmp_path,
            profile=SCOPE_PROFILE,
            is_trial=True,
            input_overrides={
                "data_scope": DataScope(file_indices=list(range(CONTRAST_NUM_FILES))),
                "formal_strategy": "anchors",
            },
        )

        assert result["error"] is None, (
            "a scope covering every file of the bound topology was refused as "
            f"partial — scope resolution used the ambient topology: {result['error']}"
        )
        assert result["lock"]["resolved_data_scope"] == list(range(CONTRAST_NUM_FILES))
        assert "[DATASCOPE] Partial scope active" not in capsys.readouterr().out, (
            "the tuner classified a complete scope as partial — `scope_is_partial` "
            "was computed against the ambient topology"
        )

    def test_a_genuinely_partial_scope_is_still_detected(self, tmp_path, capsys):
        """The control for the test above.

        Without it, a `scope_is_partial` that had been hardwired to False
        would look like a pass. Files 0-3 are a real subset of the bound
        7-file topology, so partial detection must still fire.
        """
        from execute_tools.dataset_config import DataScope

        result = _run_tuner(
            tmp_path,
            profile=SCOPE_PROFILE,
            is_trial=True,
            input_overrides={"data_scope": DataScope(file_indices=[0, 1, 2, 3])},
        )

        assert result["error"] is None, f"run failed: {result['error']}"
        assert "[DATASCOPE] Partial scope active" in capsys.readouterr().out

    def test_an_unstamped_legacy_record_is_judged_against_the_bound_full_scope(self, tmp_path):
        """`_validate_history_and_lock`'s `full_scope`, on the live path.

        A record with no `resolved_data_scope` predates DataScope and is
        assumed to have been produced under the FULL scope. "Full" is only
        meaningful relative to this run's topology: judged against TIDMAD's
        twenty files the assumed scope contradicts the run's seven and the
        ingress check fails the run closed.

        The branch is reached the way production reaches it — a workspace
        with history but no lock — not by calling the helper.
        """
        legacy_record = {
            "exp_id": "legacy_001",
            "status": "success",
            "model_type": "punet",
            "denoising_score": 1.0,
            # `resolved_data_scope` is deliberately ABSENT — that absence is
            # the whole subject: it is what makes `full_scope` load-bearing.
            # `health_gate_enabled` IS stamped, because an unstamped gate flag
            # is separately assumed to mean "gates active" and would fail this
            # run on a stamp that has nothing to do with dataset topology.
            "health_gate_enabled": False,
        }

        result = _run_tuner(
            tmp_path,
            profile=SCOPE_PROFILE,
            is_trial=True,
            seed_history=[legacy_record],
        )

        assert result["error"] is None, (
            "an unstamped legacy record was judged against the ambient "
            f"full scope rather than the bound topology's: {result['error']}"
        )

    def test_a_scope_outside_the_bound_topology_is_still_rejected(self, tmp_path):
        """The migration must not soften the out-of-range rejection.

        File 9 exists under TIDMAD and does not exist under the bound
        topology. Reading the singleton would silently accept it.
        """
        from execute_tools.dataset_config import DataScope

        result = _run_tuner(
            tmp_path,
            profile=SCOPE_PROFILE,
            is_trial=True,
            input_overrides={"data_scope": DataScope(file_indices=[0, 9])},
        )

        assert result["error"] is not None, (
            "a file index the bound topology does not have was accepted"
        )
        assert f"num_files={CONTRAST_NUM_FILES}" in str(result["error"])


# ---------------------------------------------------------------------------
# C2 / B3 — legacy single_file accounting follows the bound profile
# ---------------------------------------------------------------------------


class TestB3LegacyAccounting:
    """Varies ONLY `segments_per_file`, through the LIVE legacy route."""

    def test_the_live_single_file_counts_follow_the_bound_profile(self, tmp_path):
        result = _run_tuner(tmp_path, profile=ACCOUNTING_PROFILE, is_trial=False)

        assert result["trial_configs"], "no attempt ran"
        assert result["trial_configs"][0]["mode"] == "single_file", (
            "the run did not take the legacy route, so this proves nothing "
            "about the accounting branch"
        )

        record = result["records"][0]
        assert record["training_psd_segments"] == CONTRAST_SEGMENTS_PER_FILE
        assert record["eval_psd_segments"] == CONTRAST_SEGMENTS_PER_FILE

    def test_the_legacy_branch_is_still_reachable_and_was_not_deleted(self, tmp_path):
        """§16: the live path is MIGRATED, never removed.

        Under TIDMAD the counts must be exactly what they were before 05a —
        the Checkpoint-0 baseline value, hardcoded here rather than read from
        the profile.
        """
        result = _run_tuner(tmp_path, profile=TIDMAD_PROFILE, is_trial=False)

        assert result["trial_configs"][0]["mode"] == "single_file"
        assert result["records"][0]["training_psd_segments"] == 200
        assert result["records"][0]["eval_psd_segments"] == 200


# ---------------------------------------------------------------------------
# Transport — no consumer independently re-resolves (§10.2, §8.1)
# ---------------------------------------------------------------------------


class TestRunBoundTransport:
    """The failure class no per-site test can catch.

    Every site could read *a* profile and still be broken, if each read its
    own. The guard poisons ambient re-resolution: the first resolution
    returns the bound profile, every later one returns TIDMAD. A run whose
    consumers all use the run binding is unaffected; a consumer that resolves
    on its own authority silently switches topology mid-run.

    Deliberately NOT a call-count assertion (§4, §10.2): the frozen contract
    is that consumers share one binding, and pinning the count would forbid a
    legitimate memoized or re-entrant implementation.
    """

    @staticmethod
    def _poisoned(profile):
        calls = {"n": 0}

        def _resolve():
            calls["n"] += 1
            return profile if calls["n"] == 1 else TIDMAD_PROFILE

        return _resolve

    def test_accounting_survives_a_poisoned_second_resolution(self, tmp_path):
        result = _run_tuner(
            tmp_path,
            profile=ACCOUNTING_PROFILE,
            is_trial=False,
            resolver=self._poisoned(ACCOUNTING_PROFILE),
        )

        assert result["records"][0]["training_psd_segments"] == CONTRAST_SEGMENTS_PER_FILE, (
            "the accounting site re-resolved the profile instead of consuming the run binding"
        )
        assert result["records"][0]["eval_psd_segments"] == CONTRAST_SEGMENTS_PER_FILE

    def test_scope_survives_a_poisoned_second_resolution(self, tmp_path):
        result = _run_tuner(
            tmp_path,
            profile=SCOPE_PROFILE,
            is_trial=True,
            resolver=self._poisoned(SCOPE_PROFILE),
        )

        assert result["error"] is None, f"run failed: {result['error']}"
        assert result["lock"]["resolved_data_scope"] == list(range(CONTRAST_NUM_FILES)), (
            "a scope consumer re-resolved the profile instead of consuming the run binding"
        )

    def test_legality_survives_a_poisoned_second_resolution(self, tmp_path):
        result = _run_tuner(
            tmp_path,
            profile=LEGALITY_PROFILE,
            is_trial=True,
            plan=LEGALITY_PLAN,
            resolver=self._poisoned(LEGALITY_PROFILE),
        )

        reasons = _failure_reasons(result)
        assert reasons, "no legality rejection was recorded at all"
        assert set(reasons) == {EXPECTED_CONTRAST_REJECTION}, (
            "the legality site re-resolved the profile instead of consuming "
            f"the run binding: {sorted(set(reasons))}"
        )


# ---------------------------------------------------------------------------
# Supporting mechanical evidence (§17 M3) — NOT the property
# ---------------------------------------------------------------------------


def test_the_tuner_no_longer_imports_the_dataset_singleton():
    """Supporting evidence only, and the design says so explicitly.

    A renamed alias or an `import execute_tools.dataset_config` attribute
    access would leave this clean while the defect survived — which is why
    the semantic guards above, not this one, carry the weight.
    """
    source = Path("nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py")
    repo_root = Path(__file__).resolve().parents[4]
    text = (repo_root / source).read_text()

    offenders = [
        line.strip()
        for line in text.splitlines()
        if "import" in line and "dataset_config" in line and "TIDMAD" in line
    ]
    assert offenders == [], f"the tuner still imports the dataset singleton: {offenders}"


@pytest.mark.parametrize(
    "fact,contrast,tidmad",
    [
        ("psd_segment_length", CONTRAST_PSD, 10_000_000),
        ("num_files", CONTRAST_NUM_FILES, 20),
        ("segments_per_file", CONTRAST_SEGMENTS_PER_FILE, 200),
    ],
)
def test_each_subcase_moves_exactly_one_fact(fact, contrast, tidmad):
    """Atomicity of the three subcases, asserted rather than asserted-in-prose.

    §8: a profile that moved all three facts at once would still pass if any
    two sites were migrated and the third happened to agree. If a future edit
    quietly widened one of these fixtures, that protection would evaporate
    silently — this is the only thing that would notice.
    """
    profiles = {
        "psd_segment_length": LEGALITY_PROFILE,
        "num_files": SCOPE_PROFILE,
        "segments_per_file": ACCOUNTING_PROFILE,
    }
    profile = profiles[fact]
    assert getattr(tidmad_topology(profile).dataset, fact) == contrast

    for other in ("psd_segment_length", "num_files", "segments_per_file"):
        if other == fact:
            continue
        expected = {"psd_segment_length": 10_000_000, "num_files": 20, "segments_per_file": 200}[
            other
        ]
        assert getattr(tidmad_topology(profile).dataset, other) == expected, (
            f"the {fact} fixture also moved {other} — the subcase is no longer atomic"
        )
    assert tidmad == getattr(tidmad_topology(TIDMAD_PROFILE).dataset, fact)
