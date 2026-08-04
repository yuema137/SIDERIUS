"""Documented commands must parse against the code that actually runs.

V20 PR C2.

Two failures this catches, both of which already happened in this PR:

* the Gate packet named `--formal_eval_portion`, which the harness did not
  implement — the approved command could not have run;
* the harness's formal arm ran only `execute_training` while the packet
  described a training **and** inference comparison.

A prose review missed both. These check the documents against `argparse`
and against the source, so a rename or a dropped flag fails here rather
than at the start of a gate.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import pytest

import scripts.c2_prephase_validation as harness

REPO_ROOT = Path(__file__).resolve().parents[3]
DESIGN_DOC = (
    REPO_ROOT / "docs" / "design" / "v20_priorities" / "pr_c_measured_evidence_admission.md"
)
TUNER_DOC = REPO_ROOT / "nodes" / "ml_hyperparameter_tune_agent" / "ml_hyperparameter_tune_agent.md"

#: Flags that exist only in the validation harness. An operator must never
#: find one of these in production documentation and reach for it.
VALIDATION_ONLY_FLAGS = {
    "--case",
    "--artifact_dir",
    "--formal_train_portion",
    "--formal_eval_portion",
    "--formal_seed",
    "--dry_run",
    # The explicit integer workload bounds for the shortened Case 12. They
    # bound a GATE's formal arm and have no production meaning; an operator
    # finding one in a node doc would reach for a control that does not
    # exist outside the harness.
    "--formal_train_files",
    "--formal_train_psd_per_file",
    "--formal_eval_files",
    "--formal_eval_psd_per_file",
    # Live-stability control (D-C2-20). The first two are the stability
    # margin, the last three are SAFETY BACKSTOPS and a poll cadence. All
    # five govern a GATE's formal arm; production training has no stop rule
    # to configure, and an operator finding one of these in a node doc would
    # reach for a control that does not exist outside the harness.
    "--formal_stable_steps",
    "--formal_min_samples",
    "--formal_max_steps",
    "--formal_max_phase_seconds",
    "--formal_poll_seconds",
}


def _harness_flags() -> set[str]:
    """Every flag the harness's parser really accepts."""
    parser_actions = harness.parse_args.__doc__ is not None  # parser is built inside
    assert parser_actions
    import argparse

    captured: set[str] = set()
    original = argparse.ArgumentParser.add_argument

    def spy(self, *args, **kwargs):
        captured.update(a for a in args if isinstance(a, str) and a.startswith("--"))
        return original(self, *args, **kwargs)

    argparse.ArgumentParser.add_argument = spy  # type: ignore[method-assign]
    try:
        with pytest.raises(SystemExit):
            harness.parse_args(["--help"])
    finally:
        argparse.ArgumentParser.add_argument = original  # type: ignore[method-assign]
    return captured


def _documented_harness_flags(text: str) -> set[str]:
    """Flags appearing in a `c2_prephase_validation.py` command block."""
    flags: set[str] = set()
    for block in re.findall(r"```bash\n(.*?)```", text, re.DOTALL):
        if "c2_prephase_validation.py" not in block and "--formal_" not in block:
            continue
        flags.update(re.findall(r"(--[a-z0-9_]+)", block))
    return flags


class TestEveryDocumentedFlagExists:
    def test_the_design_doc_documents_no_flag_the_harness_lacks(self):
        """The exact defect that stopped Lite-A: an approved command naming
        a flag that was never implemented."""
        documented = _documented_harness_flags(DESIGN_DOC.read_text(encoding="utf-8"))
        missing = documented - _harness_flags()
        assert not missing, f"documented but not implemented: {sorted(missing)}"

    def test_the_approved_gate_parameters_are_real_flags(self):
        for flag in ("--formal_train_portion", "--formal_eval_portion", "--formal_seed"):
            assert flag in _harness_flags()

    #: A removed flag may still be NAMED -- in a deviation entry, or in a
    #: description of the guard that removed it. What it must never be is
    #: offered as something an operator could type. These markers are how a
    #: line says "this is gone".
    REMOVAL_MARKERS = ("renamed", "replaced", "did not", "a different quantity", "historical")

    def test_the_renamed_flag_is_gone_from_active_text(self):
        """`--formal_trial_portion` was replaced, not aliased."""
        for line in DESIGN_DOC.read_text(encoding="utf-8").splitlines():
            if "--formal_trial_portion" not in line:
                continue
            assert any(marker in line for marker in self.REMOVAL_MARKERS), (
                f"stale flag offered as usable: {line.strip()[:100]}"
            )


