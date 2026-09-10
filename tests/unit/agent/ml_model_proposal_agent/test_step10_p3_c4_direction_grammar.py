"""Step 10 / P3 — C4: the proposer is TOLD the direction, and shown it.

Design: ``docs/design/generic_framework_upgrade/step_10_orchestration_task_binding/
pr_10_p3_proposer_typed_evidence.md`` §4.5 (D1/D2/D3), §5 (the three-task
control), §7 C4; parent §11.3.

The defect this owns
--------------------
No proposer prompt stated the run's metric or its direction ANYWHERE, while
the comparison stage asked the model to name the SOTA and the causal stage
asked it to author a numeric prediction. Every worked example it could see was
higher-is-better: ``current 1.5 -> predicted 2.5``, with the refutation
threshold BELOW current. Under a lower-is-better metric a pattern-matching
model copies that shape and authors an inverted band — and nothing in the
prompt contradicts it.

Expected text is HAND-WRITTEN here, never generated from the renderer. A
fixture that asked the code what it produces would pass for any direction,
including the wrong one. DAVIS (``lower``) is the falsifier: every assertion
about it is the arithmetic opposite of the TIDMAD one on the same inputs.

Boundary: these tests own the RENDERED GRAMMAR. Whether a real model obeys it
is a different failure class and is Gate 1's (§8.2) — deterministic tests
prove the prompt is correct, not that the model reads it.
"""

from __future__ import annotations

import pytest

from agent.schemas.proposer_evidence import build_proposer_evidence
from nodes.ml_model_proposal_agent.evidence_rendering import (
    render_falsifiable_prediction_example,
    render_metric_context_block,
)

#: The three tracks, plus the absence state. Identities are the task-shaped
#: ones §5 names: TIDMAD higher (negative-valued), Pets accuracy higher,
#: DAVIS mse LOWER.
TIDMAD = {"metric_id": "tidmad_denoising_score", "direction": "higher"}
PETS = {"metric_id": "fixture_accuracy", "direction": "higher"}
DAVIS = {"metric_id": "fixture_mse", "direction": "lower"}

#: Every word that asserts a direction. The absence state must contain NONE of
#: them: a named absence that still says "higher" has not refused anything.
DIRECTION_WORDS = ("higher", "lower", "maximize", "minimize", "largest", "smallest")


def evidence(identity: dict | None):
    payload: dict = {"model_types": []}
    if identity is not None:
        payload["metric_identity"] = identity
    return build_proposer_evidence(payload)


def context(identity: dict | None) -> str:
    return render_metric_context_block(evidence(identity))


def example(identity: dict | None) -> str:
    return render_falsifiable_prediction_example(evidence(identity))


class TestD1TheMetricContextStatement:
    """The run's metric and direction, stated once, from the ONE authority."""

    def test_tidmad_states_higher(self) -> None:
        block = context(TIDMAD)
        assert "golden metric `tidmad_denoising_score` (higher is better)" in block
        assert "Better means **higher**; worse means lower." in block
        assert "The task is to maximize it." in block

    def test_pets_states_higher(self) -> None:
        block = context(PETS)
        assert "golden metric `fixture_accuracy` (higher is better)" in block
        assert "Better means **higher**" in block

    def test_davis_states_lower(self) -> None:
        """The falsifier. Every clause is the opposite of TIDMAD's."""
        block = context(DAVIS)
        assert "golden metric `fixture_mse` (lower is better)" in block
        assert "Better means **lower**; worse means higher." in block
        assert "The task is to minimize it." in block
        assert "maximize" not in block

    def test_the_two_directions_produce_different_blocks(self) -> None:
        """Anti-vacuity: a renderer ignoring direction would fail here."""
        assert context(TIDMAD) != context(DAVIS)

    def test_absent_identity_names_the_absence_and_states_no_direction(self) -> None:
        """Q-10-2's named absence, rendered rather than defaulted."""
        block = context(None)
        assert "metric direction unavailable / metric_spec absent" in block
        assert "Do NOT assume which direction is better" in block
        for word in DIRECTION_WORDS:
            assert word not in block.lower(), (
                f"the absence block asserts a direction with {word!r} — a named "
                "absence that still implies a direction has refused nothing"
            )

    def test_the_threshold_semantic_is_stated_direction_correctly(self) -> None:
        """The D2 aligning sentence (§4.5) — added after Gate 1 observed the gap.

        Candidate ``b94b2da1`` rendered a correct DAVIS example (1.5 -> 0.5,
        threshold 1.8) and a real model still authored ``current 0.0172 ->
        predicted 0.0159, threshold 0.0170``: the prediction moved the right
        way, but the threshold landed BETWEEN the prediction and the current
        value — read as a "minimum improvement bar" rather than the refuted
        side. Three numbers in an example do not teach a semantic. These
        assertions pin the words that do, in both regimes, and they name the
        wrong reading explicitly because that is the one a capable model
        actually reached for.
        """
        lower = context(DAVIS)
        assert "marks the REFUTED side of `current_value`" in lower
        assert "**higher** side of `current_value`" in lower
        assert "NOT between your prediction and the" in lower
        assert "a result lower than `current_value` is what confirms it" in lower

        higher = context(TIDMAD)
        assert "**lower** side of `current_value`" in higher
        assert "a result higher than `current_value` is what confirms it" in higher

    def test_the_threshold_semantic_inverts_between_regimes(self) -> None:
        """Anti-vacuity: a fixed sentence would satisfy one regime, not both."""
        assert "**higher** side" in context(DAVIS)
        assert "**higher** side" not in context(TIDMAD)
        assert "**lower** side" in context(TIDMAD)
        assert "**lower** side" not in context(DAVIS)

    def test_absent_identity_forbids_a_ranking_claim(self) -> None:
        block = context(None)
        assert "state-of-the-art" in block
        assert "nothing has been ranked" in block


