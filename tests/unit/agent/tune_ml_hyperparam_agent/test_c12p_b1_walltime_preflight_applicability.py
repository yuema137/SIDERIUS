"""C12-P / W3 — B1: wall-time pre-flight requires its complete legacy workload.

The corrective unit's confirmed defect: every wall-time pre-flight site
resolves its step counts through ``execute_tools.workload_resolvers``, whose
``_validate_seg`` reads ``tidmad_topology(profile).dataset.psd_segment_length``.
That function FAILS CLOSED for a profile that declares no TIDMAD topology, so
a composed non-TIDMAD run whose time budget is non-null cannot pre-flight at
all — the tuner turns the skill's structured error into
``RuntimeError("Time check error: ...")`` and the run dies.

The operator's instruction is that this must not be repaired one visible site
at a time: the sites form a FAMILY, several members of which are currently
MASKED behind the first raise. The falsifiers below are written against the
family, not against the first raise, and they attach the applicability rule to
ONE shared semantic authority — the membership predicate
``execute_tools.dataset_config.declares_tidmad_topology`` (introduced by
PR-12d, seam B) — never to a re-inlined list of section names and never to a
caught ``ValueError``.

The H100 external-task replay later exposed the second half of the same
boundary: topology membership alone is insufficient when a composed TIDMAD
task carries opaque task-owned scopes and intentionally has no legacy
``SampleSet``.

Every test states the defect it ALONE catches and how it fails on regression.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from agent.skills.evaluate_time_skill import wrapper as time_wrapper
from execute_tools.dataset_config import TIDMAD_PROFILE, DatasetProfile


def _foreign_profile() -> DatasetProfile:
    """A profile of the honest Q-12-4 shape: generic identity, no topology.

    This is what a composed Pets or DAVIS run binds. It is deliberately
    constructed HERE rather than imported from a pack fixture, so the property
    under test does not depend on any pack's current maturity.
    """
    return DatasetProfile(
        partition_count=3,
        anchor_selection_files=[0],
        health_peek_files=[1],
    )


def _malformed_tidmad_profile() -> DatasetProfile:
    """A profile that DECLARES TIDMAD's sections but declares them WRONG.

    Membership is satisfied — all three section names are present — while the
    typed view cannot be built. ``tidmad_topology`` raises for this too, with a
    DIFFERENT message, and conflating the two raises is the anti-pattern this
    module falsifies.
    """
    return DatasetProfile(
        partition_count=3,
        anchor_selection_files=[0],
        health_peek_files=[1],
        topology={
            "dataset": {"this_is_not": "a DatasetConfig"},
            "channels": {},
            "encoding": {},
        },
    )


_MODULES_THAT_READ_TIDMAD_TOPOLOGY_ON_THE_WALLTIME_PATH = (
    "execute_tools.workload_resolvers",
    "agent.skills.inference_skill.estimator",
    "agent.skills.evaluate_time_skill.wrapper",
    "execute_tools.sample_set_builder",
)


@pytest.fixture
def topology_spy(monkeypatch):
    """Record every ``tidmad_topology`` read attempted on the wall-time path.

    Patched in EVERY module that holds its own module-level reference, so a
    site that moves between modules cannot escape the census.
    """
    import importlib

    calls: list[str] = []

    for module_name in _MODULES_THAT_READ_TIDMAD_TOPOLOGY_ON_THE_WALLTIME_PATH:
        module = importlib.import_module(module_name)
        if not hasattr(module, "tidmad_topology"):
            continue
        real = module.tidmad_topology

        def _spy(profile, *, _real=real, _where=module_name):
            calls.append(_where)
            return _real(profile)

        monkeypatch.setattr(module, "tidmad_topology", _spy)

    return calls


@pytest.fixture
def torchless_time_skill(monkeypatch):
    """Neutralize the two helpers that would otherwise need a GPU/model.

    ``_count_params`` instantiates the model and ``_detect_gpu_name`` touches
    CUDA. Neither participates in the applicability question, and stubbing them
    is what lets this falsifier reach the topology-reading sites without any
    heavy subsystem — per the project rule that unit tests mock every heavy
    subsystem.
    """
    monkeypatch.setattr(time_wrapper, "_count_params", lambda *a, **k: 1_000_000)
    monkeypatch.setattr(time_wrapper, "_detect_gpu_name", lambda: None)


def _run_skill_on(profile: DatasetProfile) -> dict:
    return time_wrapper.run_skill(
        sandbox=None,
        model_type="punet",
        model_config={"segmentation_size": 40000},
        train_config={"batch_size": 4, "epochs": 1},
        loss_config={"loss_type": "ce"},
        sample_set={"0": [0, 1, 2]},
        time_budget_minutes=20.0,
        dataset_profile=profile,
    )


class TestTheApplicabilityDecisionIsMadeCallerSide:
    """The shape the operator RULED for (§V.3), replacing the skill-side one.

    These two cases are the live guard for B1 + B4. The skill-side pair below
    is retired against them -- see `TestRetiredSkillSideShape`.
    """

    def test_a_foreign_task_is_out_of_the_wall_time_family_domain(self) -> None:
        """One decision, made by the layer that owns the resolved profile.

        DEFECT THIS TEST ALONE CATCHES
            The wall-time family being entered at all for a task whose
            workload it cannot compute -- B1, and B4 with it, since the probe
            lane is only reached THROUGH this gate.

        HOW IT FAILS WHEN THE BEHAVIOUR REGRESSES
            The predicate returns True for a profile declaring no TIDMAD
            topology, so the estimate and the probe run again and the run dies
            at [Pre-flight 2/2].
        """
        from execute_tools.dataset_config import DatasetProfile
        from nodes.ml_hyperparameter_tune_agent.execution import (
            wall_time_preflight_applicable,
        )

        foreign = DatasetProfile(
            partition_count=3,
            topology={"clips": {"count": 3}},
            anchor_selection_files=[0],
            health_peek_files=[0],
        )
        assert wall_time_preflight_applicable(foreign, {"0": [0]}) is False

    def test_regime_a_and_malformed_tidmad_both_stay_applicable(self) -> None:
        """The two ways this must NOT be over-applied.

        DEFECT THIS TEST ALONE CATCHES
            (a) an un-composed TIDMAD run losing its wall-time gate, which
            would be a silent capability regression on the legacy path; and
            (b) a MALFORMED TIDMAD profile being reclassified as "some other
            task" -- the row-2-vs-row-4 rule. A malformed declaration must
            still enter the family and still fail closed, which is exactly
            what a `try/except ValueError` implementation would break.

        HOW IT FAILS WHEN THE BEHAVIOUR REGRESSES
            Either case returning False; the assertion names which.
        """
        from execute_tools.dataset_config import DatasetProfile
        from nodes.ml_hyperparameter_tune_agent.execution import (
            wall_time_preflight_applicable,
        )

        assert wall_time_preflight_applicable(None, {"0": [0]}) is True, (
            "Regime A (un-composed) IS TIDMAD and must keep its wall-time gate"
        )
        malformed = DatasetProfile(
            partition_count=3,
            # all three section names PRESENT, contents nonsense
            topology={"dataset": {"nope": 1}, "channels": {"nope": 1}, "encoding": {"nope": 1}},
            anchor_selection_files=[0],
            health_peek_files=[0],
        )
        assert wall_time_preflight_applicable(malformed, {"0": [0]}) is True, (
            "a MALFORMED TIDMAD topology is not a foreign task: it must stay "
            "applicable and fail closed, never be silently skipped"
        )

    def test_task_owned_scope_does_not_enter_the_legacy_forecast_family(self) -> None:
        """Opaque composed scopes cannot be partially priced as SampleSets.

        DEFECT THIS TEST ALONE CATCHES
            A composed task that still declares TIDMAD topology enters the
            legacy estimator even though planning intentionally produced no
            SampleSet. Training then crashes on ``None.items()``; repairing
            only that phase moves the crash to inference or scoring.

        HOW IT FAILS WHEN THE BEHAVIOUR REGRESSES
            The predicate returns True for ``legacy_sample_set=None`` and the
            caller invokes a forecast family missing its required workload.
        """
        from nodes.ml_hyperparameter_tune_agent.execution import (
            wall_time_preflight_applicable,
        )

        assert wall_time_preflight_applicable(TIDMAD_PROFILE, None) is False


class TestRetiredSkillSideShape:
    """RETIRED, not deleted, and the reason is the whole point.

    These two asserted that ``run_skill`` itself returns
    ``status="not_applicable"``. The operator RULED (§V.3) that applicability
    is decided **caller-side**, once, by the layer already holding the
    resolved profile, and that leaf modules must not rediscover it. Under that
    ruling ``run_skill`` is never invoked for a foreign task, so a skill-side
    status is unreachable by construction -- asserting it would pin a design
    the ruling rejected, and implementing it would have required a new branch
    in the tuner keyed on a status whose absence today is tolerated only by
    ``time_check.get("feasible", True)`` defaulting True, which works by
    accident rather than by contract.

    They are kept as a record because the behaviour they describe -- the skill
    raising rather than refusing -- is still TRUE of the skill in isolation,
    and would matter again if a future caller invoked it directly.
    """

    @pytest.mark.skip(reason="superseded by the caller-side ruling (§V.3); see class docstring")
    def test_run_skill_returns_a_named_inapplicability_not_an_error(self, torchless_time_skill):
        """The FIRST visible site — and the one that kills a composed run.

        Defect this test alone catches: ``evaluate_time_skill.run_skill``
        reports a task it structurally cannot price as an EXECUTION FAILURE.
        The tuner's gate (``execution.py``, "Time check error") raises
        ``RuntimeError`` on ``status == "error"``, so a composed non-TIDMAD run
        with any non-null time budget dies in pre-flight 2/2 — before a single
        training step, and while nothing is actually broken.

        Applicability is not feasibility and it is not failure. A task that
        declares no TIDMAD topology cannot have its PSD-segment decomposition
        priced, and the honest report is a NAMED refusal, exactly as Step 08a
        introduced ``CheckVerdict.inapplicable`` instead of "passed=True with
        prose" and as PR-12d B12 refuses the pre-phase GPU measurement.

        How it fails on regression: the moment the refusal is removed or a
        second entry point stops asking the membership predicate, ``status``
        reverts to ``"error"`` and this assertion fails naming the message.
        """
        result = _run_skill_on(_foreign_profile())

        assert result["status"] == "not_applicable", (
            "a task that declares no TIDMAD topology must be REFUSED BY NAME, "
            f"never reported as an execution failure; got {result!r}"
        )
        assert "feasible" not in result, (
            "an inapplicable pre-flight must not fabricate a feasibility "
            "verdict — there is no estimate to be feasible or infeasible about"
        )

    @pytest.mark.skip(reason="superseded by the caller-side ruling (§V.3); see class docstring")
    def test_no_tidmad_topology_read_is_attempted_at_all(self, torchless_time_skill, topology_spy):
        """The FAMILY test — the one the operator's §6 instruction asks for.

        Defect this test alone catches: repairing only the first visible raise.
        ``run_skill`` reads TIDMAD topology from at least four places on one
        pass — the training estimator's workload resolver, the inline
        ``psd_segment_length`` read that scales the inference-ms hint, the
        inference estimator's own resolver, and the over-budget suggestion
        renderer. Sites 2-4 are invisible today because site 1 raises first, so
        a fix validated only against site 1 would look complete and would
        surface the next raise on the next composed run.

        This asserts the property that makes the family irrelevant: under a
        foreign profile the pre-flight refuses BEFORE any TIDMAD-physical read
        is attempted, so the count of attempted reads is exactly zero.

        How it fails on regression: any site that reacquires an unguarded
        topology read appends its own module name to ``topology_spy`` and the
        assertion names the offending module.
        """
        _run_skill_on(_foreign_profile())

        assert topology_spy == [], (
            "the wall-time pre-flight attempted a TIDMAD-physical topology "
            f"read for a task that declares none, from: {topology_spy}"
        )

    def test_a_tidmad_run_still_prices_its_topology(self, torchless_time_skill, topology_spy):
        """Regime A is untouched: the refusal must not disarm the real gate.

        Defect this test alone catches: an applicability rule written so
        broadly that it also declines TIDMAD. A membership predicate that
        always answers "no" would make every one of these falsifiers pass while
        silently deleting the wall-time gate for the only task that has one.

        How it fails on regression: a TIDMAD profile stops reaching the
        resolvers, ``topology_spy`` is empty, and the run is priced by nothing.
        """
        from execute_tools.dataset_config import TIDMAD_PROFILE

        result = _run_skill_on(TIDMAD_PROFILE)

        assert result["status"] == "success", result
        assert "execute_tools.workload_resolvers" in topology_spy, (
            "a TIDMAD run must still resolve its step counts through the "
            f"workload resolver; reads seen: {topology_spy}"
        )


class TestTheOutsideTheHandlerSite:
    @pytest.mark.skip(
        reason=(
            "RETIRED by the caller-side ruling (§V.3), and retiring it is the "
            "correct call rather than a concession. This asserted that EVERY "
            "topology read in `run_skill` sits inside its try/except, so the "
            "`:1009` over-budget suggestion could not escape as a raw "
            "ValueError. Two things changed. (1) Reachability: applicability "
            "is now decided caller-side, so `run_skill` is never entered for a "
            "task that declares no TIDMAD topology -- the foreign case this "
            "guarded cannot occur. (2) Desirability: the only profile that now "
            "reaches `:1009` and still raises is a MALFORMED TIDMAD one, and "
            "§V.2 requires malformed applicable input to stay LOUD. Moving "
            "that read inside the handler would convert the raise into "
            "`status='error'` prose -- i.e. it would make a broken declaration "
            "QUIETER, which is the opposite of the rule. Kept, not deleted, "
            "because the structural fact it records is still true of the "
            "module and would matter again if a caller ever invoked the skill "
            "without the applicability gate."
        )
    )
    def test_every_topology_read_in_run_skill_sits_inside_its_handler(self):
        """The site whose FAILURE MODE differs from its three siblings.

        Defect this test alone catches: ``wrapper.py``'s over-budget suggestion
        renders ``tidmad_topology(profile).dataset.psd_segment_length`` AFTER
        ``run_skill``'s ``try/except Exception`` has closed. Its three siblings
        are inside it and degrade to the documented
        ``{"status": "error", ...}`` contract; this one propagates a RAW
        ``ValueError`` out of ``run_skill``, past the tuner's
        ``status == "error"`` branch entirely, as an unhandled crash. It is
        reached only when the projection is over budget, which is why no
        existing test has ever touched it.

        The property asserted is structural because the behaviour is masked:
        the three earlier sites raise first, so no input can currently drive
        execution to this line. Structure is the only honest witness until the
        earlier sites are refused.

        How it fails on regression: moving any topology read out of the handler
        — or adding a new one after it — makes the collected line numbers
        non-empty and the assertion names them.
        """
        source = Path(inspect.getsourcefile(time_wrapper)).read_text()
        module = ast.parse(source)

        run_skill = next(
            node
            for node in module.body
            if isinstance(node, ast.FunctionDef) and node.name == "run_skill"
        )

        guarded_lines: set[int] = set()
        for node in ast.walk(run_skill):
            if isinstance(node, ast.Try):
                for child in ast.walk(ast.Module(body=node.body, type_ignores=[])):
                    if hasattr(child, "lineno"):
                        guarded_lines.add(child.lineno)

        unguarded = [
            node.lineno
            for node in ast.walk(run_skill)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "tidmad_topology"
            and node.lineno not in guarded_lines
        ]

        assert unguarded == [], (
            "run_skill reads TIDMAD topology outside its exception handler at "
            f"line(s) {unguarded}; a raise there escapes the skill's declared "
            "structured-error contract as an unhandled crash"
        )


def test_task_owned_scope_makes_warmup_task_agnostic(monkeypatch, tmp_path, capsys):
    """A foreign profile with a task scope must enter generic measurement."""
    import torch

    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    time_wrapper._measure_ms_per_step(
        model_type="unknown_external_model",
        model_config={"segmentation_size": 8},
        train_config={"batch_size": 1},
        loss_config={"loss_type": "mse"},
        data_dir=str(tmp_path),
        sample_set={},
        profile=_foreign_profile(),
        task_scope=object(),
    )
    output = capsys.readouterr().out
    assert "NOT APPLICABLE" not in output
    assert "[warmup failed]" in output


class TestTheProposerPreflightSibling:
    def test_it_refuses_a_foreign_task_instead_of_raising(self, monkeypatch):
        """The ambient-resolution sibling, reached from a DIFFERENT node.

        Defect this test alone catches: ``agent/utils/proposer_preflight.py``
        feeds the SAME two estimators, but acquires its profile from the
        ambient ``resolve_dataset_profile()`` seam rather than from a caller.
        The proposer node calls it whenever a time budget is non-null, so a
        composed run reaches the identical TIDMAD-only family through a path
        the tuner's gate does not cover. Guarding only the tuner leaves this
        one live.

        Note also WHICH site raises first here, which the corrective unit's
        brief had wrong: with ``sample_set=None`` (the production caller's
        shape) the first raise is ``execute_tools/sample_set_builder.py``'s
        ``segments_per_file`` read inside ``build_sample_set``, reached at
        ``_synthesise_default_sample_set`` — BEFORE the training estimator.

        How it fails on regression: dropping the refusal restores the raise
        and this fails naming the ``ValueError``.
        """
        from agent.utils import proposer_preflight
        from execute_tools.dataset_config import bind_dataset_profile

        with bind_dataset_profile(_foreign_profile()):
            verdict = proposer_preflight.estimate_proposal_time(
                model_type="punet",
                model_config={"segmentation_size": 40000},
                train_config={"batch_size": 4, "epochs": 1},
                loss_config={"loss_type": "ce"},
                num_params=1_000_000,
                time_budget_minutes=20.0,
            )

        assert verdict["applicable"] is False, (
            "the proposer pre-flight must decline a task whose topology it "
            f"cannot price, by name; got {verdict!r}"
        )

    def test_the_entry_point_is_production_live(self):
        """A stale in-source comment is the reason this site was exempted.

        Defect this test alone catches: ``proposer_preflight.py`` carries a
        comment asserting "This entry point is NOT production-live — its only
        non-test caller is ``production_estimator_factory._static``". That
        claim is FALSE. ``nodes/ml_model_proposal_agent`` imports
        ``estimate_proposal_time`` at module scope and calls it from
        ``_run_preflight_check``, gated only on a non-null time budget. The
        comment then draws a conclusion from the false claim — "so it is not
        genericized (§4's binding rule)" — which is precisely why this live
        entry point still resolves an ambient TIDMAD profile.

        A comment cannot be tested, but the fact it denies can be, and pinning
        the fact is what stops the exemption from being re-derived. GREEN
        today, deliberately: it is the EVIDENCE that the comment is false, not
        a falsifier of behaviour. The comment itself is a separate write-set
        item.

        How it fails on regression: if the proposer ever stops calling it the
        assertion fails and the exemption must be re-argued from evidence
        rather than re-asserted.
        """
        import importlib

        from agent.utils.proposer_preflight import estimate_proposal_time

        proposer_node = importlib.import_module(
            "nodes.ml_model_proposal_agent.ml_model_proposal_agent"
        )

        assert proposer_node.estimate_proposal_time is estimate_proposal_time

        source = Path(inspect.getsourcefile(proposer_node)).read_text()
        preflight_fn = next(
            node
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.FunctionDef) and node.name == "_run_preflight_check"
        )
        called = {
            node.func.id
            for node in ast.walk(preflight_fn)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "estimate_proposal_time" in called, (
            "_run_preflight_check no longer calls estimate_proposal_time — "
            "re-derive the entry point's liveness before exempting it"
        )