class TestTheGateInvariantsAreStated:
    """Some statements in the design doc ARE the control.

    An operator reads the packet to decide what a Gate result means. If the
    doc still says a case needs an idle GPU, or still quotes a withdrawn
    5090 constant as an acceptance criterion, the code being right does not
    help — the operator will act on the document.
    """

    def _doc(self) -> str:
        return " ".join(DESIGN_DOC.read_text(encoding="utf-8").split())

    @pytest.mark.parametrize(
        "statement",
        [
            # D-C2-19 — presence is not contamination, and no idle card.
            "No case requires an idle GPU",
            "The presence of another GPU process is not contamination",
            "only that pair reruns",
            "external processes NEVER added",
            "external processes ALWAYS considered",
            # D-C2-20 — completion is live and machine-local.
            "training length is decided by live stability on this machine",
            "SAFETY BACKSTOPS, never success criteria",
            "no cap, step count, duration or measured requirement travels",
            # D-C2-21 — comparability is effect-based.
            "Presence and ordinary occupancy oscillation are not",
            "effect on the acceptance claim is the criterion",
            "The threshold is removed",
            "false-negative comparability result",
            "Per-arm analysis, never pooled",
            # Gate outcomes. The doc is where an operator reads what a Gate
            # result means, so the results themselves are a control.
            "Gate 2 Lite-A | RTX 5090",
            "Gate 2 Lite-B | H100 80GB HBM3",
            "The peaks differ between machines, and that is the design working",
            "never label an externally terminated process as a measured OOM",
        ],
    )
    def test_the_doc_states_it(self, statement):
        assert " ".join(statement.split()) in self._doc(), (
            f"the design doc no longer states: {statement}"
        )

    #: The 5090 observations. They may still APPEAR -- the derivation record
    #: and the withdrawal notice both name them -- but never on a line that
    #: reads as a current instruction.
    WITHDRAWN_CONSTANTS = ("2000 training steps", "160 inference batches")

    @pytest.mark.parametrize("constant", WITHDRAWN_CONSTANTS)
    def test_a_withdrawn_constant_is_never_offered_as_current(self, constant):
        """The PARAGRAPH is the unit, not the line.

        Markdown wraps, so the sentence carrying "Withdrawn" is routinely a
        different physical line from the one carrying the number. A
        line-scoped check reported a correctly-withdrawn passage as current
        guidance — it was measuring line breaks, not meaning.
        """
        marked = ("WITHDRAWN", "Withdrawn", "withdrawn", "Historical", "historical", "earlier")
        for para in DESIGN_DOC.read_text(encoding="utf-8").split("\n\n"):
            if constant not in para:
                continue
            assert any(m in para for m in marked), (
                f"a withdrawn 5090 constant reads as current guidance:\n{para.strip()[:300]}"
            )

    def test_the_documented_requirements_are_exactly_the_ones_that_exist(self):
        """Bidirectional, against the code — the pattern that already guards
        `PrephaseDisposition`.

        A presence check cannot catch an ADDED contradiction: deleting the
        "no idle-GPU requirement" sentence left the phrase intact elsewhere
        and every assertion still passed. This derives the set from
        `EnvironmentRequirement` instead, so reintroducing a `quiet`
        requirement fails here whether it appears first in the code or first
        in the document.
        """
        from typing import get_args

        from core.runtime_control.environment_stability import EnvironmentRequirement

        declared = set(get_args(EnvironmentRequirement))
        assert "quiet" not in declared, (
            "a quiescence requirement is back in the code; no case may demand an "
            "empty card — dynamic measurement exists to measure the card as it is"
        )
        doc = DESIGN_DOC.read_text(encoding="utf-8")
        for requirement in declared:
            assert f"`{requirement}`" in doc, (
                f"the environment requirement {requirement!r} exists in code but is "
                "undocumented; an operator cannot interpret a Gate result it never "
                "told them about"
            )
        assert "no `quiet` requirement" in doc, (
            "the document no longer records that quiescence was considered and "
            "rejected, so the next reader may reintroduce it"
        )

    def _case_12_block(self) -> str:
        """The executable Case 12 command block, as an operator would copy it."""
        doc = DESIGN_DOC.read_text(encoding="utf-8")
        start = doc.index("For `--case c12a`")
        open_fence = doc.index("```bash", start)
        return doc[open_fence : doc.index("```", open_fence + 8)]

    def test_the_training_ceiling_cannot_exhaust_before_the_backstop(self):
        """THE DERIVATION, checked against the code's own geometry.

        If the data runs out before `--formal_max_steps`, the arm ends in
        exhaustion — `INCONCLUSIVE` for a reason that has nothing to do with
        the peak — and the backstop that exists to bound the run never
        bounds it. The documented triple must therefore satisfy

            files x psd_per_file x steps_per_psd >= max_steps

        with `steps_per_psd` taken from the harness, not restated here: a
        second copy of 250 would let the two drift and the check would pass
        against its own assumption.

        MUTATION TARGET: lowering `--formal_train_psd_per_file` to 1 or 2,
        or raising `--formal_max_steps` without re-deriving it.
        """
        block = self._case_12_block()

        def flag(name: str) -> int:
            match = re.search(rf"{name}\s+(\d+)", block)
            assert match, f"{name} is absent from the executable Case 12 block"
            return int(match.group(1))

        files = flag("--formal_train_files")
        per_file = flag("--formal_train_psd_per_file")
        max_steps = flag("--formal_max_steps")
        available = files * per_file * harness._MODEL_SEGMENTS_PER_PSD

        assert available >= max_steps, (
            f"the documented ceiling supplies {available} training steps but the "
            f"backstop is {max_steps}; the arm would exhaust its data first and "
            "report INCONCLUSIVE for a reason unrelated to the peak"
        )
        # And it is the SMALLEST such integer -- capacity beyond the backstop
        # buys nothing, and an unexplained margin invites the next reader to
        # treat the number as taste rather than arithmetic.
        smallest = math.ceil(max_steps / (files * harness._MODEL_SEGMENTS_PER_PSD))
        assert per_file == smallest, (
            f"--formal_train_psd_per_file is {per_file}; the derivation gives "
            f"ceil({max_steps} / ({files} x {harness._MODEL_SEGMENTS_PER_PSD})) "
            f"= {smallest}"
        )

    def test_the_gate_tested_sha_is_recorded_exactly_once_as_such(self):
        """A Gate result is meaningless without the commit it was taken at.

        The header, the results table and the packet must all name the SAME
        SHA — a doc that reports PASS against an unstated or inconsistent
        commit is the failure mode `currently f0364f8b` already caused once.
        """
        doc = DESIGN_DOC.read_text(encoding="utf-8")
        tested = "7302c467d81a575e3e35a8f81821eb5dbd63e451"
        assert doc.count(tested) >= 3, (
            f"the Gate-tested SHA appears {doc.count(tested)} times; the header, "
            "the results table and the packet must each name it"
        )
        # No OTHER 40-hex SHA may be presented as the tested one. Scoped to
        # lines that actually CARRY a SHA -- prose referring to "the
        # Gate-tested SHA" as a concept names no commit and claims nothing.
        for line in doc.splitlines():
            carried = re.findall(r"\b[0-9a-f]{40}\b", line)
            if carried and re.search(r"Gate-tested SHA|exact tested SHA", line, re.I):
                assert tested in carried, f"a different SHA is claimed as tested: {line[:120]}"

    def test_the_status_header_matches_the_gate_outcomes(self):
        """MUTATION TARGET: leaving the header at 'NOT AUTHORIZED'.

        It said "no implementation has begun; neither branch exists" while
        C1 was merged and both gates had run.

        The withdrawn claim may still be QUOTED -- the header keeps a
        historical note saying what it used to say -- so this checks that
        every occurrence sits inside such a note. A bare substring check
        tripped on the very correction it was written to enforce, which is
        the same explanation-versus-instruction false positive that has now
        caught three guardrails in this PR.
        """
        lines = DESIGN_DOC.read_text(encoding="utf-8").splitlines()
        head = lines[: next(i for i, x in enumerate(lines) if "Implementation shape" in x)]
        joined = " ".join(" ".join(head).split())
        assert "Gate 2 Lite-A (RTX 5090): PASSED" in joined
        assert "Gate 2 Lite-B (H100): PASSED" in joined
        assert "Gate-tested SHA" in joined
        for i, line in enumerate(head):
            if "no implementation has begun" not in line:
                continue
            context = " ".join(head[max(0, i - 2) : i + 1])
            assert "Historical note" in context or "previously read" in context, (
                f"the status header asserts implementation has not started: {line[:100]}"
            )

    def test_no_gate_packet_claims_a_current_sha(self):
        """A SHA written into the packet can never be current: the commit
        that writes it changes the head.

        The packet carried `currently f0364f8b` through four commits,
        naming a head that predated the merge of master, the probe fix, the
        contamination redesign and the live-stability loop. An operator
        checking out that SHA would have gated none of them. The field is
        now an instruction to read the head, not a value.
        """
        stale = re.findall(r"currently\s+([0-9a-f]{7,40})\b", DESIGN_DOC.read_text("utf-8"))
        assert not stale, (
            f"the packet claims a SHA is current: {stale}. It cannot be — record "
            "`git rev-parse HEAD` at authorization instead."
        )

    def test_the_derivation_is_written_down_not_just_obeyed(self):
        """A number that satisfies the arithmetic but records no reason is
        the judgment call this test exists to eliminate."""
        doc = " ".join(DESIGN_DOC.read_text(encoding="utf-8").split())
        assert "The training ceiling is derived, not chosen." in doc
        assert "ceil(5000 / (8 x 250)) = ceil(2.5) = 3" in doc
        assert "ceiling on capacity, not a required workload" in doc

    def test_the_case_12_packet_no_longer_bounds_training_by_a_portion(self):
        """MUTATION TARGET: restoring `--formal_train_portion 0.01` to the
        executable Case 12 block.

        The portion decided how long the arm ran, which is precisely the
        decision live stability took away from the operator.
        """
        doc = DESIGN_DOC.read_text(encoding="utf-8")
        start = doc.index("For `--case c12a`")
        block = doc[start : doc.index("```", doc.index("```bash", start) + 8)]
        assert "--formal_train_portion" not in block, (
            "the executable Case 12 command bounds training by a portion again"
        )
        assert "--formal_stable_steps" in block
        assert "--formal_max_phase_seconds" in block