class TestD2TheAuthoringExample:
    """The numbers the model copies — moved onto the declared direction."""

    def test_tidmad_moves_upward_with_the_threshold_below(self) -> None:
        """Hand-computed: better is HIGHER, so predicted > current and the
        refuted side is BELOW current."""
        block = example(TIDMAD)
        assert '"current_value": 1.5,' in block
        assert '"predicted_value": 2.5,' in block
        assert '"threshold_for_refutation": 1.2,' in block

    def test_tidmad_reproduces_the_pre_migration_literal_exactly(self) -> None:
        """Backward parity, stated as its own claim.

        The template's hard-coded example WAS 1.5 / 2.5 / 1.2. Under `higher`
        the renderer must reproduce it byte-for-byte, so a TIDMAD-shaped run
        sees the same three numbers it always saw and the delta is confined to
        the regimes that were previously wrong.
        """
        assert '"current_value": 1.5,\n    "predicted_value": 2.5,' in example(TIDMAD)

    def test_pets_moves_upward(self) -> None:
        block = example(PETS)
        assert '"predicted_value": 2.5,' in block
        assert '"threshold_for_refutation": 1.2,' in block

    def test_davis_moves_DOWNWARD_with_the_threshold_ABOVE(self) -> None:
        """The sign falsifier, hand-computed.

        Better is LOWER, so the predicted value must fall (1.5 -> 0.5) and the
        REFUTED side is ABOVE current (1.8). An upward example here, or a
        threshold below current, is precisely the inverted band this delta
        exists to stop.
        """
        block = example(DAVIS)
        assert '"current_value": 1.5,' in block
        assert '"predicted_value": 0.5,' in block
        assert '"threshold_for_refutation": 1.8,' in block

    @pytest.mark.parametrize(
        ("identity", "predicted", "threshold"),
        [(TIDMAD, 2.5, 1.2), (PETS, 2.5, 1.2), (DAVIS, 0.5, 1.8)],
    )
    def test_the_threshold_is_always_on_the_refuted_side(
        self, identity: dict, predicted: float, threshold: float
    ) -> None:
        """The property, stated once over all three tracks.

        "Refuted side" means the side of ``current_value`` AWAY from the
        prediction. Asserted as an inequality rather than by re-reading the
        literals, so it stays true if the example values are ever re-chosen.
        """
        current = 1.5
        block = example(identity)
        assert f'"predicted_value": {predicted},' in block
        assert f'"threshold_for_refutation": {threshold},' in block
        assert (predicted > current) != (threshold > current), (
            "predicted and threshold must sit on OPPOSITE sides of current"
        )

    def test_the_metric_example_names_the_run_metric(self) -> None:
        """D2 owns the one task-science literal it removes.

        ``'denoising_score'`` was hard-coded in a FRAMEWORK template. It is now
        the run's declared id, which is the only proposer task-science
        migration this PR is authorised to make (§3).
        """
        assert "'tidmad_denoising_score'" in example(TIDMAD)
        assert "'fixture_mse'" in example(DAVIS)

    def test_the_framework_template_no_longer_carries_the_tidmad_literal(self) -> None:
        from pathlib import Path

        template = (
            Path(__file__).resolve().parents[4]
            / "agent/prompt_templates/proposal/causal_reasoning_stage.md"
        ).read_text(encoding="utf-8")
        assert "denoising_score" not in template

    def test_absent_identity_omits_the_numeric_example_entirely(self) -> None:
        """Never a defaulted upward example."""
        block = example(None)
        assert '"current_value": 1.5' not in block
        assert '"predicted_value": 2.5' not in block
        assert "do not assume which way is better" in block
        for word in ("higher", "lower", "upward", "downward"):
            assert word not in block.lower(), (
                f"the absence example implies a direction with {word!r}"
            )

    def test_the_two_directions_produce_different_examples(self) -> None:
        assert example(TIDMAD) != example(DAVIS)


