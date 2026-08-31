"""F-LAUNCH-1 — the canonical Gold campaign entrypoint (contract PR #329).

Each test names the defect ONLY it can catch:

* ``TestFrozenLlmRouting`` — F-LLM-WIRE-1 (release blocker): the historical
  Stage-2 path binds the frozen routing config, the runner's REAL parser +
  ``WorkflowLLMConfig`` resolve the pinned snapshot model, and the
  non-campaign chain default still legitimately omits the flag. The
  defect class: ``--llm_config`` is optional at every hop, so omitting it
  ran the entire official campaign on the deprecated all-Gemini default
  while still exiting 0 — the pin was real and nothing consumed it.
* ``TestGenericRetentionCompatibility`` — the exploratory chain default
  still cleans up, the typed retention token suppresses that cleanup, and
  SDSc mode refuses retention it cannot honor.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SDSC = REPO_ROOT / "sdsc_submission_scripts"
ENTRYPOINT = SDSC / "run_gold_campaign.sh"
CHAIN_COMMON = SDSC / "_chain_common.sh"
RUN_CHAIN = SDSC / "run_chain.sh"

#: The campaign's frozen LLM routing authority (D-LLM-1). HARDCODED here for
#: the same reason the nineteen are: reading the path back out of the lib
#: would compare the declaration to itself.
FROZEN_LLM_CONFIG_RELPATH = "llm_configs/openai_tiered_pro.json"
FROZEN_LLM_CONFIG = REPO_ROOT / FROZEN_LLM_CONFIG_RELPATH

#: The snapshot model D-LLM-1 pins every campaign LLM role to, and the
#: deprecated default that silently stands in when --llm_config is omitted.
PINNED_MODEL_ID = "gpt-5.5-2026-04-23"
UNPINNED_DEFAULT_MODEL_ID = "gemini-3.1-pro-preview"


def _bash(*argv: str, env: dict | None = None) -> subprocess.CompletedProcess:
    merged = dict(os.environ)
    merged.pop("CUDA_VISIBLE_DEVICES", None)
    if env:
        merged.update({k: str(v) for k, v in env.items()})
    return subprocess.run(
        ["bash", *argv],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=merged,
        timeout=180,
    )


@pytest.fixture
def campaign_root(tmp_path: Path) -> dict:
    root = tmp_path / "ws"
    root.mkdir()
    advice = tmp_path / "advice.json"
    advice.write_text('{"propose": "placeholder"}\n')
    return {"root": root, "advice": advice}


def _stage1_dry(campaign_root: dict, *extra: str) -> subprocess.CompletedProcess:
    return _bash(
        str(ENTRYPOINT),
        "--workspace_root",
        str(campaign_root["root"]),
        "--stage",
        "1",
        "--gold_advice_file",
        str(campaign_root["advice"]),
        "--dry-run",
        *extra,
    )


def _band_argvs(stdout: str) -> dict[str, list[str]]:
    """Parse the dry-run's ``band <B> run_chain argv:`` blocks."""
    argvs: dict[str, list[str]] = {}
    lines = stdout.splitlines()
    for i, line in enumerate(lines):
        if "run_chain argv:" in line and "[gold-band]" in line:
            # "[gold-band] band 0-3 run_chain argv:" — split on the spaced
            # word, because "gold-band" itself contains "band".
            band = line.split(" band ")[1].split(" run_chain")[0].strip()
            argvs[band] = shlex.split(lines[i + 1])
    return argvs


def _pairs(argv: list[str]) -> dict[str, str]:
    out = {}
    for i, tok in enumerate(argv):
        if tok.startswith("--") and i + 1 < len(argv):
            out.setdefault(tok, argv[i + 1])
    return out


