"""Step 12 / PR-12a — C7-4: ImplementorTaskBlocks.

Design:
``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12a_composed_path_closure.md`` §5 C7, §8.14 (F-12a-C7-13) and the
operator-ratified contract correction recorded there.

C7-4 was STOPPED as a material deviation and then AUTHORIZED, because closing
it needs a schema the child's ratification did not enumerate. What the source
audit had already established, and what shaped the narrow contract:

* **I2 was already closed** for any run with a ModelIOContract — Step 04a
  renders both generated-code comments from the declaration. Only the
  regressor half was hardcoded (`"continuous waveform regression"`), because
  the classifier half derives from the declared class cardinality.
* **I1** (two role clauses) had no task-owned source at this node: the task
  description would have moved LEGACY bytes, the ModelIOContract carries no
  free-text phrase, and gating on composition presence would have introduced
  the ambient discriminator D-12a-1 removed.

So the task owns two values and the framework owns everything around them.

The eight validations the ruling requires are each a class below.
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from typing import ClassVar

import pytest

from agent.prompt_templates.implementor.task_blocks import (
    LEGACY_DEFAULT_TASK_IMPLEMENTOR_CONFIG,
    load_implementor_task_blocks,
)
from agent.schemas.implementor import ImplementorTaskBlocks
from execute_tools.health_checks import _plugin_binding
from execute_tools.health_checks.registry import _PROVIDER_REGISTRY, _REGISTRY
from nodes.ml_model_implementor.ml_model_implementor import (
    IMPLEMENTOR_LOSS_REASONING_PROMPT,
    IMPLEMENTOR_REASONING_PROMPT,
    render_continuous_output_phrase,
    render_engineer_role,
)
from tests.helpers.composed_manifest import write_complete_manifest
from workflows.model_exploration import resolve_run_implementor_blocks
from workflows.task_composition import TaskCompositionError, compose_run_task_bindings

REPO_ROOT = Path(__file__).resolve().parents[3]
IMPLEMENTOR = REPO_ROOT / "nodes" / "ml_model_implementor" / "ml_model_implementor.py"
ADAPTER = REPO_ROOT / "agent" / "prompt_templates" / "implementor" / "task_blocks.py"


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


class _Emitted:
    """Minimal stand-in for a declared output tensor."""

    @staticmethod
    def render_shape() -> str:
        return "[B, T] float32"


# (1) legacy rendered-prompt byte parity against the pre-C7 recorded digest
class TestLegacyRenderedPromptByteParity:
    """The ruling's validation 1, in its strictest available form.

    Not "the prompt looks the same" — the pre-C7 sha256, recorded in the C0
    fixture at `eeb073dc`, HARDCODED here so this compares against the
    recorded past rather than against itself.
    """

    PRE_C7_SHA: ClassVar[dict[str, str]] = {
        "IMPLEMENTOR_REASONING_PROMPT": (
            "5f32ce79e121318360a6cf72d907d87bd3cfb2598e0a6a6536c4d4d1696c020b"
        ),
    }

    def test_substituting_tidmads_blocks_reproduces_the_original_bytes(self):
        blocks = load_implementor_task_blocks()
        rendered = IMPLEMENTOR_REASONING_PROMPT.replace(
            "{ENGINEER_ROLE}", render_engineer_role(blocks)
        )
        assert (
            hashlib.sha256(rendered.encode("utf-8")).hexdigest()
            == self.PRE_C7_SHA["IMPLEMENTOR_REASONING_PROMPT"]
        )

    def test_both_role_lines_read_exactly_as_before(self):
        blocks = load_implementor_task_blocks()
        model_line = IMPLEMENTOR_REASONING_PROMPT.replace(
            "{ENGINEER_ROLE}", render_engineer_role(blocks)
        ).splitlines()[0]
        loss_line = IMPLEMENTOR_LOSS_REASONING_PROMPT.replace(
            "{LOSS_ENGINEER_ROLE}", render_engineer_role(blocks, for_losses=True)
        ).splitlines()[0]

        assert model_line == (
            "You are a senior PyTorch engineer specialising in deep learning for signal denoising."
        )
        assert loss_line == (
            "You are a senior PyTorch engineer specialising in loss functions for signal denoising."
        )

    def test_the_prose_no_longer_lives_in_the_node(self):
        source = IMPLEMENTOR.read_text(encoding="utf-8")
        assert "specialising in deep learning for signal denoising" not in source
        assert "specialising in loss functions for signal denoising" not in source
        assert "{ENGINEER_ROLE}" in source
        assert "{LOSS_ENGINEER_ROLE}" in source


# (2) composed task WITH declared blocks -> the science comes from them
class TestComposedWithDeclaredBlocks:
    def test_the_role_clauses_come_from_the_declaration(self, tmp_path):
        declaration = tmp_path / "mine.yaml"
        declaration.write_text("science_domain: variable-length tabular grouping\n", "utf-8")
        composition = compose_run_task_bindings(
            str(write_complete_manifest(tmp_path, implementor_blocks={"config": str(declaration)}))
        )
        blocks = composition.implementor_blocks
        assert blocks is not None

        assert render_engineer_role(blocks) == (
            " specialising in deep learning for variable-length tabular grouping"
        )
        assert render_engineer_role(blocks, for_losses=True) == (
            " specialising in loss functions for variable-length tabular grouping"
        )
        assert "denoising" not in render_engineer_role(blocks)

    def test_the_continuous_phrase_comes_from_the_declaration(self, tmp_path):
        declaration = tmp_path / "mine.yaml"
        declaration.write_text("continuous_output_phrase: per-group scalar regression\n", "utf-8")
        composition = compose_run_task_bindings(
            str(write_complete_manifest(tmp_path, implementor_blocks={"config": str(declaration)}))
        )
        assert (
            render_continuous_output_phrase(composition.implementor_blocks, _Emitted())
            == "per-group scalar regression"
        )


# (3) composed task WITHOUT blocks -> zero fallback to TIDMAD science
class TestComposedWithoutBlocksNeverFallsBackToTidmad:
    """The ruling's frozen semantic, and the whole reason this family exists."""

    @pytest.mark.parametrize("blocks", [None, ImplementorTaskBlocks()])
    def test_the_role_clause_disappears_rather_than_becoming_TIDMADs(self, blocks):
        assert render_engineer_role(blocks) == ""
        assert render_engineer_role(blocks, for_losses=True) == ""
        rendered = IMPLEMENTOR_REASONING_PROMPT.replace(
            "{ENGINEER_ROLE}", render_engineer_role(blocks)
        )
        assert "You are a senior PyTorch engineer." in rendered
        assert "denoising" not in rendered.splitlines()[0]

    @pytest.mark.parametrize("blocks", [None, ImplementorTaskBlocks()])
    def test_the_continuous_phrase_names_the_DECLARED_form_not_a_waveform(self, blocks):
        """No invented science and no TIDMAD: it names what the contract
        already says the output is, which is how the classifier half has
        always worked (it derives from the declared class cardinality)."""
        phrase = render_continuous_output_phrase(blocks, _Emitted())
        assert "waveform" not in phrase
        assert "[B, T] float32" in phrase

    def test_a_real_composed_task_that_declares_none_gets_none(self):
        composition = compose_run_task_bindings(
            str(REPO_ROOT / "tests" / "fixtures" / "step10_p1" / "davis" / "composition.yaml")
        )
        resolved = resolve_run_implementor_blocks(composition)
        assert resolved is None
        assert render_engineer_role(resolved) == ""


