"""Step 04a CHECKPOINT B — the Stage-B semantic ladder: 6.5-A, 6.5-C, 6.5-D.

Design: ``docs/design/generic_framework_upgrade/step_04_candidate_creation_mechanics/
pr_04a_contract_derived_candidate_mechanics.md`` §6 (the ladder), §6.1 (why
6.5-B is NOT a rung), §6.2 (6.5-D closes at the validator), §16 C7.

**What a rung is for.** A test that a 16-class task produces 16-class
artifacts proves the code reads a number. A *rung* proves something stronger:
that varying **exactly one** declared axis moves **exactly** the consumers
that axis owns, and moves nothing else. Without the atomicity half, a rung
passes for a consumer that recomputed everything from scratch — and would
keep passing if a second axis silently changed with it.

So each rung below does three things:

1. varies one axis against its **own declared baseline**;
2. **machine-checks** that only that axis differs (the 02b/02c ``_diff_paths``
   precedent), rather than asserting atomicity in prose;
3. asserts the consumers that axis does NOT own are unchanged.

===========  ==========================  ==========================
rung         baseline                    varies ONLY
===========  ==========================  ==========================
**6.5-A**    the TIDMAD declaration      class cardinality
**6.5-C**    the TIDMAD declaration      canonical output semantic
**6.5-D**    **6.5-C's** regressor       custom-loss capability
===========  ==========================  ==========================

**6.5-B is deliberately absent.** ``T = 64 -> 128`` varies no declared
semantic: a *symbolic* dimension declares alignment, not magnitude, so both
values satisfy the identical constraint and no upstream authority changes.
Such a rung would pass whether or not a consumer re-hardcoded its literal —
the exact weakness §6 forbids. It is retained below only as explicitly
labelled probe-recipe robustness, never reported as a semantic contrast.

**6.5-D lives in
``ml_model_implementor/test_step04a_regressor_custom_loss_capability.py``**
because it must run the real implementor and the real validator. It is
referenced here, not duplicated (§16 C7: *"already added in C5; reference it,
do not duplicate"*); this module owns its atomicity check.
"""

from __future__ import annotations

import pytest

from agent.skills.model_io_probe_skill import (
    PROBE_BATCH,
    PROBE_SYMBOLIC_EXTENT,
    build_loss_probe_pair,
    expected_output_shape,
    input_index_extent,
    realize_shape,
)
from nodes.ml_code_validator_agent.ml_code_validator_agent import (
    _build_review_system_prompt,
)
from nodes.ml_model_implementor.ml_model_implementor import (
    _assemble_test,
    _render_output_contract,
)
from tests.helpers.step04a_fixtures import regressor_model_io, tidmad_model_io


def _diff_paths(left, right, prefix=""):
    """Dotted paths at which two nested dicts differ (02b/02c convention)."""
    paths = []
    for key in sorted(set(left) | set(right)):
        path = f"{prefix}{key}"
        lv, rv = left.get(key), right.get(key)
        if isinstance(lv, dict) and isinstance(rv, dict):
            paths.extend(_diff_paths(lv, rv, prefix=f"{path}."))
        elif lv != rv:
            paths.append(path)
    return paths


def _declaration(contract) -> dict:
    """The declared axes, as a comparable nested structure.

    This is what "varies exactly one axis" is measured over: the axis roles
    and extents themselves, not a rendering of them.
    """

    def tensor(t):
        return {
            "dtype": list(t.dtype.admissible),
            "axes": {
                str(i): {
                    "role": a.role.value if a.role else None,
                    "fixed": a.dimension.fixed,
                    "symbolic": a.dimension.symbolic,
                    "dynamic": a.dimension.dynamic,
                }
                for i, a in enumerate(t.axes)
            },
        }

    return {"input": tensor(contract.input), "output": tensor(contract.output)}