class TestBypassTransportCompatibility:
    def test_chain_side_probe_condition_holds_at_this_head(self):
        """The ownership-gap witness (F2 finding): the chain-side parse +
        emission for the bypass ceiling once ended up owned by NOBODY —
        each lane believed the other owned the hop — and without these
        lines the entrypoint's probe would self-disable FOREVER, running
        every campaign bypass-less with only a stderr NOTE and exit 0 (the
        silent-fallback class). RED again if the parse arm is descoped.

        Asserted BEHAVIORALLY through the production builder, not just
        bytes: typed -> the pair reaches the child argv; empty -> omitted
        (the tri-state, matching run_one_iteration's None default)."""
        assert "--bypass_formal_time_budget_minutes)" in CHAIN_COMMON.read_text(), (
            "the chain-side parse arm for --bypass_formal_time_budget_minutes is gone "
            "(folded from 378a68db); the entrypoint probe would silently self-disable"
        )
        typed = _bash(
            "-c",
            f"source '{CHAIN_COMMON}'; "
            "parse_chain_args --workspace /tmp/x --run_name t "
            "--bypass_formal_time_budget_minutes 200; "
            'build_app_args 1; printf "%s\\n" "${APP_ARGS[@]}"',
        )
        assert typed.returncode == 0, typed.stderr
        tokens = typed.stdout.splitlines()
        assert "--bypass_formal_time_budget_minutes" in tokens
        assert tokens[tokens.index("--bypass_formal_time_budget_minutes") + 1] == "200"
        untyped = _bash(
            "-c",
            f"source '{CHAIN_COMMON}'; "
            "parse_chain_args --workspace /tmp/x --run_name t; "
            'build_app_args 1; printf "%s\\n" "${APP_ARGS[@]}"',
        )
        assert untyped.returncode == 0, untyped.stderr
        assert "--bypass_formal_time_budget_minutes" not in untyped.stdout.splitlines()


class TestFrozenLlmRouting:
    """F-LLM-WIRE-1 — the campaign path BINDS the frozen LLM routing config.

    The defect this closes is the declared-but-unconsumed class, and its
    whole danger is that the failure mode is SILENT: `--llm_config` is
    optional at every hop (`_chain_common.sh` LLM_CONFIG="" forwards
    nothing; `run_one_iteration.py` falls back to
    `WorkflowLLMConfig.uniform("gemini", --llm_model)`), so a campaign
    launched without it runs every LLM role on the deprecated
    all-Gemini default, exits 0, and produces records that look normal.
    The pin was real and the config was correct — nothing on the campaign
    path consumed it.
    """

    def test_runner_resolves_the_pinned_model_not_the_gemini_default(self, campaign_root):
        """Witness (b): drive the REAL transport, end to end.

        The launcher's own emitted argv is walked through the production
        hops — `_chain_common.sh` parse + `build_app_args`, then
        `run_one_iteration.py`'s REAL argparse, then the SAME
        `WorkflowLLMConfig.from_json` branch the runner takes at
        `args.llm_config` — and every campaign-active role must land on the
        pinned snapshot. Asserting on strings would prove only that a path
        was copied around; this proves a model was actually selected.

        The negative half is what makes it a witness rather than a
        tautology: the identical parser with the flag ABSENT resolves every
        one of those roles to the deprecated default, which is exactly what
        the campaign was doing."""
        pytest.importorskip("pydantic")
        import importlib.util

        proc = _stage1_dry(campaign_root)
        assert proc.returncode == 0, proc.stderr + proc.stdout
        argv = _band_argvs(proc.stdout)["0-3"]
        # argv = ["CUDA_VISIBLE_DEVICES=0", "bash", "<run_chain.sh>", ...]
        chain_args = argv[3:]
        built = _bash(
            "-c",
            f"source '{CHAIN_COMMON}'; "
            f"parse_chain_args {' '.join(shlex.quote(a) for a in chain_args)}; "
            'build_app_args 1; printf "%s\\n" "${APP_ARGS[@]}"',
        )
        assert built.returncode == 0, built.stderr
        app_args = [tok for tok in built.stdout.splitlines() if tok]

        spec = importlib.util.spec_from_file_location(
            "roi_for_llm_wire_test", SDSC / "run_one_iteration.py"
        )
        roi = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(roi)
        from workflows.llm_config import WorkflowLLMConfig

        ns = roi.build_parser().parse_args(app_args)
        assert ns.llm_config == str(FROZEN_LLM_CONFIG)

        # The production branch (run_one_iteration.py: `if args.llm_config`).
        pinned = WorkflowLLMConfig.from_json(ns.llm_config)
        # lit_review is deliberately excluded: Q-LIT-1 is OFF in both arms,
        # and the shipped config routes it elsewhere on purpose.
        campaign_roles = ("interpret", "propose", "implement", "validate", "tune")
        for role in campaign_roles:
            resolved = pinned.get(role)
            model_ids = {v for k, v in resolved.items() if k.endswith("model_id")}
            assert model_ids == {PINNED_MODEL_ID}, (role, resolved)

        # The negative half — the same parser, the flag omitted.
        bare = roi.build_parser().parse_args(["--workspace", "/tmp/x", "--run_name", "t"])
        assert bare.llm_config is None
        unpinned = WorkflowLLMConfig.uniform("gemini", bare.llm_model)
        for role in campaign_roles:
            resolved = unpinned.get(role)
            model_ids = {v for k, v in resolved.items() if k.endswith("model_id")}
            assert model_ids == {UNPINNED_DEFAULT_MODEL_ID}, (role, resolved)

    def test_exploratory_chain_launch_still_omits_llm_config(self):
        """Witness (d), the differential: LLM_CONFIG="" stays legal OFF the
        campaign path.

        The general chain default must not be dragged into the campaign's
        refusal — exploratory and non-campaign runs legitimately launch
        without a routing config, and forwarding an empty value would put a
        bare `--llm_config` on the child argv and crash argparse."""
        proc = _bash(
            "-c",
            f"source '{CHAIN_COMMON}'; "
            "parse_chain_args --workspace /tmp/x --run_name t; "
            'build_app_args 1; printf "%s\\n" "${APP_ARGS[@]}"',
        )
        assert proc.returncode == 0, proc.stderr
        assert "--llm_config" not in proc.stdout.splitlines()


