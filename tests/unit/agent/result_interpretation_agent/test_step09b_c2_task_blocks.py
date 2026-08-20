"""Step 09b C2 — InterpretationTaskBlocks, the TIDMAD declaration, and the
task-free framework templates.

Owners in this file (design §11.2 / §16):

* the SENTENCE-ACCOUNTING census — every migrated (B) science fragment lives
  in the TIDMAD-assembled prompt of its phase and NOT in the framework
  template; framework (A) anchors stay; every declared rewording (DW-n) is
  pinned old-absent/new-present. Fragments are compared WHITESPACE-NORMALIZED
  because the declaration re-wraps the long single-line instruction strings
  (a declared layout-only transformation, ledger §22.2).
* the splice/omission contract — absent blocks render NOTHING (no header, no
  bytes; block-less goldens), sections render only in their frozen phases,
  and the placeholder never leaks.
* the `InterpretationTaskBlocks` value contract (census 4: exactly the four
  framework keys) and the fail-closed adapter.
* census 3 (generic surfaces carry zero task-name tokens in executable
  string literals) and census 3b (the ONE allowed occurrence is the
  adapter's default-path CONSTANT — no branch, no dispatch, no second task).
* census 6 (exactly one production module knows the declaration path).
* the census-1 source half: `rendering.py` carries no science token outside
  the ONE §5.4-exempt schema-derived label (F-09b-3).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
import yaml

from agent.prompt_templates.interpretation.rendering import (
    PER_MODEL_SYSTEM_PROMPT,
    SYNTHESIS_SYSTEM_PROMPT,
    _build_per_model_system_prompt,
    _build_synthesis_system_prompt,
)
from agent.prompt_templates.interpretation.task_blocks import (
    LEGACY_DEFAULT_TASK_INTERPRETATION_CONFIG,
    load_interpretation_task_blocks,
)
from agent.schemas.interpretation import InterpretationInput, InterpretationTaskBlocks
from tests.helpers.golden import assert_golden

REPO_ROOT = Path(__file__).resolve().parents[4]
GOLDENS = Path(__file__).parent / "goldens"

_TASK_DESCRIPTION = "Denoise SQUID data."


def _norm(text: str) -> str:
    """Whitespace-normalize for fragment comparison (declared layout rule)."""
    return " ".join(text.split())


def _inp(blocks: InterpretationTaskBlocks | None) -> InterpretationInput:
    return InterpretationInput(
        model_types=["wavenet"],
        task_description=_TASK_DESCRIPTION,
        task_blocks=blocks,
    )


TIDMAD_BLOCKS = load_interpretation_task_blocks()
PM_ASSEMBLED = _build_per_model_system_prompt(_inp(TIDMAD_BLOCKS))
SY_ASSEMBLED = _build_synthesis_system_prompt(_inp(TIDMAD_BLOCKS))
PM_BARE = _build_per_model_system_prompt(_inp(None))
SY_BARE = _build_synthesis_system_prompt(_inp(None))


# ---------------------------------------------------------------------------
# Sentence accounting (design §22.2 — the executable half)
# ---------------------------------------------------------------------------

#: Migrated TIDMAD science (class B): (distinctive fragment, phases it must
#: reach). Every fragment must appear in the ASSEMBLED prompt of each named
#: phase and in NO framework template.
B_FRAGMENTS: list[tuple[str, tuple[str, ...]]] = [
    ("the Log-of-Mean trap", ("pm", "sy")),
    (
        "The aggregate denoising scalar is the log of a *sum* of per-segment linear energies",
        ("pm", "sy"),
    ),
    (
        "**`Linear_Weight`** — the file's current share of the scalar's linear denominator",
        ("pm", "sy"),
    ),
    (
        "**`Impact_Score`** — the log-scalar gain you would obtain by lifting this file's `model` to its `ground_truth`",
        ("pm", "sy"),
    ),
    (
        "A per-file score table: one row per validation file with raw_baseline, ground_truth, model, gain_vs_raw, headroom_vs_gt, Linear_Weight, and Impact_Score columns",
        ("pm", "sy"),
    ),
    (
        "Data volume: how many PSD segments were used for training vs baseline (baseline typically uses 4000)",
        ("pm", "sy"),
    ),
    ("When you analyse bottlenecks for this model:", ("pm",)),
    (
        "Rank the files by `Impact_Score` descending — that is the per-iter opportunity ranking",
        ("pm",),
    ),
    (
        "Do not memorise file-index labels across iterations — re-read the column each iter.",
        ("pm",),
    ),
    (
        "Read the per-file table by Impact_Score descending. Cite specific files BY file_index",
        ("pm",),
    ),
    ("do NOT declare this model saturated while a clear lever remains", ("pm",)),
    (
        "rank by Impact_Score; cite Linear_Weight as context, not as a ranking metric on its own; never use fixed cutoffs",
        ("pm",),
    ),
    ("reference training_psd_segments, trial_portion changes across rounds", ("pm",)),
    ("all sampled files saturated against their ground_truth ceiling", ("pm",)),
    ("When you analyse bottlenecks across the candidate models:", ("sy",)),
    (
        "**Rank by `Impact_Score` descending** to identify each model's largest remaining levers",
        ("sy",),
    ),
    (
        "There is no fixed cutoff; you compare the distribution against the scale of progress.",
        ("sy",),
    ),
    (
        "Cite Impact_Score, Linear_Weight, and gain_vs_raw together when discussing per-file bottlenecks",
        ("sy",),
    ),
    (
        "Read the Impact_Score column FIRST — never decide saturation from model_scalar alone",
        ("sy",),
    ),
    (
        "identify the file_index with the largest Impact_Score as the primary objective for the next iteration",
        ("sy",),
    ),
    ("declare ceiling reached rather than manufacture an architectural deficiency", ("sy",)),
    (
        "rank by Impact_Score descending; cite Linear_Weight as context, not as a ranking metric on its own; do not use fixed cutoffs or fixed file-index labels",
        ("sy",),
    ),
    ('you MUST cite that file\'s file_index explicitly (e.g. "file 17")', ("sy",)),
]

#: Framework (class A) anchors that must STAY in the templates.
A_ANCHORS_PM = [
    "You are a senior ML research analyst.",
    "{TASK_DESCRIPTION}",
    "Produce a JSON object with exactly these fields:",
    "How sensitive the model is to data volume. Did scores improve when trial_portion increased?",
    "ranked by importance, evidence-based, reference actual values",
    "Output only the JSON object — no preamble, no commentary, no markdown",
]
A_ANCHORS_SY = [
    "You are a senior ML research analyst.",
    "{TASK_DESCRIPTION}",
    "One sentence: the single most critical insight that motivates the next step.",
    "MUST compare across models, reference actual scores",
    "Do not repeat per-model findings verbatim — synthesise and draw cross-model conclusions",
]

#: Declared framework rewordings (DW-n, ledger §22.2): old bytes gone, new
#: bytes present, in the named template.
DW_PAIRS = [
    (
        "pm",
        "per-file behaviour, data sensitivity",
        "per-sample behaviour where per-sample evidence exists",
    ),
    ("pm", "Best and worst denoising scores", "Best and worst golden-metric scores"),
    (
        "pm",
        "Read the per-file table by Impact_Score descending",
        "state explicitly that no per-sample evidence is available — never invent per-sample claims",
    ),
    (
        "pm",
        "'all sampled files saturated against their ground_truth ceiling'",
        "root causes (e.g. 'architecture capacity ceiling'), not symptoms",
    ),
    (
        "pm",
        "rank by Impact_Score; cite Linear_Weight as context",
        "follow the task guidance when per-sample evidence is present; otherwise state its absence",
    ),
    (
        "pm",
        "reference training_psd_segments",
        "reference the training data volume and trial_portion changes across rounds",
    ),
    (
        "sy",
        "Cite Impact_Score, Linear_Weight, and gain_vs_raw together",
        "Per-sample comparison across models.",
    ),
    (
        "sy",
        "Read the Impact_Score column FIRST",
        "One sentence: the single most critical insight that motivates the next step.",
    ),
    ("sy", "grounded in the Impact_Score distribution", "take_home_message: exactly one sentence"),
]


class TestSentenceAccounting:
    @pytest.mark.parametrize("fragment,phases", B_FRAGMENTS, ids=lambda x: str(x)[:48])
    def test_every_migrated_fragment_reaches_its_phase_and_left_the_framework(
        self, fragment, phases
    ):
        frag = _norm(fragment)
        assembled = {"pm": _norm(PM_ASSEMBLED), "sy": _norm(SY_ASSEMBLED)}
        templates = {"pm": _norm(PER_MODEL_SYSTEM_PROMPT), "sy": _norm(SYNTHESIS_SYSTEM_PROMPT)}
        for phase in phases:
            assert frag in assembled[phase], f"migrated science missing from {phase} assembly"
        for name, tpl in templates.items():
            assert frag not in tpl, f"task science still framework-owned in {name} template"

    def test_framework_anchors_stayed(self):
        for anchor in A_ANCHORS_PM:
            assert anchor in PER_MODEL_SYSTEM_PROMPT, anchor
        for anchor in A_ANCHORS_SY:
            assert anchor in SYNTHESIS_SYSTEM_PROMPT, anchor

    @pytest.mark.parametrize("phase,old,new", DW_PAIRS, ids=lambda x: str(x)[:40])
    def test_declared_rewordings(self, phase, old, new):
        # Whitespace-normalized: the templates wrap prose at ~78 cols, so a
        # multi-word fragment may straddle a line break (declared layout rule).
        template = _norm(PER_MODEL_SYSTEM_PROMPT if phase == "pm" else SYNTHESIS_SYSTEM_PROMPT)
        assert _norm(old) not in template, f"DW old bytes survived in {phase}: {old!r}"
        assert _norm(new) in template, f"DW new bytes missing in {phase}: {new!r}"

    def test_the_health_example_is_the_generic_one(self):
        """Ruling §0.4 amendment 1 (DW-9)."""
        from agent.prompt_templates.interpretation.rendering import (
            HEALTH_FEEDBACK_SYSTEM_INSTRUCTIONS,
        )

        assert "sample_dispersion_floor_blocking:dispersion=0.0" in (
            HEALTH_FEEDBACK_SYSTEM_INSTRUCTIONS
        )
        assert "output_diversity_blocking" not in HEALTH_FEEDBACK_SYSTEM_INSTRUCTIONS
        assert "n_unique_int8_values" not in HEALTH_FEEDBACK_SYSTEM_INSTRUCTIONS


# ---------------------------------------------------------------------------
# Splice / omission contract
# ---------------------------------------------------------------------------


class TestSpliceAndOmission:
    def test_blockless_prompts_match_their_goldens(self):
        assert_golden(
            PM_BARE,
            GOLDENS / "per_model_system_prompt_blockless.txt",
            surface="09b C2 block-less per-model system prompt",
        )
        assert_golden(
            SY_BARE,
            GOLDENS / "synthesis_system_prompt_blockless.txt",
            surface="09b C2 block-less synthesis system prompt",
        )

    def test_absent_blocks_render_no_header_and_no_bytes(self):
        for bare in (PM_BARE, SY_BARE):
            assert "### Task" not in bare
            assert "{TASK_GUIDANCE_SECTIONS}" not in bare

    def test_no_placeholder_leaks_when_blocks_are_present(self):
        assert "{TASK_GUIDANCE_SECTIONS}" not in PM_ASSEMBLED
        assert "{TASK_GUIDANCE_SECTIONS}" not in SY_ASSEMBLED

    def test_sections_render_only_in_their_frozen_phases(self):
        blocks = InterpretationTaskBlocks(
            evidence_reading="EVIDENCE-PROSE",
            per_model_guidance="PER-MODEL-PROSE",
            synthesis_guidance="SYNTHESIS-PROSE",
            prediction_guidance="PREDICTION-PROSE",
        )
        pm = _build_per_model_system_prompt(_inp(blocks))
        sy = _build_synthesis_system_prompt(_inp(blocks))
        assert "EVIDENCE-PROSE" in pm and "EVIDENCE-PROSE" in sy
        assert "PER-MODEL-PROSE" in pm and "PER-MODEL-PROSE" not in sy
        assert "SYNTHESIS-PROSE" in sy and "SYNTHESIS-PROSE" not in pm
        assert "PREDICTION-PROSE" in sy and "PREDICTION-PROSE" not in pm
        assert "### Task prediction guidance" in sy

    def test_a_partial_value_renders_only_its_headers(self):
        blocks = InterpretationTaskBlocks(evidence_reading="ER-ONLY")
        pm = _build_per_model_system_prompt(_inp(blocks))
        assert "### Task evidence guidance" in pm
        assert "### Task analysis guidance (per-model)" not in pm

    def test_tidmad_supplies_no_prediction_guidance(self):
        """Frozen §5.3: absence is deliberate — nothing existed to migrate."""
        assert TIDMAD_BLOCKS.prediction_guidance is None
        assert "### Task prediction guidance" not in SY_ASSEMBLED

    def test_flag_on_is_still_flag_off_plus_the_constant(self):
        from agent.prompt_templates.interpretation.rendering import (
            HEALTH_FEEDBACK_SYSTEM_INSTRUCTIONS,
        )

        flag_on = _build_per_model_system_prompt(
            InterpretationInput(
                model_types=["wavenet"],
                task_description=_TASK_DESCRIPTION,
                task_blocks=TIDMAD_BLOCKS,
                enable_structured_health_feedback=True,
            )
        )
        assert flag_on == PM_ASSEMBLED + HEALTH_FEEDBACK_SYSTEM_INSTRUCTIONS


# ---------------------------------------------------------------------------
# Value contract + adapter (fail closed)
# ---------------------------------------------------------------------------


class TestValueContract:
    def test_the_key_set_is_exactly_the_four_framework_sections(self):
        """Census 4 — key-set growth is a framework decision."""
        assert list(InterpretationTaskBlocks.model_fields) == [
            "evidence_reading",
            "per_model_guidance",
            "synthesis_guidance",
            "prediction_guidance",
        ]

    def test_an_unknown_key_fails_closed(self):
        with pytest.raises(Exception, match=r"extra_forbidden|Extra inputs"):
            InterpretationTaskBlocks.model_validate({"evidence_reading": "x", "typo_key": "y"})

    def test_an_empty_present_section_is_refused(self):
        with pytest.raises(Exception, match="present but empty"):
            InterpretationTaskBlocks(evidence_reading="   \n")

    def test_the_value_round_trips(self):
        assert InterpretationTaskBlocks.model_validate(TIDMAD_BLOCKS.model_dump()) == TIDMAD_BLOCKS


class TestAdapter:
    def test_the_default_path_loads_tidmads_declaration(self):
        blocks = load_interpretation_task_blocks()
        assert blocks.evidence_reading is not None
        assert blocks.per_model_guidance is not None
        assert blocks.synthesis_guidance is not None
        assert blocks.prediction_guidance is None

    def test_a_missing_file_fails_closed(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="not found"):
            load_interpretation_task_blocks(str(tmp_path / "nope.yaml"))

    def test_a_non_mapping_file_fails_closed(self, tmp_path):
        p = tmp_path / "bad.yaml"
        p.write_text("- just\n- a\n- list\n")
        with pytest.raises(ValueError, match="YAML mapping"):
            load_interpretation_task_blocks(str(p))

    def test_an_unknown_section_fails_closed(self, tmp_path):
        p = tmp_path / "typo.yaml"
        p.write_text("evidnce_reading: 'typo section'\n")
        with pytest.raises(ValueError, match="failed the"):
            load_interpretation_task_blocks(str(p))

    def test_an_empty_section_fails_closed(self, tmp_path):
        p = tmp_path / "empty.yaml"
        p.write_text("evidence_reading: '   '\n")
        with pytest.raises(ValueError, match="present but empty"):
            load_interpretation_task_blocks(str(p))

    def test_an_explicit_external_path_works_with_no_siderius_edit(self, tmp_path):
        """The extension story: any task, any path, same typed value."""
        p = tmp_path / "fourth_task.yaml"
        p.write_text("evidence_reading: 'Read the frobnication ledger first.'\n")
        blocks = load_interpretation_task_blocks(str(p))
        assert blocks.evidence_reading == "Read the frobnication ledger first."
        assert blocks.synthesis_guidance is None


# ---------------------------------------------------------------------------
# Structural censuses (design §16 items 1-source / 3 / 3b / 6)
# ---------------------------------------------------------------------------

_TASK_TOKEN = re.compile(r"tidmad|pets|davis", re.IGNORECASE)

#: The GENERIC interpreter surfaces (census 3): zero task-name tokens in
#: executable (non-docstring) string literals. The adapter module is the ONE
#: named exemption, censused separately (3b).
GENERIC_SURFACES = [
    "nodes/result_interpretation_agent/result_interpretation_agent.py",
    "nodes/result_interpretation_agent/evidence.py",
    "nodes/result_interpretation_agent/ordering.py",
    "nodes/result_interpretation_agent/prediction.py",
    "nodes/interpretation_helpers.py",
    "agent/prompt_templates/interpretation/rendering.py",
    "agent/schemas/interpretation.py",
]


def _non_docstring_string_literals(source: str) -> list[str]:
    """Every string constant that is NOT a docstring."""
    tree = ast.parse(source)
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                docstrings.add(id(body[0].value))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


class TestCensus3GenericSurfacesCarryNoTaskIdentity:
    @pytest.mark.parametrize("rel", GENERIC_SURFACES)
    def test_no_task_token_in_executable_string_literals(self, rel):
        source = (REPO_ROOT / rel).read_text(encoding="utf-8")
        offenders = [
            lit[:80] for lit in _non_docstring_string_literals(source) if _TASK_TOKEN.search(lit)
        ]
        assert not offenders, f"{rel} carries task-identity string literals: {offenders}"

    def test_anti_vacuity_the_scanner_sees_the_prompt_constants(self):
        """The scan must actually visit the big template literals."""
        source = (REPO_ROOT / "agent/prompt_templates/interpretation/rendering.py").read_text(
            encoding="utf-8"
        )
        literals = _non_docstring_string_literals(source)
        assert any("senior ML research analyst" in lit for lit in literals)


class TestCensus3bTheAdapterConstantIsNotABranch:
    ADAPTER = "agent/prompt_templates/interpretation/task_blocks.py"

    def _tree_and_source(self):
        source = (REPO_ROOT / self.ADAPTER).read_text(encoding="utf-8")
        return ast.parse(source), source

    def test_exactly_one_task_token_literal_the_default_path_constant(self):
        _, source = self._tree_and_source()
        # Docstrings legitimately NAME the task while stating the bounded-
        # adapter doctrine; the census counts EXECUTABLE literals only —
        # exactly like census 3's scanner.
        hits: list[tuple[str, int]] = []
        tree = ast.parse(source)
        docstring_ids = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        }
        for node in ast.walk(tree):
            if id(node) in docstring_ids:
                continue
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and _TASK_TOKEN.search(node.value)
            ):
                hits.append((node.value, node.lineno))
        assert len(hits) == 1, f"expected exactly ONE task-token literal, got {hits}"
        (value, lineno) = hits[0]
        assert value == "tidmad.yaml"
        # ... and that literal sits inside the ONE module-level assignment to
        # the self-labelled constant.
        assign_names = [
            t.id
            for stmt in tree.body
            if isinstance(stmt, ast.AnnAssign | ast.Assign)
            for t in (stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target])
            if isinstance(t, ast.Name) and stmt.lineno <= lineno <= (stmt.end_lineno or stmt.lineno)
        ]
        assert assign_names == ["LEGACY_DEFAULT_TASK_INTERPRETATION_CONFIG"]

    def test_no_conditional_or_mapping_touches_a_task_token(self):
        """A second task constant, a task table, or an `if 'tidmad' in …`
        branch turns this RED (ruling §0.4 amendment 2)."""
        tree, _ = self._tree_and_source()
        for node in ast.walk(tree):
            if isinstance(node, ast.If | ast.IfExp | ast.Match | ast.Compare | ast.Dict):
                segment = ast.unparse(node)
                assert not _TASK_TOKEN.search(segment), (
                    f"task identity participates in control flow / mapping: {segment[:120]}"
                )

    def test_docstrings_state_the_bounded_adapter_doctrine(self):
        _, source = self._tree_and_source()
        assert "not a branch" in source


class TestCensus6OneProductionModuleKnowsTheDeclarationPath:
    def test_the_path_string_lives_in_exactly_one_production_module(self):
        production_dirs = [
            "nodes",
            "agent",
            "core",
            "execute_tools",
            "workflows",
            "scripts",
            "dashboard",
        ]
        carriers: list[str] = []
        for d in production_dirs:
            root = REPO_ROOT / d
            if not root.exists():
                continue
            for py in root.rglob("*.py"):
                if "task_interpretation" in py.read_text(encoding="utf-8", errors="ignore"):
                    carriers.append(str(py.relative_to(REPO_ROOT)))
        assert carriers == ["agent/prompt_templates/interpretation/task_blocks.py"], (
            f"the declaration path must be known to the ONE bounded adapter only; found: {carriers}"
        )


class TestCensus1SourceHalf:
    """`rendering.py` source carries no science token outside the §5.4-exempt
    schema-derived label (F-09b-3)."""

    _SCIENCE = re.compile(
        r"Log-of-Mean|Impact_Score|Linear_Weight|PSD|segmentation_size"
        r"|output_diversity_blocking|n_unique_int8_values"
    )
    #: The §5.4/F-09b-3 exemption: the SCHEMA-DERIVED record-vocabulary labels
    #: (`training_psd_segments` / `eval_psd_segments` rendered as their
    #: presence-gated evidence labels). Exactly these, nothing else.
    _EXEMPT_LABELS = ("Training PSD segments: ", "Eval PSD segments    : ")

    def test_rendering_source_is_science_free_except_the_exempt_labels(self):
        source = (REPO_ROOT / "agent/prompt_templates/interpretation/rendering.py").read_text(
            encoding="utf-8"
        )
        literals = _non_docstring_string_literals(source)
        offenders = [
            lit[:80]
            for lit in literals
            if self._SCIENCE.search(lit) and not any(label in lit for label in self._EXEMPT_LABELS)
        ]
        assert not offenders, f"science tokens in rendering source literals: {offenders}"
        # Anti-vacuity: the exemption names REAL lines — the presence-gated
        # schema-derived labels must still exist, at exactly the known sites
        # (Training ×2: per-model + synthesis builders; Eval ×1).
        exempt = [lit for lit in literals if any(label in lit for label in self._EXEMPT_LABELS)]
        assert len(exempt) == 3, exempt

    def test_the_assembled_tidmad_prompts_do_carry_the_science(self):
        """The positive half that replaced `test_impact_aware_framing_present`."""
        for token in ("Log-of-Mean", "Impact_Score", "Linear_Weight"):
            assert token in PM_ASSEMBLED, f"{token} missing from assembled per-model prompt"
            assert token in SY_ASSEMBLED, f"{token} missing from assembled synthesis prompt"
        assert "(baseline typically uses 4000)" in _norm(PM_ASSEMBLED)


class TestDeclarationFileShape:
    def test_the_declaration_is_a_yaml_mapping_with_only_framework_keys(self):
        raw = yaml.safe_load(
            (REPO_ROOT / LEGACY_DEFAULT_TASK_INTERPRETATION_CONFIG).read_text(encoding="utf-8")
        )
        assert isinstance(raw, dict)
        assert set(raw) <= set(InterpretationTaskBlocks.model_fields)