# (4) changing ONLY implementor_blocks -> the fingerprint changes
class TestFingerprintParticipation:
    #: Measured AT `eeb073dc`, before either section existed (§8.15).
    #:
    #: MOVED at Step 12 / PR-12d D4c, with the reason this file's own
    #: convention requires. The Pets/DAVIS fixtures' secondary metrics were
    #: bound to implementations that computed something else entirely —
    #: `psnr` and `mae` both to `GlobalMseMetric`, `macro_f1` to
    #: `AccuracyMetric` (F-12d-3). Rebinding them to the packs' OWN
    #: implementations changes `implementation:` from a `module:` ref to a
    #: `file:` ref, and a `file:` ref contributes its CONTENT DIGEST to the
    #: fingerprint. So the value moves because the composition genuinely
    #: changed, not because the fingerprint rule did.
    #:
    #: TIDMAD's shipped fingerprint is UNTOUCHED and still `9125bf58…` — no
    #: TIDMAD binding was mis-bound, so none was rebound.
    #:
    #: MOVED AGAIN at Step 12 / PR-12d, once per pack and each for its own
    #: reason — D6 for DAVIS, D5 for Pets. Both fixtures stopped carrying the
    #: fabricated TIDMAD-shaped `dataset_profile` F-12d-4 condemned
    #: (`psd_segment_length`, `segments_per_file`, `.h5` shard patterns for
    #: tasks that have clips and images): DAVIS' was re-authored into the
    #: Q-12-4 shape, and Pets' was DELETED so the fixture resolves the pack's
    #: SHIPPED `declared/dataset_profile.json` — exactly one Pets profile now
    #: exists. The profile's wire form enters the semantic fingerprint, so
    #: both values move because the DECLARATIONS genuinely changed; the
    #: fingerprint rule did not.
    #:
    #: TIDMAD's shipped fingerprint remains `9125bf58…` and is asserted
    #: separately — no TIDMAD declaration was touched by either commit.
    #: MOVED a THIRD time, and NOT because this fixture's own YAML changed —
    #: it did not. Both fixtures bind their SECONDARY metric through a `file:`
    #: ref into `_pets_metrics.py` / `_davis_metrics.py`, and a `file:` ref's
    #: CONTENT DIGEST enters the fingerprint. F-12d-19 added
    #: `PetsAccuracyMetric` / `DavisMseMetric` to those same files (to give the
    #: SHIPPED manifest's primary a binding that accepts the composed call),
    #: which moved the digest — and with it, every fixture referencing the
    #: file, whether or not the fixture's own content moved.
    #:
    #: The generalisable point: a `file:` ref's identity is the FILE's content,
    #: not the symbol composed. Two manifests binding different symbols out of
    #: the same file share one identity, and editing the file for one manifest
    #: silently reopens every other manifest's pinned fingerprint.
    PRE_SECTION_FINGERPRINT: ClassVar[dict[str, str]] = {
        "davis": "48b5e53e389f349396b83446e398a9ad02b6b3c36146e83ab4e5e668584d3b94",
        "pets": "600d7c2eea82fb03e56c41640d9837336259918293861eacdcc0c7d78a95bdfb",
    }

    @pytest.mark.parametrize("task", ["davis", "pets"])
    def test_an_undeclared_manifest_fingerprints_UNCHANGED(self, task):
        composition = compose_run_task_bindings(
            str(REPO_ROOT / "tests" / "fixtures" / "step10_p1" / task / "composition.yaml")
        )
        assert composition.implementor_blocks is None
        assert composition.semantic_fingerprint == self.PRE_SECTION_FINGERPRINT[task]

    def test_changing_ONLY_the_blocks_moves_the_fingerprint(self, tmp_path):
        first = tmp_path / "a.yaml"
        first.write_text("science_domain: one\n", encoding="utf-8")
        second = tmp_path / "b.yaml"
        second.write_text("science_domain: two\n", encoding="utf-8")

        a = compose_run_task_bindings(
            str(write_complete_manifest(tmp_path / "wa", implementor_blocks={"config": str(first)}))
        )
        b = compose_run_task_bindings(
            str(
                write_complete_manifest(tmp_path / "wb", implementor_blocks={"config": str(second)})
            )
        )
        assert a.semantic_fingerprint != b.semantic_fingerprint


