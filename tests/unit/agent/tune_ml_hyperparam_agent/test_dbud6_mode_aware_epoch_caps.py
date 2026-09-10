"""D-BUD-6: mode-aware epoch ceilings.

The retained regression fixture uses ``trial_max_epochs=2 / formal_max_epochs=1`` as two
CEILINGS keyed on the round's trial/formal role. The mechanism:
``HyperparamTuningInput.trial_max_epochs`` / ``formal_max_epochs`` resolve
through the ONE authority ``resolve_epoch_cap(is_trial=...)`` (precedence:
per-mode value -> mode-agnostic ``max_epochs`` -> no clamp), and the planning
clamp keys on ``plan.is_trial`` AFTER the mode-override chain — the same
authority that stamps ``record.is_trial`` (PR #217).

Each witness names the defect ONLY it can catch:

* **(a) role split through the REAL clamp site** — one bounded pseudo run of
  the PRODUCTION tuner with ``trial_max_epochs=2, formal_max_epochs=1`` and
  every canned plan requesting 10 epochs: the trial records carry epochs 2
  and the formal record carries epochs 1. The role is resolved by the round
  machinery itself (round 2 is the forced-formal last round), never a
  hand-set boolean — so a clamp keyed on the wrong authority (or on a
  parallel derivation such as ``memory.time_mode``) fails here and nowhere
  else.
* **(b) legacy differential** — with the per-mode fields ABSENT, the clamp
  decision for BOTH roles is byte-identical to invoking the pre-change
  clamp directly with ``max_epochs``, across a planned-epochs x cap grid.
  (The Step-00 REC/WF byte-baselines replay the un-capped legacy pseudo run
  in this same suite and independently pin that nothing else moved.)
* **(c) transport** — the two hops no other file guards: the workflow ->
  protocol call site forwards BOTH fields from ``launch`` (the F2
  ownership-gap class: a split value with an unowned hop ships silently
  disabled), and the tuner-node CLI (route B: ``run_comparison.py`` spawns
  the node script) lands ``--trial_max_epochs 2 --formal_max_epochs 1`` on
  the validated input. The chain/app hops (route A) are guarded by
  ``test_chain_consistency.py`` (name/default/type parity) and
  ``test_run_one_iteration.py`` (Namespace values + parse refusals); the
  campaign emission by ``test_gold_campaign_entrypoint.py``.
* **(d) refusal reachability, route B** — the node CLI forwards a zero
  per-mode value INTO the validated schema, so ``build_agent_input``
  refuses it loudly (``ge=1``). The parse-time refusal on route A
  (``_positive_int``) lives beside the flags in
  ``test_run_one_iteration.py``.
* **prompt honesty** — with per-mode caps configured the FIXED block shows
  the pair of clamp-effective ceilings (a prompt still saying "<= 1" would
  steer the planner under the trial ceiling and make trial-2 unreachable);
  with no per-mode cap the legacy line renders byte-identically
  (hardcoded expectation, never read back from the renderer).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import nodes.ml_hyperparameter_tune_agent as tuner
from agent.prompts import _format_fixed_params_block
from agent.schemas.hyperparam_tuning import HyperparamTuningInput
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from tests.helpers._pseudo_data import load_pseudo_data
from tests.helpers.recording_llm_bridge import RecordingLLMBridge
from tests.helpers.step00_pseudo_iteration import (
    PSEUDO_AGENT_FOLDER,
    run_bounded_pseudo_iteration,
)

_PREFLIGHT_FIXTURE = Path(__file__).parent / "fixtures" / "step00_preflight_results.json"
_REPO_ROOT = Path(__file__).resolve().parents[4]


def _required_cli_args() -> list[str]:
    return [
        "--task_composition",
        str(_REPO_ROOT / "configs" / "task_composition" / "quickstart.yaml"),
        "--data_dir",
        "/tmp/dbud6_data",
    ]


def _minimal_input(**overrides) -> HyperparamTuningInput:
    return HyperparamTuningInput(
        model_type="punet",
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace="/tmp/dbud6", run_name="dbud6"),
        ),
        **overrides,
    )


# ---------------------------------------------------------------------------
# (a) trial clamps at 2 while formal clamps at 1 — ONE run configuration,
#     the REAL clamp site, the round machinery's own role authority
# ---------------------------------------------------------------------------


class TestWitnessARoleSplitThroughTheRealClampSite:
    def _epoch_hungry_bridge(self) -> RecordingLLMBridge:
        """The k9 canned queue with every plan asking for 10 epochs.

        With the fixture's own plans (epochs=1) the clamp would never have
        to DECIDE — min(1, cap) is 1 for both roles and a clamp keyed on
        the wrong role authority would still pass. 10 exceeds both frozen
        ceilings, so the per-record effective value IS the per-role cap.
        """
        responses = load_pseudo_data("api_call_outputs", PSEUDO_AGENT_FOLDER)
        for plan in responses["generate"]:
            plan["train_config"]["epochs"] = 10
        return RecordingLLMBridge(responses=responses)

    def test_trial_records_cap_at_2_and_the_formal_record_at_1(self, tmp_path, monkeypatch):
        preflight = json.loads(_PREFLIGHT_FIXTURE.read_text(encoding="utf-8"))["results"]
        output, _bridge, _sandbox, _ws = run_bounded_pseudo_iteration(
            tmp_path,
            monkeypatch,
            preflight_results=preflight,
            bridge=self._epoch_hungry_bridge(),
            input_overrides={"trial_max_epochs": 2, "formal_max_epochs": 1},
        )

        # Role selection is over SUCCESS records: `record.is_trial` is the
        # candidate-role authority and only success records stamp it — a
        # skip record carries no is_trial key by shape ("absence ==
        # formal", records.py), so selecting the OOM-skip by that flag
        # would misread its round role. Its clamp evidence is asserted
        # separately below.
        successes = [r for r in output.all_records if r.status == "success"]
        trial_records = [r for r in successes if r.is_trial]
        formal_records = [r for r in successes if not r.is_trial]
        assert trial_records, "the bounded iteration must produce a trial success record"
        assert formal_records, "the bounded iteration must produce a formal success record"

        for record in trial_records:
            assert record.params["train_config"]["epochs"] == 2, (
                f"trial record {record.exp_id}: expected the D-BUD-6 trial ceiling 2, "
                f"got {record.params['train_config']['epochs']} — the clamp did not "
                "key on the round's trial role"
            )
        for record in formal_records:
            assert record.params["train_config"]["epochs"] == 1, (
                f"formal record {record.exp_id}: expected the D-BUD-6 formal ceiling 1, "
                f"got {record.params['train_config']['epochs']} — the clamp did not "
                "key on the round's formal role"
            )

        # The OOM-skip attempt belongs to a TRIAL round and its persisted
        # config already carries the trial ceiling: the clamp fires at the
        # plan boundary, BEFORE admission — an attempt rejected for
        # resources was still priced on the capped workload.
        skips = [r for r in output.all_records if r.status == "skipped_oom_risk"]
        assert skips, "the k9 queue's first attempt is the OOM-skip"
        for record in skips:
            assert record.params["train_config"]["epochs"] == 2


# ---------------------------------------------------------------------------
# (b) legacy differential — per-mode fields absent ⇒ clamp decisions
#     byte-identical to the pre-change mode-agnostic clamp, for BOTH roles
# ---------------------------------------------------------------------------


class TestWitnessBLegacyDifferential:
    @pytest.mark.parametrize("max_epochs", [None, 1, 5])
    @pytest.mark.parametrize(
        "planned", [{}, {"epochs": 1}, {"epochs": 10}, {"epochs": 50}], ids=str
    )
    @pytest.mark.parametrize("is_trial", [True, False])
    def test_clamp_decisions_match_the_mode_agnostic_clamp(self, max_epochs, planned, is_trial):
        """Drives PRODUCTION's ``_apply_epoch_bound`` twice: once with the
        cap resolved through the new authority (per-mode fields unset) and
        once exactly as the pre-D-BUD-6 call site did. Any divergence —
        value, write-back, or return — is a silent legacy behavior change."""
        agent_input = (
            _minimal_input(max_epochs=max_epochs) if max_epochs is not None else _minimal_input()
        )
        resolution = agent_input.resolve_epoch_cap(is_trial=is_trial)

        via_authority = dict(planned)
        returned_new = tuner._apply_epoch_bound(
            via_authority, resolution.cap, source=resolution.source or "max_epochs"
        )
        legacy = dict(planned)
        returned_old = tuner._apply_epoch_bound(legacy, max_epochs)

        assert via_authority == legacy
        assert returned_new == returned_old

    def test_the_resolution_source_is_the_legacy_field(self):
        """With no per-mode cap, BOTH roles resolve to max_epochs — and say
        so. A resolution naming a per-mode source here would relabel every
        legacy clamp log line."""
        agent_input = _minimal_input(max_epochs=3)
        for is_trial in (True, False):
            resolution = agent_input.resolve_epoch_cap(is_trial=is_trial)
            assert resolution == (3, "max_epochs")

    def test_per_mode_precedence_and_the_unbounded_corner(self):
        """The resolution table, hardcoded: per-mode wins over max_epochs
        for its OWN role only; a role with neither cap is unbounded."""
        both = _minimal_input(max_epochs=1, trial_max_epochs=2, formal_max_epochs=1)
        assert both.resolve_epoch_cap(is_trial=True) == (2, "trial_max_epochs")
        assert both.resolve_epoch_cap(is_trial=False) == (1, "formal_max_epochs")

        trial_only = _minimal_input(trial_max_epochs=2)
        assert trial_only.resolve_epoch_cap(is_trial=True) == (2, "trial_max_epochs")
        assert trial_only.resolve_epoch_cap(is_trial=False) == (None, None)

        formal_only = _minimal_input(max_epochs=4, formal_max_epochs=1)
        assert formal_only.resolve_epoch_cap(is_trial=True) == (4, "max_epochs")
        assert formal_only.resolve_epoch_cap(is_trial=False) == (1, "formal_max_epochs")


# ---------------------------------------------------------------------------
# (c) transport — the hops no other file guards
# ---------------------------------------------------------------------------


class TestWitnessCTransportHops:
    def test_protocol_signature_carries_both_fields(self):
        """A field on the launch config that the protocol cannot accept is
        the F2 shape: emitted upstream, dropped at an unowned hop."""
        import inspect

        from agent.schemas.protocols.ml_model_valid_to_ml_model_tune import (
            local_validated_model,
        )

        params = set(inspect.signature(local_validated_model).parameters)
        assert "trial_max_epochs" in params
        assert "formal_max_epochs" in params

    def test_workflow_forwards_both_fields_from_launch(self):
        """The workflow -> protocol call site forwards ``launch.<field>``
        for BOTH fields (same guard shape as
        test_watchdog_admission_split's kwarg-forwarding witness): the one
        hop where a missing line would ship the feature silently disabled
        while every schema and CLI test stayed green."""
        import inspect

        import workflows.model_exploration as mx

        src = inspect.getsource(mx)
        assert "trial_max_epochs=launch.trial_max_epochs" in src
        assert "formal_max_epochs=launch.formal_max_epochs" in src

    def test_node_cli_lands_the_pair_on_the_validated_input(self):
        """Route B (run_comparison.py -> tuner-node argv): the node's own
        argparse + input builder must land trial=2 / formal=1 on the
        VALIDATED HyperparamTuningInput."""
        from nodes.ml_hyperparameter_tune_agent.cli import build_agent_input, build_parser

        parser = build_parser()
        args = parser.parse_args(
            [
                "--force_model",
                "punet",
                "--workspace",
                "/tmp/dbud6_cli",
                "--run_name",
                "dbud6_cli",
                *_required_cli_args(),
                "--is_trial",
                "--max_epochs",
                "1",
                "--trial_max_epochs",
                "2",
                "--formal_max_epochs",
                "1",
            ]
        )
        agent_input = build_agent_input(args, parser)
        assert agent_input.max_epochs == 1
        assert agent_input.trial_max_epochs == 2
        assert agent_input.formal_max_epochs == 1

    def test_node_cli_omission_leaves_the_schema_defaults(self):
        """Route B legacy invocations must not silently activate the split:
        omitted flags leave both fields None (mode-agnostic max_epochs
        governs), the pre-D-BUD-6 posture."""
        from nodes.ml_hyperparameter_tune_agent.cli import build_agent_input, build_parser

        parser = build_parser()
        args = parser.parse_args(
            [
                "--force_model",
                "punet",
                "--workspace",
                "/tmp/dbud6_cli",
                "--run_name",
                "dbud6_cli",
                *_required_cli_args(),
                "--is_trial",
                "--max_epochs",
                "1",
            ]
        )
        agent_input = build_agent_input(args, parser)
        assert agent_input.trial_max_epochs is None
        assert agent_input.formal_max_epochs is None


# ---------------------------------------------------------------------------
# (d) refusal reachability on route B
# ---------------------------------------------------------------------------


class TestWitnessDRefusalReachability:
    @pytest.mark.parametrize("flag", ["--trial_max_epochs", "--formal_max_epochs"])
    def test_zero_refuses_loudly_through_the_node_cli(self, flag):
        """The node CLI uses ``type=int`` (unlike run_one_iteration's
        ``_positive_int``), so its refusal IS the schema's ``ge=1`` — this
        proves the CLI actually routes the value through the validated
        schema instead of accepting a zero ceiling that would disable one
        role's training."""
        import pydantic

        from nodes.ml_hyperparameter_tune_agent.cli import build_agent_input, build_parser

        parser = build_parser()
        args = parser.parse_args(
            [
                "--force_model",
                "punet",
                "--workspace",
                "/tmp/dbud6_cli",
                "--run_name",
                "dbud6_cli",
                *_required_cli_args(),
                "--is_trial",
                flag,
                "0",
            ]
        )
        with pytest.raises(pydantic.ValidationError) as excinfo:
            build_agent_input(args, parser)
        assert flag.lstrip("-") in str(excinfo.value)


# ---------------------------------------------------------------------------
# prompt honesty — the FIXED block
# ---------------------------------------------------------------------------


class TestPromptDisclosure:
    LEGACY_LINE = "  epochs (cap)     ≤ 1      ← higher values are clamped"
    PAIR_LINE = (
        "  epochs (cap)     ≤ 2 (trial) / ≤ 1 (formal)"
        "      ← per-round-mode ceilings; higher values are clamped"
    )

    def test_legacy_rendering_is_byte_identical_without_per_mode_caps(self):
        block = _format_fixed_params_block(None, 1)
        assert self.LEGACY_LINE in block
        assert "(trial)" not in block

    def test_pair_line_replaces_the_single_cap_line(self):
        """The pair carries the clamp-effective values; keeping the
        shadowed "<= 1" single line beside it would tell the planner the
        fallback still governs."""
        block = _format_fixed_params_block(None, 1, trial_max_epochs=2, formal_max_epochs=1)
        assert self.PAIR_LINE in block
        assert self.LEGACY_LINE not in block

    def test_an_uncapped_role_is_disclosed_as_unbounded(self):
        block = _format_fixed_params_block(None, None, trial_max_epochs=2)
        assert "≤ 2 (trial) / unbounded (formal)" in block

    def test_planning_disclosure_uses_the_one_resolution_authority(self):
        """The prompt values and the clamp values may not be computed by two
        different rules: the planning module must derive BOTH from
        ``resolve_epoch_cap``. Re-deriving the precedence inline in the
        prompt path is the two-copies drift this pins against."""
        import importlib
        import inspect

        # importlib because the package __init__ re-exports shadow the
        # module name (same quirk the step00 pseudo harness works around).
        planning = importlib.import_module("nodes.ml_hyperparameter_tune_agent.planning")

        src = inspect.getsource(planning)
        assert "agent_input.resolve_epoch_cap(is_trial=True).cap" in src
        assert "agent_input.resolve_epoch_cap(is_trial=False).cap" in src


pytestmark = pytest.mark.usefixtures("synthetic_run_authorities")
