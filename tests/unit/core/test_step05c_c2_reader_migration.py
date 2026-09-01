"""Step 05c — C2: the deliverable-name READERS resolve through the spec.

Design: ``docs/design/generic_framework_upgrade/
step_05c_tuner_execution_contracts.md`` C2.

Readers migrate before producers on purpose. A reader migration is reversible
against artifacts that already exist on disk — if the spec were wrong a reader
finds nothing, loudly, and destroys nothing — whereas a wrong producer writes
files that nothing can find or clean (failure class 1).

The three migrated sites:

* ``ml_hyperparameter_tune_agent._build_denoised_filename`` (``:1053``)
* ``core.sandbox_executor.TidmadSandbox.execute_inference`` — the watchdog
  partial-artifact glob (``:1776``)
* the tuner's ``--cleanup_denoised`` glob (``:5560``)

What is asserted here is **reachability**, not correctness of the accessors:
C1 already proved the accessors reproduce the C0 captures. What C1 could not
prove is that production *calls* them — a migration test that only exercised
the spec would pass just as happily if every production site still executed
its own literal.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.sandbox_executor import TidmadSandbox
from execute_tools.data_paths import bind_physical_data_root
from execute_tools.deliverable_spec import DeliverableNaming, default_deliverable_naming
from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
    _build_denoised_filename,
)
from tests.helpers.tuner_source import tuner_node_source
from tests.unit.core.test_step05c_c0_launch_cleanup_baseline import (
    EXP_ID,
    MODEL_TYPE,
    RUN_NAME,
    SEEDED_FILES,
)
from tests.unit.execute_tools.test_step05c_c0_deliverable_baseline import (
    GOLDEN_EXP_ID,
    GOLDEN_FILE_INDEX,
    GOLDEN_MODEL_TYPE,
    GOLDEN_RUN_NAME,
    GOLDEN_SAMPLE_SET_NAME,
)
from workflows.task_config import bind_task_config

RENAMED = DeliverableNaming(prefix="step05c_renamed")


@pytest.fixture(autouse=True)
def _bind_synthetic_task_config():
    """Exercise the reader seam without reviving an implicit scientific task."""
    with bind_task_config(
        {
            "task_description": "Synthetic deliverable-reader fixture.",
            "forward_contract": {},
        }
    ):
        yield


# ---------------------------------------------------------------------------
# Site 1 — the path builder
# ---------------------------------------------------------------------------


def test_path_builder_resolves_through_the_injected_naming():
    """An injected naming changes the resolved path; ``None`` keeps TIDMAD.

    Both halves are load-bearing. Without the first, the new parameter could
    be accepted and ignored while the inlined f-string kept running. Without
    the second, every caller that predates 05c — including the four existing
    ``test_denoised_filename_helper.py`` tests, which pass **unedited** —
    would change behaviour.
    """
    kwargs = {
        "model_type": GOLDEN_MODEL_TYPE,
        "run_name": GOLDEN_RUN_NAME,
        "exp_id": GOLDEN_EXP_ID,
        "input_identity": GOLDEN_FILE_INDEX,
        "base_dir": "/step05c/workspace",
    }

    assert _build_denoised_filename(**kwargs) == os.path.join(
        "/step05c/workspace", GOLDEN_SAMPLE_SET_NAME
    )
    assert _build_denoised_filename(**kwargs, naming=RENAMED) == os.path.join(
        "/step05c/workspace",
        RENAMED.name(
            model_type=GOLDEN_MODEL_TYPE,
            run_name=GOLDEN_RUN_NAME,
            exp_id=GOLDEN_EXP_ID,
            input_identity=GOLDEN_FILE_INDEX,
        ),
    )


# ---------------------------------------------------------------------------
# Site 2 — the watchdog partial-artifact cleanup, through the REAL kill path
# ---------------------------------------------------------------------------


def _seed(workspace, names) -> None:
    for name in names:
        (workspace / name).write_bytes(b"x")


def _run_killed_inference(sandbox: TidmadSandbox):
    """Drive ``execute_inference`` down its watchdog-kill branch.

    The branch is guarded by ``policy_obj.watchdog.enabled and sample_set is
    not None`` (``:1759``), so both are supplied; the kill itself is the
    second element of ``_run_observed_subprocess``'s return.
    """
    cfg_dir = sandbox.dirs["configs"]
    os.makedirs(cfg_dir, exist_ok=True)
    os.makedirs(sandbox.dirs["models"], exist_ok=True)
    open(
        os.path.join(sandbox.dirs["models"], f"model_{MODEL_TYPE}_{EXP_ID}_agent.pth"), "w"
    ).close()

    result = MagicMock()
    result.returncode = -9
    result.stdout = ""
    result.stderr = ""
    kill_info = {"elapsed_s": 12.0, "deadline_s": 10.0, "estimate_source": "test"}

    with patch("core.sandbox_executor._run_observed_subprocess") as mock_run:
        mock_run.return_value = (result, kill_info)
        return sandbox.execute_inference(
            EXP_ID,
            RUN_NAME,
            MODEL_TYPE,
            {"model_type": "fcnet", "segmentation_size": 10000, "latent_dims": [100, 10]},
            {"loss_type": "ce"},
            sample_set={"0": [0, 1]},
            runtime_policy={"watchdog": {"enabled": True}},
        )


def test_watchdog_cleanup_deletes_the_c0_set_and_spares_the_survivors(tmp_path):
    """The REAL kill path removes exactly the C0 attempt set.

    This is the reachability evidence for site 2: ``os.remove`` is called by
    production, on a pattern production obtained from ``self.deliverable_naming``.
    Asserting the survivors matters as much as the deletions — a broadened
    glob here destroys a concurrent attempt's artifacts, which is data loss,
    not a naming refactor.
    """
    _seed(tmp_path, SEEDED_FILES)
    with bind_physical_data_root(str(tmp_path), purpose="watchdog cleanup test"):
        sandbox = TidmadSandbox(run_name=RUN_NAME, workspace=str(tmp_path), progress_bar=False)

    outcome = _run_killed_inference(sandbox)

    assert outcome["status"] == "wall_clock_timeout"
    survivors = sorted(p for p in os.listdir(str(tmp_path)) if os.path.isfile(str(tmp_path / p)))
    assert survivors == [
        "abra_validation_0000.h5",
        "abra_validation_denoised_fcnet_c0run_c0exp_0000.txt",
        "abra_validation_denoised_fcnet_c0run_otherexp_0000.h5",
        "abra_validation_denoised_wavenet_otherrun_c0exp_0003.h5",
        "model_fcnet_c0exp_agent.pth",
    ]


def test_watchdog_cleanup_follows_an_injected_renamed_naming(tmp_path):
    """With a renamed spec the watchdog cleans the RENAMED artifacts — and
    leaves the TIDMAD-named ones untouched.

    This is the one assertion no value-level check can fake: if the site still
    executed its own ``abra_validation_denoised_…`` literal, the renamed files
    would survive and the TIDMAD ones would be deleted — the exact inverse of
    what is asserted.
    """
    renamed_files = (
        RENAMED.name(model_type=MODEL_TYPE, run_name=RUN_NAME, exp_id=EXP_ID, input_identity=0),
        RENAMED.name(model_type=MODEL_TYPE, run_name=RUN_NAME, exp_id=EXP_ID, input_identity=7),
    )
    tidmad_file = "abra_validation_denoised_fcnet_c0run_c0exp_0000.h5"
    _seed(tmp_path, (*renamed_files, tidmad_file))

    with bind_physical_data_root(str(tmp_path), purpose="renamed cleanup test"):
        sandbox = TidmadSandbox(
            run_name=RUN_NAME,
            workspace=str(tmp_path),
            progress_bar=False,
            deliverable_naming=RENAMED,
        )
    _run_killed_inference(sandbox)

    remaining = {p for p in os.listdir(str(tmp_path)) if p.endswith(".h5")}
    assert remaining == {tidmad_file}


def test_sandbox_defaults_to_the_shipped_naming(tmp_path):
    """A caller that predates 05c gets the TIDMAD naming, not ``None``.

    Every existing construction site — ``run_comparison.py``,
    ``pregate_runtime_control_validation.py``, ``c2_prephase_validation.py``,
    ``finalize_recovered_diagnostic_round.py`` and every test — omits the new
    kwarg. If the default were left unresolved the watchdog branch would raise
    ``AttributeError`` on the kill path only: a failure that never appears
    until something has already gone wrong.
    """
    with bind_physical_data_root(str(tmp_path), purpose="default naming test"):
        sandbox = TidmadSandbox(run_name=RUN_NAME, workspace=str(tmp_path))
    assert sandbox.deliverable_naming == default_deliverable_naming()


# ---------------------------------------------------------------------------
# Site 3 — the tuner's --cleanup_denoised glob
# ---------------------------------------------------------------------------


def _tuner_source() -> str:
    """The tuner NODE's source, read from the checkout this test runs in.

    Read from disk rather than via ``inspect.getsource``: the package
    ``nodes.ml_hyperparameter_tune_agent`` re-binds its own name to the module,
    so the usual import form raises. The root is derived from ``__file__``,
    never hardcoded.

    Step 07 PR 07b C7 decomposed the node into a main module plus five
    node-local submodules. This test asks whether the NODE still reads
    deliverable paths through the naming authority, which is a claim about the
    node, so it reads all of its files.
    """
    return tuner_node_source()


@pytest.mark.parametrize(
    ("start_anchor", "end_anchor", "expected_accessor"),
    [
        (
            # Step 12 / PR-12d D4b: anchored on the CONDITION rather than the
            # whole line. Seam E added `and run_deliverable_naming is not
            # None` — a behaviour-preserving guard for a task that names its
            # own artifacts — and a whole-line anchor could not survive it.
            # Same failure shape as the source-string pins upgraded in 12a C3,
            # 12bc B7 and D0's B8: what this test owns is that the block uses
            # the naming AUTHORITY, not that the `if` is spelled a given way.
            "agent_input.cleanup_denoised",
            # C7d: the cleanup block ends the inference/scoring phase in
            # `execution.py`, so the anchor that follows it is now that phase's
            # return rather than run()'s next section comment.
            "return AttemptExecution(",
            "experiment_glob(exp_id=exp_id)",
        ),
        (
            "def _build_denoised_filename(",
            # C7: the anchor that follows it in `records.py`, where both now
            # live (it used to be `_validate_data_config`, now in `policy.py`).
            "def _build_scoring_failure_record(",
            "resolved.name(",
        ),
        (
            "def _denoised_fn(",
            # Step 06 C2 moved the live scoring call from `sandbox.score_vector`
            # to `sandbox.evaluate_metric(run_metric, …)`; the closure this
            # anchor brackets is unchanged and still the scorer's.
            "metric_result = sandbox.evaluate_metric(",
            "naming=naming",
        ),
    ],
    ids=["cleanup_glob", "path_builder", "scorer_closure"],
)
def test_no_tuner_reader_executes_an_inlined_deliverable_template(
    start_anchor, end_anchor, expected_accessor
):
    """No migrated tuner reader re-states the template — one concept, three sites.

    Site 3 (the ``--cleanup_denoised`` block) lives inside ``run()``'s
    ``finally``, which no unit test can reach without standing up a full round,
    so its reachability evidence is structural here and behavioural at
    Checkpoint C and Gate 2. The structural form is not a weaker version of the
    value-level check: it catches a site re-inlining the template, which no
    value assertion can, because a value assertion does not know the site
    exists.

    Asserted as ONE concept across all three because that is what would break
    together: ``_build_denoised_filename``'s body is the path the peek helpers
    open verbatim (``_peek.py:20-24``), ``_denoised_fn`` is the closure the
    scorer receives, and the cleanup glob decides what is deleted. A literal
    surviving in any of them makes the tuner agree with the producer only by
    coincidence.
    """
    source = _tuner_source()
    # Step 12 / PR-12d D-FINAL: a missing anchor used to raise
    # `ValueError: substring not found` from `str.index`, which pytest reports
    # as an ERROR with no indication of what this guard is for. A test that
    # cannot say why it broke sends the next reader to `git blame` instead of
    # to the invariant. The anchors are the guard's own scaffolding, so their
    # disappearance is a maintenance fact, NOT evidence about the production
    # invariant — it must be reported as such rather than as a silent crash.
    start = source.find(start_anchor)
    assert start != -1, (
        f"the anchor {start_anchor!r} no longer appears in the tuner source. "
        f"This says nothing about whether an inlined template survived — it "
        f"means this guard can no longer FIND the block it audits. Re-anchor "
        f"it on the moved code; never delete the case."
    )
    end = source.find(end_anchor, start)
    assert end != -1, (
        f"the closing anchor {end_anchor!r} no longer follows {start_anchor!r}. "
        f"Re-anchor this case on the code that now ends the block."
    )
    block = source[start:end]

    assert expected_accessor in block, (
        f"{start_anchor!r} must resolve through the deliverable naming authority"
    )
    assert "abra_validation_denoised" not in block, (
        f"an inlined deliverable template survived at {start_anchor!r}"
    )


# ---------------------------------------------------------------------------
# Who holds this authority — the inverted C1 inertness assertion
# ---------------------------------------------------------------------------

# Sites the §0 census assigns to 05c and that have migrated so far. Extended as
# C3-C6 land; a site dropping OUT of this list means the seam went dead.
MIGRATED_CONSUMERS = (
    "core/sandbox_executor.py",
    # A directory entry means "this NODE consumes it" — C7 spread the
    # tuner across a main module plus private submodules, and the census
    # is about the consumer, not about which file holds the read.
    "nodes/ml_hyperparameter_tune_agent/",
)

# Sites migrated by the OWNER the census deferred to. Step 06 (C3) took the
# scorer CLI's two deliverable-name literals — which 05c's census listed as
# "Step 06 — NOT touched" — through the naming authority. Asserted as a
# consumer so the seam cannot silently die; the frozen arithmetic module
# below stays forbidden.
STEP06_CONSUMERS = ("execute_tools/denoising_score_single.py",)

# Sites the census deliberately EXCLUDES. This half never grows: it is the
# frozen scorer arithmetic and the historical-artifact readers, and it is what
# turns a progress check into a scope guard.
FORBIDDEN_CONSUMERS = (
    "execute_tools/scoring_utils.py",
    "scripts/score_tidmad_official_banded.py",
    "scripts/score_tidmad_official_wavenet.py",
    "scripts/fcnet_full_file_scan.py",
    "scripts/fcnet_diversity_pearson_scan.py",
    "scripts/investigate_pearson_feasibility.py",
)


def test_only_the_censused_sites_consume_the_deliverable_spec():
    """The migrated sites hold the authority; the excluded sites never do.

    Two failure classes in one concept, and neither is visible to a
    value-level assertion:

    * a **dead seam** — a site reverting to its own literal while a
      spec-level test keeps passing because the spec is still correct;
    * a **scope breach** — the scorer or a historical-artifact reader
      acquiring the producer contract. Migrating a historical reader is not a
      neutral tidy-up: those scripts must keep matching names that files
      already on disk carry, and Step 06, not 05c, owns the scorer.
    """
    repo_root = Path(__file__).resolve().parents[3]

    for relative in MIGRATED_CONSUMERS + STEP06_CONSUMERS:
        target = repo_root / relative
        text = (
            "\n".join(f.read_text() for f in sorted(target.glob("*.py")))
            if target.is_dir()
            else target.read_text()
        )
        assert "deliverable_spec" in text, (
            f"{relative} no longer consumes the deliverable spec — the seam is dead"
        )

    for relative in FORBIDDEN_CONSUMERS:
        path = repo_root / relative
        if not path.exists():  # pragma: no cover - the census is current, not eternal
            continue
        assert "deliverable_spec" not in path.read_text(), (
            f"{relative} is outside 05c's census (Step 06 / historical replay) "
            f"and must not consume the producer contract"
        )