# (5) malformed / unknown declaration -> fail closed
class TestFailClosed:
    def test_a_declared_but_missing_file_refuses(self, tmp_path):
        manifest = write_complete_manifest(
            tmp_path, implementor_blocks={"config": str(tmp_path / "absent.yaml")}
        )
        with pytest.raises(TaskCompositionError, match="implementor_blocks declaration"):
            compose_run_task_bindings(str(manifest))

    def test_a_non_mapping_section_refuses(self, tmp_path):
        manifest = write_complete_manifest(tmp_path, implementor_blocks="nope")
        with pytest.raises(TaskCompositionError, match="must be a mapping"):
            compose_run_task_bindings(str(manifest))

    def test_an_unknown_key_refuses(self, tmp_path):
        bad = tmp_path / "typo.yaml"
        bad.write_text("sceince_domain: oops\n", encoding="utf-8")
        with pytest.raises(ValueError, match="failed the ImplementorTaskBlocks contract"):
            load_implementor_task_blocks(str(bad))

    def test_a_non_mapping_file_refuses(self, tmp_path):
        bad = tmp_path / "list.yaml"
        bad.write_text("- a\n", encoding="utf-8")
        with pytest.raises(ValueError, match="must be a YAML mapping"):
            load_implementor_task_blocks(str(bad))

    def test_an_explicit_none_is_a_legal_named_absence(self, tmp_path):
        manifest = write_complete_manifest(tmp_path, implementor_blocks={"none": True})
        assert compose_run_task_bindings(str(manifest)).implementor_blocks is None