class TestD3TheComparisonSotaWording:
    """SOTA is BEST under the stated direction — a static template rewrite."""

    @staticmethod
    def _template() -> str:
        from pathlib import Path

        return (
            Path(__file__).resolve().parents[4]
            / "agent/prompt_templates/proposal/comparison_stage.md"
        ).read_text(encoding="utf-8")

    def test_the_rule_defines_sota_by_direction(self) -> None:
        text = self._template()
        assert "SOTA means BEST under this run's metric direction" in text
        # The rule is hard-wrapped in the template, so the claim is asserted on
        # the collapsed text rather than on one physical line.
        collapsed = " ".join(text.split())
        assert "not the largest number." in collapsed
        assert "the SOTA is the model with the LOWEST score" in collapsed
        assert 'calling the highest one "state of the art" would be exactly backwards' in (
            collapsed
        )

    def test_the_rule_handles_the_unavailable_case_without_contradicting_the_output_format(
        self,
    ) -> None:
        """Refusing to rank must still say what to PUT in the required JSON.

        The stage's output format declares `sota_model_type` / `sota_score`
        unconditionally. An instruction that says only "do not name a SOTA"
        leaves the model to invent its own resolution — omit the keys, null
        them, or fill them with an apology — and whatever it picks rides into
        every later stage as `accumulated["comparison"]`. Adversarial review
        caught that contradiction; the rule now names the exact shape.
        """
        collapsed = " ".join(self._template().split())
        assert "do NOT invent a ranking" in collapsed
        assert '`"sota_model_type": null` and `"sota_score": null`' in collapsed
        assert "Emitting the keys as null is required" in collapsed

    def test_the_rule_points_at_the_rendered_block(self) -> None:
        """D3 is static; it must reference D1 rather than restate a direction.

        A static rule that named a direction itself would be a SECOND
        declaration site, which is what the whole ordering architecture forbids.
        """
        text = self._template()
        assert "Metric context block above" in text