class TestValidationOnlyFlagsStayOutOfProductionDocs:
    @pytest.mark.parametrize("flag", sorted(VALIDATION_ONLY_FLAGS))
    def test_no_production_doc_offers_a_harness_flag(self, flag):
        """An operator reading the node doc must not find a control that
        only the gate harness has."""
        assert flag not in TUNER_DOC.read_text(encoding="utf-8")


class TestTheNodeDocDescribesTheCurrentProductionPath:
    """The tuner's formal path changed: a bounded GPU measurement now runs
    before formal training. A node doc still describing plan -> resource
    check -> train would send an operator looking for a phase that no longer
    exists in that order."""

    def test_it_documents_the_prephase_measurement(self):
        assert "Pre-phase GPU measurement" in TUNER_DOC.read_text(encoding="utf-8")

    @pytest.mark.parametrize(
        "disposition",
        [
            "PROCEED",
            "STOP_OVER_CAP",
            "STOP_MEASURED_OOM",
            "STOP_TIMEOUT",
            "STOP_MEASUREMENT_UNAVAILABLE",
            "STOP_PROBE_HOST_MEMORY_EXCEEDED",
            "STOP_INFRASTRUCTURE_FAILURE",
        ],
    )
    def test_every_production_disposition_is_documented(self, disposition):
        assert disposition in TUNER_DOC.read_text(encoding="utf-8")

    def test_the_dispositions_documented_are_exactly_the_ones_that_exist(self):
        """Guards both directions: a disposition added to the code without a
        doc entry, and a doc entry for one that was removed."""
        from typing import get_args

        from core.runtime_control.prephase_admission import PrephaseDisposition

        text = TUNER_DOC.read_text(encoding="utf-8")
        for value in get_args(PrephaseDisposition):
            assert value in text, f"{value} exists in code but not in the node doc"

    def test_it_states_when_the_measurement_does_not_run(self):
        text = TUNER_DOC.read_text(encoding="utf-8")
        assert "trial round" in text
        assert "device_identity" in text

    def test_it_states_the_o7_accounting(self):
        # Whitespace-normalized: the doc is hard-wrapped, and a statement
        # split across a line break is still a statement. Matching the raw
        # text would fail on reflowing a paragraph, which is noise.
        text = " ".join(TUNER_DOC.read_text(encoding="utf-8").split())
        for phrase in (
            "attempt is consumed",
            "no completed round",
            "no scientific blame",
            "no proposal shrinking",
            "no same-attempt retry",
        ):
            assert phrase in text, f"missing O-7 statement: {phrase}"

    def test_it_records_that_there_is_no_flag(self):
        """The absence of a switch is a production fact an operator will
        look for."""
        assert "There is **no flag**" in TUNER_DOC.read_text(encoding="utf-8")


class TestDocumentedDefaultsMatchTheCode:
    def test_the_deadline_and_soft_budget_match(self):
        from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
            PREPHASE_MEASUREMENT_DEADLINE_SECONDS,
            PREPHASE_MEASUREMENT_SOFT_BUDGET_SECONDS,
        )

        text = TUNER_DOC.read_text(encoding="utf-8")
        assert f"{int(PREPHASE_MEASUREMENT_DEADLINE_SECONDS)} s" in text
        assert f"{int(PREPHASE_MEASUREMENT_SOFT_BUDGET_SECONDS)} s" in text