class TestGenericRetentionCompatibility:
    def test_exploratory_chain_default_still_cleans_up(self):
        """Witness (c): sourcing _chain_common and building default args
        must still emit the flag — the campaign fix must not break
        non-campaign disk hygiene."""
        proc = _bash(
            "-c",
            f"source '{CHAIN_COMMON}'; "
            "parse_chain_args --workspace /tmp/x --run_name t; "
            'build_app_args 1; printf "%s\\n" "${APP_ARGS[@]}"',
        )
        assert proc.returncode == 0, proc.stderr
        assert "--cleanup_denoised" in proc.stdout.splitlines()

    def test_chain_retention_token_suppresses_cleanup(self):
        """The typed named absence flows through the chain builder: with
        --no-cleanup_denoised the child argv carries NEITHER token."""
        proc = _bash(
            "-c",
            f"source '{CHAIN_COMMON}'; "
            "parse_chain_args --workspace /tmp/x --run_name t --no-cleanup_denoised; "
            'build_app_args 1; printf "%s\\n" "${APP_ARGS[@]}"',
        )
        assert proc.returncode == 0, proc.stderr
        tokens = proc.stdout.splitlines()
        assert "--cleanup_denoised" not in tokens
        assert "--no-cleanup_denoised" not in tokens  # chain-level flag, not a child flag

    def test_sdsc_mode_refuses_retention(self, tmp_path):
        """submit_one_iteration.slurm force-injects --cleanup_denoised into
        jobs that omit it, so honoring retention in sdsc mode is
        impossible — the combination must refuse, not lie.

        Launch-inertness by FIXTURE CONSTRUCTION (the no-test-executes-a-
        launcher rule's concern): the copy runs in a tmp tree holding ONLY
        run_chain.sh + _chain_common.sh. The expected path exits at the
        retention refusal before any interpreter resolution; and were that
        refusal regressed away, the tree has no _import_resolution_probe.py,
        so the source-authority guard aborts before anything can submit —
        with a different stderr, which this assertion then catches."""
        tree = tmp_path / "chain"
        tree.mkdir()
        shutil.copy2(RUN_CHAIN, tree / RUN_CHAIN.name)
        shutil.copy2(CHAIN_COMMON, tree / CHAIN_COMMON.name)
        proc = _bash(
            str(tree / RUN_CHAIN.name),
            "--mode",
            "sdsc",
            "--workspace",
            str(tmp_path / "w"),
            "--run_name",
            "t",
            "--no-cleanup_denoised",
        )
        assert proc.returncode != 0
        assert "cannot be honored in --mode sdsc" in proc.stderr