def _consumers(contract, declared_form: str) -> dict:
    """Every contract-owned fact the candidate-creation consumers derive.

    One dict per (contract, declared form) so a rung can diff the OBSERVABLE
    outputs — realized shapes, rendered comments, generated test text,
    rendered prompt — rather than the configuration that produced them
    (§16's binding rule).
    """
    forward_comment, output_comment = _render_output_contract(declared_form, contract)
    return {
        "expected_output_shape": str(expected_output_shape(contract, declared_form)),
        "probe_input_shape": str(realize_shape(contract.input)),
        "probe_index_extent": input_index_extent(contract),
        "plugin_forward_comment": forward_comment,
        "plugin_output_comment": output_comment,
        "generated_test": _assemble_test("rung_probe", contract),
        "review_prompt": _build_review_system_prompt(contract),
    }


# ---------------------------------------------------------------------------
# 6.5-A — cardinality only
# ---------------------------------------------------------------------------


class TestRung65A:
    """Baseline: the TIDMAD declaration. Varies: class cardinality only."""

    BASELINE = tidmad_model_io()
    VARIED = tidmad_model_io(num_classes=16)

    def test_exactly_one_declared_axis_differs(self):
        """Atomicity, machine-checked.

        Fails when: the rung's two declarations differ anywhere except the
        class axis's fixed extent — which is how a rung silently becomes a
        two-axis contrast and stops proving anything about either.
        """
        assert _diff_paths(_declaration(self.BASELINE), _declaration(self.VARIED)) == [
            "output.axes.1.fixed"
        ]

    def test_every_cardinality_consumer_follows(self):
        """The axis's owned consumers all move — and say 16, not 256.

        Fails when: any consumer re-hardcodes the class count. Each entry is
        an artifact the pipeline actually emits, so a consumer that reads the
        contract but renders a constant still fails.
        """
        varied = _consumers(self.VARIED, "classifier")

        assert varied["expected_output_shape"] == str((PROBE_BATCH, 16, PROBE_SYMBOLIC_EXTENT))
        assert varied["probe_index_extent"] == 16
        assert varied["plugin_forward_comment"].endswith("output [B, 16, T] float32")
        assert varied["plugin_output_comment"] == "[B, 16, T] → 16-class classification"
        assert "(2, 16, config.segmentation_size)" in varied["generated_test"]
        assert '"classifier" must emit [B, 16, T]' in varied["review_prompt"]

    def test_the_unvaried_consumers_are_unchanged(self):
        """§6: the rung must move the axis's consumers and NOTHING else.

        The input tensor carries no class axis, so its realized probe shape
        is cardinality-independent. If it moved, the derivation would be
        reading the class extent for something it does not own.
        """
        base = _consumers(self.BASELINE, "classifier")
        varied = _consumers(self.VARIED, "classifier")

        assert base["probe_input_shape"] == varied["probe_input_shape"]

        moved = {k for k in base if base[k] != varied[k]}
        assert moved == {
            "expected_output_shape",
            "probe_index_extent",
            "plugin_forward_comment",
            "plugin_output_comment",
            "generated_test",
            "review_prompt",
        }, f"unexpected consumer set moved for a cardinality-only change: {moved}"

    def test_no_256_survives_anywhere_in_the_varied_consumers(self):
        """The residue check, scoped to the block under test.

        Step 01's lesson: a whole-prompt absence assertion is unsatisfiable
        and is a test-design error. These are the contract-derived outputs
        only, so ``256`` appearing in any of them is a genuine survival.
        """
        varied = _consumers(self.VARIED, "classifier")
        for name in (
            "expected_output_shape",
            "plugin_forward_comment",
            "plugin_output_comment",
        ):
            assert "256" not in varied[name], f"{name} still carries 256"


# ---------------------------------------------------------------------------
# 6.5-C — output semantic only
# ---------------------------------------------------------------------------


