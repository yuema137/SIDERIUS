"""Step 12 / PR-12a — C7-2: composed prompts carry no TIDMAD science.

Design:
``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12a_composed_path_closure.md`` §5 C7, D-12a-5, and the §8.9 classification
table this implements.

Four blocks are gated. The classification governs what each composed rendering
must be — the rule is that removing TIDMAD science is NOT sufficient:

    P1  `denoising_score` NOUN     (2) required -> "field", not "metric".
                                   The KEY itself is frozen and stays.
    P2  built-in model roster      (2) required -> a pointer to the run's own
                                   [MODEL ARCHITECTURE DESCRIPTION], which
                                   `plan()` already renders on both paths
    P3  per-file table protocol    (1) optional -> nothing
    R1  reflector score naming     (1) optional naming; the judgement PROTOCOL
                                   is task-generic and stays in full

WHERE THE GATING LIVES: in the render authority, as a rendered STRING. The
assembly sites in `llm_bridge` substitute tokens exactly as they did before
and never learn what a composition is — which is why the legacy rendered
bytes could not move even by accident.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.prompt_templates.tuner.rendering import (
    LEGACY_AVAILABLE_MODELS_BLOCK,
    LEGACY_PER_FILE_TABLE_PROTOCOL,
    build_tuner_task_render,
    render_available_models_block,
    render_per_file_table_protocol,
    render_score_display_noun,
    render_score_field_noun,
)
from execute_tools.health_checks import _plugin_binding
from execute_tools.health_checks.registry import _PROVIDER_REGISTRY, _REGISTRY
from tests.helpers.composition_data_root import COMPOSED_TEST_DATA_ROOT
from tests.helpers.step12_pr12a_prompt_capture import capture_tuner_prompts
from workflows.model_exploration import build_task_composition_ref
from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "step10_p1"

#: Tokens that name TIDMAD's science. A composed prompt must contain none of
#: them. Deliberately NOT including `denoising_score`: that is a FROZEN RECORD
#: KEY every task's history JSON carries, and the model must be told to read
#: it (F-12a-C7-1).
BANNED_ON_A_COMPOSED_PROMPT = (
    "PositionalUNet",
    "FCNet",
    "TransformerModel",
    "SimpleWaveNet",
    "RNNSeq2Seq",
    "raw_baseline",
    "ground_truth",
    "Impact_Score",
    "Denoising Score",
    "DENOISING SCORE",
)


@pytest.fixture(autouse=True)
def _isolated_run_scope():
    registry = dict(_REGISTRY)
    providers = dict(_PROVIDER_REGISTRY)
    _plugin_binding.reset_run_scope()
    try:
        yield
    finally:
        _REGISTRY.clear()
        _REGISTRY.update(registry)
        _PROVIDER_REGISTRY.clear()
        _PROVIDER_REGISTRY.update(providers)
        _plugin_binding.reset_run_scope()


class TestTheRenderersGateExactlyAsClassified:
    """Unit-level, one row per §8.9 classification."""

    def test_p1_the_frozen_key_stays_and_only_the_noun_moves(self):
        assert render_score_field_noun(composed=False) == "metric"
        assert render_score_field_noun(composed=True) == "field"

    def test_p2_legacy_is_verbatim_and_composed_points_at_the_real_authority(self):
        assert render_available_models_block(composed=False) == LEGACY_AVAILABLE_MODELS_BLOCK

        composed = render_available_models_block(composed=True)
        assert "[MODEL ARCHITECTURE DESCRIPTION]" in composed
        assert "do not assume" in composed.lower()
        for name in ("PositionalUNet", "FCNet", "SimpleWaveNet"):
            assert name not in composed

    def test_p3_legacy_is_verbatim_and_composed_renders_NOTHING(self):
        assert render_per_file_table_protocol(composed=False) == LEGACY_PER_FILE_TABLE_PROTOCOL
        assert render_per_file_table_protocol(composed=True) == ""

    def test_r1_only_the_naming_moves(self):
        assert render_score_display_noun(composed=False) == "Denoising Score"
        assert render_score_display_noun(composed=True) == "score"

    def test_the_legacy_blocks_are_carried_VERBATIM(self):
        """The whole reason legacy bytes cannot move: the render authority
        holds the template's exact former bytes, not a re-typed copy."""
        assert LEGACY_AVAILABLE_MODELS_BLOCK.startswith("### AVAILABLE MODELS:\n")
        assert "**PositionalUNet (punet)**" in LEGACY_AVAILABLE_MODELS_BLOCK
        assert LEGACY_PER_FILE_TABLE_PROTOCOL.startswith("### PER-FILE PERFORMANCE TABLE:\n")
        assert "Impact_Score" in LEGACY_PER_FILE_TABLE_PROTOCOL

    def test_the_default_is_LEGACY_on_both_the_parameter_and_the_field(self):
        """Every existing caller renders the legacy bytes without knowing this
        mechanism exists — the reason no other suite had to change."""
        render = build_tuner_task_render(
            dataset=type("D", (), {"num_files": 20, "segments_per_file": 100})(),
            model_io_contract=None,
            health_config=type("H", (), {"health_gates": []})(),
            efficiency_band_fraction=0.05,
        )
        assert render.available_models_block == LEGACY_AVAILABLE_MODELS_BLOCK
        assert render.per_file_table_protocol == LEGACY_PER_FILE_TABLE_PROTOCOL
        assert render.score_field_noun == "metric"
        assert render.score_display_noun == "Denoising Score"