class TestThePlaceholderWiring:
    """Substitution is ``str.replace``; a stray token ships literally."""

    @staticmethod
    def _read(name: str) -> str:
        from pathlib import Path

        return (
            Path(__file__).resolve().parents[4] / "agent/prompt_templates/proposal" / name
        ).read_text(encoding="utf-8")

    @pytest.mark.parametrize(
        ("template", "token", "expected"),
        [
            ("comparison_stage.md", "{metric_context_block}", 1),
            ("causal_reasoning_stage.md", "{metric_context_block}", 1),
            ("causal_reasoning_stage.md", "{falsifiable_prediction_example}", 1),
            # The proposing stage neither ranks nor authors a prediction, so it
            # declares neither placeholder and both substitutions are no-ops.
            ("proposing_stage.md", "{metric_context_block}", 0),
            ("proposing_stage.md", "{falsifiable_prediction_example}", 0),
        ],
    )
    def test_each_placeholder_appears_exactly_where_it_belongs(
        self, template: str, token: str, expected: int
    ) -> None:
        assert self._read(template).count(token) == expected

    def test_no_rendered_prompt_ships_an_unsubstituted_token(self, tmp_path) -> None:
        """The failure mode of a typo'd key: the literal brace token reaches
        the model. Checked on the real assembled prompts, both modes."""
        from tests.unit.agent.ml_model_proposal_agent.test_step00_prompt_goldens import (
            pin_environment,
        )
        from tests.unit.agent.ml_model_proposal_agent.test_step10_p3_c0_baselines import (
            capture_pipeline,
            full_coverage_interpretation,
        )

        monkeypatch = pytest.MonkeyPatch()
        try:
            index = pin_environment(tmp_path, monkeypatch)
            for mode in ("explore", "exploit"):
                caps = capture_pipeline(
                    tmp_path,
                    index,
                    mode=mode,
                    interpretation=full_coverage_interpretation(),
                    health=True,
                )
                for _method, label, system, user in caps:
                    for token in ("{metric_context_block}", "{falsifiable_prediction_example}"):
                        assert token not in system, f"{label} ({mode}) system carries {token}"
                        assert token not in user, f"{label} ({mode}) user carries {token}"
        finally:
            monkeypatch.undo()

    def test_the_mindset_override_does_not_displace_the_blocks(self) -> None:
        """D1/D2 live in the BASE template, not the mode block.

        ``load_stage_prompt`` replaces ``{# EXPLORATION_MODE_BLOCK #}`` with the
        mindset when one is supplied, so anything that lived in the mode file
        would vanish under an operator mindset. Both placeholders are above
        that marker; this proves it on the assembled prompt.
        """
        from agent.prompt_templates.proposal import load_stage_prompt

        rendered = load_stage_prompt(
            "causal_reasoning_stage",
            exploration_mode="explore",
            template_vars={
                "metric_context_block": "METRIC-CONTEXT-SENTINEL",
                "falsifiable_prediction_example": "PREDICTION-SENTINEL",
                "minimum_boldness": "0.05",
                "task_background_block": "",
                "available_losses_block": "",
            },
            mindset="A MINDSET THAT REPLACES THE MODE BLOCK",
        )
        assert "METRIC-CONTEXT-SENTINEL" in rendered
        assert "PREDICTION-SENTINEL" in rendered
        assert "A MINDSET THAT REPLACES THE MODE BLOCK" in rendered


class TestTheDeltaIsConfinedToD1D2D3:
    """Everything outside the declared surfaces is parity-owned."""

    def test_the_legacy_prompt_carries_no_authoring_delta(self, tmp_path) -> None:
        """§4.5: legacy prompts carry NONE of D1/D2/D3.

        Legacy authors no prediction at all — ``_run_legacy`` never extracts a
        ``falsifiable_prediction`` and the commit prompt's JSON spec has no such
        field — so a direction-authoring delta there would have no referent, and
        its byte parity is the compatibility value §11.2 protects.
        """
        from tests.unit.agent.ml_model_proposal_agent.test_step00_prompt_goldens import (
            pin_environment,
        )
        from tests.unit.agent.ml_model_proposal_agent.test_step10_p3_c0_baselines import (
            capture_legacy,
            full_coverage_interpretation,
        )

        monkeypatch = pytest.MonkeyPatch()
        try:
            index = pin_environment(tmp_path, monkeypatch)
            prompt = capture_legacy(
                tmp_path,
                index,
                interpretation=full_coverage_interpretation(),
                health=True,
            )
        finally:
            monkeypatch.undo()
        assert "## Metric context" not in prompt
        assert "SOTA means BEST" not in prompt

    def test_the_rendering_module_contains_no_comparison_shaped_derivation(self) -> None:
        """A narrow, honestly-scoped check — NOT the whole C-P3-2 claim.

        It owns exactly one shape in exactly one file: a ``Compare`` node in
        ``evidence_rendering.py`` testing ``direction`` against a direction
        literal. A dict dispatch, a ``match``, or a derivation in another module
        would pass here.

        The BROAD claim — no production surface outside the metric and order
        modules executes a ``"higher"``/``"lower"`` literal at all — is owned by
        Step 06's C5 boundary guard
        (``tests/unit/execute_tools/test_step06_c5_boundary_and_structure.py``),
        which scans every production file and pins the two allowed modules as
        exact multisets. That guard caught a real violation in this PR's own
        Gate harness, so it is doing the work; this one is a local tripwire
        beside the code it watches.
        """
        import ast
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[4]
            / "nodes/ml_model_proposal_agent/evidence_rendering.py"
        ).read_text(encoding="utf-8")
        offenders = []
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Compare):
                text = ast.unparse(node)
                if "direction" in text and ("higher" in text or "lower" in text):
                    offenders.append(f"{node.lineno}: {text}")
        assert offenders == [], (
            "a renderer compares the direction declaration itself instead of "
            f"asking MetricOrder: {offenders}"
        )


pytestmark = pytest.mark.usefixtures("synthetic_dataset_profile")