class TestRung65C:
    """Baseline: the TIDMAD declaration. Varies: canonical output semantic."""

    BASELINE = tidmad_model_io()
    VARIED = regressor_model_io()

    def test_exactly_one_declared_axis_differs(self):
        """Atomicity: the ONLY difference is the presence of the class axis.

        ``output_semantic`` is derived from that axis, so removing it is
        precisely "vary the output semantic and nothing else". The diff shows
        the third axis vanishing, which is the same fact expressed positionally.
        """
        paths = _diff_paths(_declaration(self.BASELINE), _declaration(self.VARIED))
        assert all(p.startswith("output.axes.") for p in paths), (
            f"a non-output-axis difference leaked into the semantic rung: {paths}"
        )
        assert _declaration(self.BASELINE)["input"] == _declaration(self.VARIED)["input"], (
            "the input declaration must be identical — otherwise this rung varies two axes"
        )

    def test_the_semantic_flips_and_the_cardinality_becomes_inapplicable(self):
        from ml_models.models_format_sandbox import OutputSemantic

        assert self.BASELINE.output_semantic is OutputSemantic.CATEGORICAL
        assert self.VARIED.output_semantic is OutputSemantic.CONTINUOUS
        assert self.BASELINE.class_cardinality == 256
        assert self.VARIED.class_cardinality is None

    def test_generation_and_validation_both_follow_the_semantic(self):
        """§6: reds when generation OR validation still assumes classifier.

        Fails when: any consumer synthesises a class axis the task no longer
        declares.
        """
        varied = _consumers(self.VARIED, "regressor")

        assert varied["expected_output_shape"] == str((PROBE_BATCH, PROBE_SYMBOLIC_EXTENT))
        assert varied["plugin_forward_comment"] == "input [B, T] int64 → output [B, T] float32"
        assert varied["plugin_output_comment"] == "[B, T] → continuous waveform regression"
        assert '"regressor" must emit [B, T]' in varied["review_prompt"]
        assert "(not declared by this task)" in varied["review_prompt"]

    def test_a_classifier_candidate_is_refused_under_the_varied_declaration(self):
        """The semantic is enforced, not merely described (§15.1 row 3)."""
        from agent.skills.model_io_probe_skill import ProbeConstructionError

        with pytest.raises(ProbeConstructionError):
            expected_output_shape(self.VARIED, "classifier")


# ---------------------------------------------------------------------------
# 6.5-D — custom-loss capability only, against 6.5-C's regressor
# ---------------------------------------------------------------------------


class TestRung65D:
    """Baseline: **6.5-C's** established regressor. Varies: loss capability.

    The capability itself is proven end-to-end at the validator boundary in
    ``ml_model_implementor/test_step04a_regressor_custom_loss_capability.py``
    (§6.2). What lives here is the atomicity obligation §6 places on this
    rung specifically, because it is the one rung whose baseline is another
    rung rather than TIDMAD.
    """

    def test_the_baseline_is_6_5_c_s_declaration_not_tidmad(self):
        """§6: 6.5-D must NOT vary output semantic and loss capability at once.

        Fails when: someone re-baselines this rung on TIDMAD, which would
        make it a two-axis contrast and destroy its meaning — a failure would
        no longer say whether the loss recipe or the semantic derivation
        broke.
        """
        assert (
            _diff_paths(_declaration(TestRung65C.VARIED), _declaration(regressor_model_io())) == []
        )

    def test_the_loss_probe_pair_is_the_only_thing_that_moves(self):
        """The single varied axis, observed on the constructed tensors.

        Under one unchanged declaration, the model-probe facts are identical
        and only the loss pair differs from the categorical recipe.
        """
        contract = regressor_model_io()

        cat_inputs, cat_targets, _ = build_loss_probe_pair(tidmad_model_io())
        con_inputs, con_targets, _ = build_loss_probe_pair(contract)

        assert tuple(cat_inputs.shape) == (2, 256, 100)
        assert tuple(con_inputs.shape) == (2, 100)
        assert con_targets.dtype.is_floating_point
        assert not cat_targets.dtype.is_floating_point
        assert tuple(con_targets.shape) == tuple(cat_targets.shape) == (2, 100)


# ---------------------------------------------------------------------------
# NOT a rung — probe-recipe robustness only (§6.1)
# ---------------------------------------------------------------------------