#: ARBITRARY TRANSPORT PROBES — NOT the campaign's ceiling, and deliberately
#: not near any value anybody has proposed for one. D-HW-6's ceiling is
#: HARDWARE_DERIVED / PENDING_H100_QUALIFICATION, so no number is bound
#: anywhere on the production path; these exist ONLY to be recognisable on
#: the far side of the transport. They DIFFER from each other on purpose:
#: identical probes could not tell a faithful two-value transport apart from
#: one that carries the trial value into both slots.
PROBE_TRIAL_VRAM = "7.5"
PROBE_FORMAL_VRAM = "9.25"


class TestHistoricalStage2AndGenericVramTransport:
    """Retained Stage-2 and generic transport evidence for D-HW-6.

    Stage-1 policy and concrete campaign values are owned externally. These
    tests preserve only the independent historical Stage-2 builder, the real
    chain-to-typed-config transport, and non-campaign empty-default behavior.

    UNITS ARE OUT OF SCOPE BY DESIGN. D-HW-6 records a live GB/GiB gap (the
    flags spell ``_gb``; ``evaluate_vram_skill/wrapper.py`` multiplies by
    ``_GB = 1024**3``). The seam carries the operator's value unchanged, so
    no test here may assert a converted or normalised number — that would
    silently settle a question the decision record leaves open.
    """

    @pytest.fixture
    def registry(self, tmp_path: Path) -> Path:
        reg = tmp_path / "designs"
        reg.mkdir()
        for design in ("wavenetA", "punetB", "rnnC", "fnoD"):
            (reg / f"{design}.json").write_text("{}\n")
        return reg

    def _supplied(self) -> list[str]:
        return [
            "--gold_trial_vram_budget_gb",
            PROBE_TRIAL_VRAM,
            "--gold_formal_vram_budget_gb",
            PROBE_FORMAL_VRAM,
        ]

    def test_a_the_value_ARRIVES_at_the_consumer_through_the_real_transport(self, campaign_root):
        """(d) THE witness. The defect only this catches: a ceiling that is
        present in argv and consumed by nothing.

        Argv presence proves a string was assembled. It does NOT prove the
        value survives ``_chain_common.sh``'s parse (which forwards each
        budget only inside an ``if [ -n ... ]``), nor that the runner's
        argparse binds it, nor that it lands on the typed object the
        workflow actually reads. Each of those hops has an omission mode
        that still exits 0 — which is precisely how every defect in this
        release's family survived.

        So the launcher's OWN emitted argv is walked through the production
        hops: real ``parse_chain_args`` + ``build_app_args``, real
        ``run_one_iteration.py`` argparse, real ``WorkflowLaunchConfig``
        construction — the object ``model_exploration`` reads at the point
        it picks the active budget.

        Boundary stated honestly: this stops at ``WorkflowLaunchConfig``,
        the last hop the SEAM owns. Enforcement beyond it (the tuner's
        per-mode gate and ``evaluate_vram_skill``'s cap arithmetic) is
        landed behaviour with its own tests and needs a sandbox/GPU.

        The negative half is what makes it a witness and not a tautology:
        the identical parsers with the flags ABSENT must yield ``None`` —
        i.e. no operator ceiling — so a green assertion cannot be explained
        by a default that was going to be there anyway.

        Fails by: the value being dropped at any hop, or coerced to
        something other than what was supplied."""
        pytest.importorskip("pydantic")
        import importlib.util

        proc = _stage1_dry(campaign_root, *self._supplied())
        assert proc.returncode == 0, proc.stderr + proc.stdout
        argv = _band_argvs(proc.stdout)["0-3"]
        # argv = ["CUDA_VISIBLE_DEVICES=0", "bash", "<run_chain.sh>", ...]
        chain_args = argv[3:]
        built = _bash(
            "-c",
            f"source '{CHAIN_COMMON}'; "
            f"parse_chain_args {' '.join(shlex.quote(a) for a in chain_args)}; "
            'build_app_args 1; printf "%s\\n" "${APP_ARGS[@]}"',
        )
        assert built.returncode == 0, built.stderr
        app_args = [tok for tok in built.stdout.splitlines() if tok]
        assert "--trial_vram_budget_gb" in app_args, app_args
        assert "--formal_vram_budget_gb" in app_args, app_args

        spec = importlib.util.spec_from_file_location(
            "roi_for_vram_seam_test", SDSC / "run_one_iteration.py"
        )
        roi = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(roi)
        from workflows.run_config import WorkflowLaunchConfig

        ns = roi.build_parser().parse_args(app_args)
        assert ns.trial_vram_budget_gb == float(PROBE_TRIAL_VRAM)
        assert ns.formal_vram_budget_gb == float(PROBE_FORMAL_VRAM)

        # The production construction site (run_one_iteration.py) — the
        # typed object model_exploration reads.
        launch = WorkflowLaunchConfig(
            trial_vram_budget_gb=ns.trial_vram_budget_gb,
            formal_vram_budget_gb=ns.formal_vram_budget_gb,
        )
        assert launch.trial_vram_budget_gb == float(PROBE_TRIAL_VRAM)
        assert launch.formal_vram_budget_gb == float(PROBE_FORMAL_VRAM)

        # The negative half — the same parsers, the flags omitted.
        bare = roi.build_parser().parse_args(["--workspace", "/tmp/x", "--run_name", "t"])
        assert bare.trial_vram_budget_gb is None
        assert bare.formal_vram_budget_gb is None
        assert WorkflowLaunchConfig().trial_vram_budget_gb is None
        assert WorkflowLaunchConfig().formal_vram_budget_gb is None

    def test_g_the_non_campaign_chain_path_is_behaviourally_unchanged(self, tmp_path):
        """(d) The defect only this catches: the seam leaking a ceiling into
        NON-Gold chains. The obvious way to 'wire VRAM up' would have been to
        give ``_chain_common.sh`` a default budget — which would silently cap
        every exploratory run, every X9 launcher and every smoke on the box,
        none of which asked for one.

        This drives the chain parser DIRECTLY with a non-campaign argv (no
        Gold script involved) and asserts the pre-existing 'empty == omit'
        contract still holds. Fails by: either token appearing in APP_ARGS
        for a chain that supplied no budget."""
        built = _bash(
            "-c",
            f"source '{CHAIN_COMMON}'; "
            f"parse_chain_args --workspace {shlex.quote(str(tmp_path / 'w'))} "
            "--run_name t; "
            'build_app_args 1; printf "%s\\n" "${APP_ARGS[@]}"',
        )
        assert built.returncode == 0, built.stderr
        app_args = [tok for tok in built.stdout.splitlines() if tok]
        assert "--trial_vram_budget_gb" not in app_args, app_args
        assert "--formal_vram_budget_gb" not in app_args, app_args