class TestAComposedRunsRenderedPromptsAreFreeOfTidmadScience:
    """The end-to-end property, through the REAL tuner render paths.

    Replaces C0's inverted guard (e), which asserted the composed planner
    prompt still carried the five built-in descriptions.
    """

    #: The composed TIDMAD manifest, deliberately — and it makes this a
    #: STRICTER subject, not a convenient one. The gating keys on composition
    #: PRESENCE (C-P56-1), so a composed TIDMAD run must lose TIDMAD's science
    #: too; a gate that keyed on task identity would leave every banned token
    #: in place here and this class would go green for the wrong reason.
    #:
    #: It is also the only composed fixture that COMPLETES rounds under the
    #: Step-00 canned plans: those carry a `segmentation_size` valid for a
    #: 256-sample profile, so a composed Pets drive fails validation before it
    #: ever reaches the reflector. That is a fixture limit, not a product
    #: statement — `test_a_non_tidmad_composed_planner_is_also_clean` covers
    #: the other topology as far as it runs.
    TASK = "tidmad"

    @classmethod
    def _composed_prompts(cls, tmp_path, monkeypatch, task: str | None = None):
        composition = compose_run_task_bindings(
            str(FIXTURES / (task or cls.TASK) / "composition.yaml")
        )
        with bind_run_task_composition(composition, physical_data_root=COMPOSED_TEST_DATA_ROOT):
            import json

            from tests.helpers.step00_pseudo_iteration import run_bounded_pseudo_iteration
            from tests.helpers.step12_pr12a_prompt_capture import (
                PREFLIGHT_FIXTURE,
                capturing_bridge_class,
            )

            index = tmp_path / "index.json"
            index.write_text("[]", encoding="utf-8")
            bridge = capturing_bridge_class()()
            run_bounded_pseudo_iteration(
                tmp_path,
                monkeypatch,
                preflight_results=json.loads(PREFLIGHT_FIXTURE.read_text(encoding="utf-8"))[
                    "results"
                ],
                bridge=bridge,
                capability_index_path=str(index),
                input_overrides={"task_composition_ref": build_task_composition_ref(composition)},
            )
        out: dict[str, list[str]] = {}
        for call in bridge.captures:
            out.setdefault(call["label"], []).append(call["system"] + "\n" + call["user"])
        return out

    def test_no_banned_tidmad_token_survives(self, tmp_path, monkeypatch):
        prompts = self._composed_prompts(tmp_path, monkeypatch)
        assert prompts.get("tuner.planner"), "the composed run must reach the planner"
        assert prompts.get("tuner.reflector"), "the composed run must reach the reflector"

        violations = [
            f"{label}[{index}]: {token!r}"
            for label, payloads in prompts.items()
            for index, payload in enumerate(payloads)
            for token in BANNED_ON_A_COMPOSED_PROMPT
            if token in payload
        ]
        assert not violations, "TIDMAD science reached a COMPOSED prompt:\n  " + "\n  ".join(
            violations
        )

    def test_the_frozen_record_key_is_STILL_THERE(self, tmp_path, monkeypatch):
        """The other half, and the one a token-ban alone would get wrong: the
        model still has to be told which key carries the score, because a
        composed run's history JSON really does use `denoising_score`."""
        prompts = self._composed_prompts(tmp_path, monkeypatch)
        planner = prompts["tuner.planner"][0]
        assert "`denoising_score` field" in planner
        assert "`denoising_score` metric" not in planner

    def test_the_replacement_semantics_are_PRESENT_not_merely_absent(self, tmp_path, monkeypatch):
        """D-12a-5's governing rule: a class-(2) block must be REPLACED, never
        just deleted. A blanket named-absence treatment is not acceptable."""
        prompts = self._composed_prompts(tmp_path, monkeypatch)
        planner = prompts["tuner.planner"][0]
        assert "### THE MODEL UNDER TUNING:" in planner
        assert "[MODEL ARCHITECTURE DESCRIPTION]" in planner

    def test_a_non_tidmad_composed_planner_is_also_clean(self, tmp_path, monkeypatch):
        """A second topology, as far as the canned fixtures carry it. The Pets
        drive stops before the reflector (see TASK above), so this asserts the
        PLANNER surface only — stated rather than quietly parametrized away."""
        prompts = self._composed_prompts(tmp_path, monkeypatch, task="pets")
        planner = prompts["tuner.planner"][0]
        for token in BANNED_ON_A_COMPOSED_PROMPT:
            assert token not in planner, token

    def test_the_generic_judgement_protocol_SURVIVES(self, tmp_path, monkeypatch):
        """R1 is class (1) for its NAMING only. If the gating had removed the
        protocol with the name, the reflector would lose task-generic
        guidance it needs on every task."""
        prompts = self._composed_prompts(tmp_path, monkeypatch)
        reflector = prompts["tuner.reflector"][0]
        assert "relative metric" in reflector
        assert "ALWAYS compare against the Baseline Score and Best Score So Far" in reflector
        assert "NEVER call a result a failure just because the score is negative." in reflector


class TestTheAssemblySiteNeverLearnsAboutComposition:
    """The structural reason legacy bytes could not move by accident."""

    def test_llm_bridge_does_not_read_a_composition_authority(self):
        source = (REPO_ROOT / "agent" / "llm_bridge.py").read_text(encoding="utf-8")
        for forbidden in (
            "active_task_data_path",
            "active_composition_fingerprint",
            "task_composition_ref",
            "bind_run_task_composition",
        ):
            assert forbidden not in source, (
                f"agent/llm_bridge.py reads {forbidden!r} — the assembly site "
                f"must substitute tokens and let the render authority decide"
            )

    def test_the_prompt_module_is_still_composition_free(self):
        source = (REPO_ROOT / "agent" / "prompts.py").read_text(encoding="utf-8")
        assert "task_composition" not in source
        assert "active_task_data_path" not in source