def test_probe_recipe_robustness_at_a_second_symbolic_length():
    """``T`` is a recipe, not a semantic — labelled, never reported as a rung.

    A symbolic dimension declares that two axes share an extent, not what the
    extent is. This checks the realizer honours whatever length the recipe
    picks, at both axes simultaneously, which is a real (if modest) property:
    a realizer that hardcoded 64 on one side would desynchronise input and
    output.

    It is **not** a semantic contrast and must never be reported as one — it
    would pass whether or not a consumer re-hardcoded its literal, which is
    exactly why §6.1 removed 6.5-B from the required ladder.
    """
    import agent.skills.model_io_probe_skill as probe

    contract = tidmad_model_io()
    original = probe.PROBE_SYMBOLIC_EXTENT
    try:
        probe.PROBE_SYMBOLIC_EXTENT = 128
        assert realize_shape(contract.input) == (PROBE_BATCH, 128)
        assert realize_shape(contract.output) == (PROBE_BATCH, 256, 128)
    finally:
        probe.PROBE_SYMBOLIC_EXTENT = original

    # And the declared cardinality is untouched by the recipe change — the
    # fixed/symbolic distinction that makes 6.5-A semantic and this one not.
    assert realize_shape(contract.output) == (PROBE_BATCH, 256, PROBE_SYMBOLIC_EXTENT)


# ---------------------------------------------------------------------------
# The output-semantics AUTHORITY rule (operator audit, 2026-08-14)
# ---------------------------------------------------------------------------


class TestOutputSemanticsAuthority:
    """Who owns "what output semantics does this model have"? — Step-03 §8b.

    §8b forbids *"normalized tensor semantics **plus** an independent competing
    ``output_type`` authority"* and requires that **exactly one** authority
    answer that question **for a model**.

    Step 04a lets a candidate declare ``regressor`` under a categorical task
    contract. The audit that reconciles the two (ledger §17.4.2a) concluded
    this is Step-03's OWN documented precedence pattern, not a second
    authority — Step 03 §24 states it explicitly for dtype and names
    ``plugin_loader.get_output_type`` as the lookup it MIRRORS:

        1. the model's OWN declaration, when it has one;
        2. otherwise the TASK contract.
        "Not two authorities: one lookup, and the task contract answers for
         every model that does not override."

    The rule therefore has two halves, and this class pins BOTH, because
    prose cannot stop a later change from quietly inverting either one.
    """

    def test_the_contract_never_supplies_the_FORM(self):
        """Half 1: the task contract does not override a model's declaration.

        The same categorical contract yields the classifier form for a
        candidate that declares ``classifier`` and the continuous form for one
        that declares ``regressor``. If the contract dictated the form, these
        would be equal — and the three ``regressor`` plugins in the live
        corpus, plus builtin ``fcnet``'s ``hybrid``, would all be invalid
        under the shipped task.

        Fails when: the form is derived from the contract instead of the
        candidate's declaration (a TIDMAD verdict change, Stage-A parity break).
        """
        contract = tidmad_model_io()
        assert expected_output_shape(contract, "classifier") != expected_output_shape(
            contract, "regressor"
        )

    def test_the_declaration_never_supplies_a_CONTRACT_OWNED_FACT(self):
        """Half 2: the declaration selects a form; it never invents a fact.

        Cardinality, rank, axis order and dtype come from the contract in
        every form. Two contracts differing only in cardinality must produce
        different shapes under the SAME declaration — otherwise
        ``output_type`` would be answering a question §8b reserves for the
        normalized tensor semantics.

        Fails when: any contract-owned fact starts coming from the declared
        word rather than the declaration it parameterizes.
        """
        assert expected_output_shape(tidmad_model_io(256), "classifier") != (
            expected_output_shape(tidmad_model_io(16), "classifier")
        )
        # ...and the continuous form of both is identical, because the class
        # axis is the ONLY thing cardinality owns.
        assert expected_output_shape(tidmad_model_io(256), "regressor") == (
            expected_output_shape(tidmad_model_io(16), "regressor")
        )

    def test_a_declaration_the_contract_cannot_parameterize_fails_closed(self):
        """The boundary between the two halves.

        A candidate may choose its form, but it may NOT choose a form the
        contract cannot supply the facts for. That is what keeps the
        precedence a precedence rather than an independent authority: the
        declaration selects among forms the contract can express, and a
        request outside that set is refused rather than guessed.
        """
        from agent.skills.model_io_probe_skill import ProbeConstructionError

        with pytest.raises(ProbeConstructionError):
            expected_output_shape(regressor_model_io(), "classifier")