# (6) mutation: restoring the unconditional TIDMAD phrase turns ownership RED
class TestOwnershipCensus:
    """The ruling's validation 6, as a PERMANENT test rather than a one-off
    plant: re-introducing the unconditional phrase anywhere in the node turns
    this RED."""

    def test_no_role_science_literal_survives_in_the_node(self):
        source = IMPLEMENTOR.read_text(encoding="utf-8")
        for banned in (
            "specialising in deep learning for signal denoising",
            "specialising in loss functions for signal denoising",
        ):
            assert banned not in source, (
                f"{banned!r} is back in the implementor — a composed run would "
                f"receive TIDMAD's science again"
            )

    def test_the_one_surviving_phrase_is_PINNED_to_the_legacy_table(self):
        """F-12a-C7-14. The regressor entry of
        ``_LEGACY_OUTPUT_CONTRACT_COMMENTS`` still carries TIDMAD's phrase,
        because that table exists to hold the pre-Step-04a bytes for a task
        declaring no ``model_io``. Pinning the COUNT is what keeps it from
        spreading: a second occurrence — e.g. someone restoring the
        unconditional phrase in the renderer — turns this RED."""
        source = IMPLEMENTOR.read_text(encoding="utf-8")
        occurrences = source.count("continuous waveform regression")
        assert occurrences == 1, (
            f"expected exactly the pinned legacy-table occurrence, found "
            f"{occurrences} — see F-12a-C7-14"
        )
        table = source.split("_LEGACY_OUTPUT_CONTRACT_COMMENTS: dict", 1)[1].split("\n}", 1)[0]
        assert "continuous waveform regression" in table

    def test_the_dead_unconditional_phrase_constant_is_gone(self):
        """R-11-10: replace or delete, never twin. ``_CONTINUOUS_OUTPUT_PHRASE``
        was the renderer's unconditional source and has no remaining reader."""
        assert "_CONTINUOUS_OUTPUT_PHRASE" not in IMPLEMENTOR.read_text(encoding="utf-8")

    def test_the_declaration_still_carries_them(self):
        """The other half: the census above would also pass if the prose were
        simply deleted, which would silently drop required science."""
        blocks = load_implementor_task_blocks()
        assert blocks.science_domain == "signal denoising"
        assert blocks.continuous_output_phrase == "continuous waveform regression"


# (7) no new task-identity dispatch / central catalog row
class TestNoTaskDispatchWasIntroduced:
    def test_the_adapter_is_a_constant_not_a_branch(self):
        tree = ast.parse(ADAPTER.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.If | ast.IfExp | ast.Match):
                rendered = ast.dump(node.test if not isinstance(node, ast.Match) else node.subject)
                for forbidden in ("tidmad", "pets", "davis"):
                    assert forbidden not in rendered.lower()
        assert LEGACY_DEFAULT_TASK_IMPLEMENTOR_CONFIG.endswith("tidmad.yaml")

    def test_the_renderers_never_name_a_task(self):
        import inspect
        import textwrap

        for fn in (render_engineer_role, render_continuous_output_phrase):
            body = ast.parse(textwrap.dedent(inspect.getsource(fn)))
            function = next(n for n in ast.walk(body) if isinstance(n, ast.FunctionDef))
            statements = function.body[1:] if ast.get_docstring(function) else function.body
            executable = "\n".join(ast.unparse(n) for n in statements).lower()
            for forbidden in ("tidmad", "denoising", "waveform", "pets", "davis"):
                assert forbidden not in executable, (fn.__name__, forbidden)


# (8) structural: the decision is a render boundary, not a new branch family
class TestStructuralOwnership:
    def test_the_workflow_calls_a_named_resolver(self):
        import inspect

        from workflows import model_exploration

        source = inspect.getsource(model_exploration.run_workflow)
        assert "resolve_run_implementor_blocks(" in source

    def test_the_resolver_truth_table(self):
        assert resolve_run_implementor_blocks(None) is not None  # bounded adapter
        composition = compose_run_task_bindings(
            str(REPO_ROOT / "tests" / "fixtures" / "step10_p1" / "davis" / "composition.yaml")
        )
        assert resolve_run_implementor_blocks(composition) is None  # declares none