# ---------------------------------------------------------------------------
# #316 B1 / F-GATE-WIRE-1 — the incumbent-formal-gate switch
# ---------------------------------------------------------------------------

#: The frozen deltas, HARDCODED. Reading them back from the lib would compare
#: the table to itself and pass for any table (same rule as the nineteen).
FROZEN_SKIP_DELTA = -2.0
FROZEN_BYPASS_DELTA = 0.5
GATE_SWITCH = "--enable_chain_incumbent_formal_gates"


class TestIncumbentFormalGateSwitch:
    """#316 B1 — the Gold launcher declared two formal-gate deltas and never
    emitted the switch that makes them consumable.

    ``skip_formal_min_delta=-2.0`` and
    ``bypass_formal_time_budget_min_delta=0.5`` were transported and parsed
    all the way to the tuner, where
    ``ml_hyperparameter_tune_agent.py:1103-1107`` nulls the reference unless
    the switch is on. Both gates then resolve ``gates_disabled`` and go
    inert. Nothing fails; the campaign runs its whole horizon with a
    scientific policy that was declared, transported and never applied.

    The predecessor campaign emitted the switch on the line directly above
    the same two deltas (``launch_v20_campaign.sh:158-160``).
    """

    def test_the_real_transport_delivers_an_armed_switch_to_the_runner(self, campaign_root):
        """The launcher's OWN argv walked through the production hops —
        ``_chain_common.sh`` ``parse_chain_args`` + ``build_app_args``, then
        ``run_one_iteration.py``'s REAL argparse.

        ``_chain_common.sh:129`` defaults the switch OFF and ``:662`` forwards
        it only when it arrives, so this is where a dropped emission becomes
        an unarmed run."""
        pytest.importorskip("pydantic")
        import importlib.util

        proc = _stage1_dry(campaign_root)
        assert proc.returncode == 0, proc.stderr + proc.stdout
        chain_args = _band_argvs(proc.stdout)["0-3"][3:]
        built = _bash(
            "-c",
            f"source '{CHAIN_COMMON}'; "
            f"parse_chain_args {' '.join(shlex.quote(a) for a in chain_args)}; "
            'build_app_args 1; printf "%s\\n" "${APP_ARGS[@]}"',
        )
        assert built.returncode == 0, built.stderr
        app_args = [tok for tok in built.stdout.splitlines() if tok]
        assert GATE_SWITCH in app_args, "the chain parse+forward dropped the switch"

        spec = importlib.util.spec_from_file_location(
            "roi_for_gate_wire_test", SDSC / "run_one_iteration.py"
        )
        roi = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(roi)
        ns = roi.build_parser().parse_args(app_args)
        assert ns.enable_chain_incumbent_formal_gates is True
        assert ns.skip_formal_min_delta == FROZEN_SKIP_DELTA
        assert ns.bypass_formal_time_budget_min_delta == FROZEN_BYPASS_DELTA

        # The negative half: the identical parser with the switch absent is
        # what the campaign was actually running.
        bare = roi.build_parser().parse_args(["--workspace", "/tmp/x", "--run_name", "t"])
        assert bare.enable_chain_incumbent_formal_gates is False

    def test_the_gates_evaluate_live_with_the_switch_and_are_inert_without_it(self, campaign_root):
        """THE BEHAVIOURAL WITNESS. An argv assertion proves a token was
        copied; this proves a POLICY was applied.

        The real resolver is driven at the production call-site condition
        (``ml_hyperparameter_tune_agent.py:1103-1107``) for BOTH switch
        states, with the switch value taken from the REAL parsed args, and
        both real gate predicates are then evaluated against three winner
        scores chosen to straddle both thresholds.

        Note ``_should_bypass_formal_time_budget`` takes no ``gates_enabled``
        argument — it is inert only because the resolver handed it a ``None``
        threshold. That is why this is ONE fix and not two: the inertness
        originates at the reference-nulling call site, so restoring the
        switch re-arms both gates at once.
        """
        pytest.importorskip("pydantic")
        import importlib.util

        proc = _stage1_dry(campaign_root)
        chain_args = _band_argvs(proc.stdout)["0-3"][3:]
        built = _bash(
            "-c",
            f"source '{CHAIN_COMMON}'; "
            f"parse_chain_args {' '.join(shlex.quote(a) for a in chain_args)}; "
            'build_app_args 1; printf "%s\\n" "${APP_ARGS[@]}"',
        )
        app_args = [tok for tok in built.stdout.splitlines() if tok]
        spec = importlib.util.spec_from_file_location(
            "roi_for_gate_behaviour_test", SDSC / "run_one_iteration.py"
        )
        roi = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(roi)
        ns = roi.build_parser().parse_args(app_args)

        sys.path.insert(0, str(REPO_ROOT))
        from execute_tools.dataset_config import TIDMAD_PROFILE
        from execute_tools.evaluation_metric import derive_tidmad_metric_spec
        from execute_tools.metric_order import MetricOrder
        from nodes.ml_hyperparameter_tune_agent.policy import (
            _resolve_formal_comparison_thresholds,
            _should_bypass_formal_time_budget,
            _should_skip_formal,
        )

        order = MetricOrder(derive_tidmad_metric_spec(TIDMAD_PROFILE))
        assert order.direction == "higher", "fixture assumes the TIDMAD direction"
        incumbent = 5.0

        def resolve(switch: bool):
            # The production call-site expression, mirrored verbatim. The
            # source guard below fails if production stops doing this.
            consumed = incumbent if switch else None
            return _resolve_formal_comparison_thresholds(
                reference_score=consumed,
                gates_enabled=switch,
                skip_min_delta=ns.skip_formal_min_delta,
                bypass_min_delta=ns.bypass_formal_time_budget_min_delta,
                order=order,
            )

        # --- switch ON (what this fix delivers) --------------------------
        ref_on, skip_thr, bypass_thr, source_on = resolve(ns.enable_chain_incumbent_formal_gates)
        assert source_on == "restored_valid_formal_incumbent"
        assert ref_on == incumbent
        # Hardcoded, not recomputed from the deltas under test.
        assert skip_thr == 3.0, "5.0 loosened by -2.0"
        assert bypass_thr == 5.5, "5.0 tightened by +0.5"

        # Three winners straddling both thresholds — both gates DECIDE.
        def gates(score, thr_skip, thr_bypass):
            winner = {"denoising_score": score}
            return (
                _should_skip_formal(
                    winner,
                    threshold=thr_skip,
                    gates_enabled=ns.enable_chain_incumbent_formal_gates,
                    order=order,
                ),
                _should_bypass_formal_time_budget(winner, threshold=thr_bypass, order=order),
            )

        assert gates(2.0, skip_thr, bypass_thr) == (True, False), "SKIP must fire at 2.0"
        assert gates(4.0, skip_thr, bypass_thr) == (False, False), "neither at 4.0"
        assert gates(6.0, skip_thr, bypass_thr) == (False, True), "BYPASS must fire at 6.0"

        # --- switch OFF (the shipped state before this fix) --------------
        ref_off, skip_off, bypass_off, source_off = resolve(False)
        assert source_off == "gates_disabled"
        assert (ref_off, skip_off, bypass_off) == (None, None, None)
        for score in (2.0, 4.0, 6.0):
            winner = {"denoising_score": score}
            assert (
                _should_skip_formal(winner, threshold=skip_off, gates_enabled=False, order=order)
                is False
            )
            assert (
                _should_bypass_formal_time_budget(winner, threshold=bypass_off, order=order)
                is False
            ), "the bypass gate is inert ONLY via the None threshold"

    def test_the_production_call_site_still_nulls_the_reference_on_the_switch(self):
        """Reachability guard for the mirror above.

        The behavioural witness reproduces two lines of
        ``ml_hyperparameter_tune_agent.py``. If production stops nulling the
        reference on this switch, the mirror would keep testing a condition
        nothing evaluates — the exact "test captures what production
        recomputes" failure. This pins the call site instead.
        """
        src = (
            REPO_ROOT / "nodes" / "ml_hyperparameter_tune_agent" / "ml_hyperparameter_tune_agent.py"
        ).read_text()
        assert "_consumed_reference = (" in src
        assert "if agent_input.enable_chain_incumbent_formal_gates" in src
        assert "gates_enabled=agent_input.enable_chain_incumbent_formal_gates" in src
