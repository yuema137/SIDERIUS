"""Step 12 / PR-12a — C0 LEGACY BYTE-PARITY BASELINES.

Design:
``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12a_composed_path_closure.md`` §5 C0 item 1.

The frozen invariant this module owns:

    Legacy (un-composed, regime-A) behaviour stays byte-compatible under
    R-11-13's wording — the legacy transport OPTION SURFACE and execution
    semantics are byte-identical; only an explicitly frozen canonical
    path-token rule may differ.

PR-12a changes prompt assembly (C7), the Health config hand-off (C1), the
per-model lock's identity kwargs (C2) and the plugin-registration authority
(C6). Every one of those has a legacy branch that must not move, so each gets
a baseline HERE, before any of it changes.

WHAT IS PINNED, AND WHY THAT FORM
---------------------------------
* **Rendered prompt bytes.** A pinned pseudo tuner run drives the PRODUCTION
  ``plan()`` / ``reflect()`` render paths through ``StubLLMBridge`` and the
  result is reduced by the Step-10 P1 parity reducer — the same seven
  dimensions that PR's evidence used, deliberately reused rather than
  re-implemented. This catches an ASSEMBLY change that a template-constant
  hash cannot see.
* **Prompt template constants.** The bytes C7 actually edits. Pinning them
  makes the C7 contract explicit: gate at the assembly, do not edit the
  legacy-rendered constant. A template edit turns this RED and C7 must then
  show the rendered legacy manifest is still identical.
* **The legacy run-invariants lock and effective Health config.** C1/C2 add
  composed-only kwargs; the un-composed lock must serialize the same keys with
  the same values, and the omitted-when-``None`` rule must survive.

WHAT IS NOT DUPLICATED
----------------------
Legacy **argv** is already owned by ``TestLegacyArgvFlagBaseline`` in
``tests/unit/core/test_step11_c0_baselines.py``. PR-12a emits no new argv, so
that standing census is CITED (below) rather than copied — a second copy would
be one more thing to keep in sync and no additional failure class.

WHAT IS DELIBERATELY *NOT* NORMALIZED
-------------------------------------
The prompt capture normalizes wall-clock timestamps and nothing else; see
``tests/helpers/step12_pr12a_prompt_capture.py``. Workspace paths, model
names, scores, ordering and whitespace are all compared raw. The capability
index is PINNED to an empty one rather than scrubbed, because
``agent_generated/`` is gitignored machine-local state and a sha over a prompt
embedding it would pass locally and fail on a fresh CI clone.
"""

from __future__ import annotations

import hashlib
import json
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ======================================================================
# 1. Rendered legacy prompt bytes
# ======================================================================

#: Captured at the PR-12a base ``eeb073dc`` (source ``e4cd5c18``). Verified
#: identical across three separate fresh interpreter processes before being
#: frozen — a baseline that is not reproducible is a claim, not a proof.
LEGACY_TUNER_PROMPT_MANIFEST_SHA = (
    "6e8de64b660da36c4801bd0e9d590e206dcf4f1395701305d5115bfe753039d6"
)

#: The per-call shape, recorded beside the digest so a mismatch localizes to a
#: call index and a dimension instead of reporting "the hashes differ".
LEGACY_TUNER_PROMPT_SHAPE: tuple[tuple[str, int, int], ...] = (
    ("tuner.planner", 14152, 16858),
    ("tuner.planner", 14152, 19162),
    ("tuner.reflector", 9677, 2854),
    ("tuner.planner", 18252, 36499),
    ("tuner.reflector", 9677, 3163),
)


class TestLegacyRenderedPromptBytes:
    """An UN-COMPOSED tuner run's rendered prompts, byte for byte.

    HOW THIS FAILS WHEN C7 BREAKS THE CONTRACT: C7 gates TIDMAD's science
    behind composition presence. If the gating is written so that the LEGACY
    branch also loses (or reorders, or re-spaces) a block, this manifest's
    sha moves and the per-call table names which call and which dimension.
    """

    def test_the_legacy_manifest_is_byte_identical(self, tmp_path, monkeypatch):
        from tests.helpers.step12_pr12a_prompt_capture import capture_tuner_prompts

        manifest = capture_tuner_prompts(tmp_path, monkeypatch)

        observed = tuple(
            (row["label"], row["system_bytes"], row["user_bytes"]) for row in manifest["calls"]
        )
        assert observed == LEGACY_TUNER_PROMPT_SHAPE
        assert manifest["manifest_sha256"] == LEGACY_TUNER_PROMPT_MANIFEST_SHA

    def test_the_capture_observes_the_real_render_path(self, tmp_path, monkeypatch):
        """Anti-vacuity: a capture that recorded a test's own strings would
        pin nothing. The planner system prompt must contain a substring that
        exists ONLY in the production template."""
        from agent.prompts import PLANNER_PROMPT
        from tests.helpers.step12_pr12a_prompt_capture import capturing_bridge_class

        assert "### BASELINE REFERENCE RULE:" in PLANNER_PROMPT
        bridge = capturing_bridge_class()()
        assert bridge.captures == []

        from tests.helpers.step00_pseudo_iteration import run_bounded_pseudo_iteration
        from tests.helpers.step12_pr12a_prompt_capture import PREFLIGHT_FIXTURE

        index = tmp_path / "index.json"
        index.write_text("[]", encoding="utf-8")
        run_bounded_pseudo_iteration(
            tmp_path,
            monkeypatch,
            preflight_results=json.loads(PREFLIGHT_FIXTURE.read_text(encoding="utf-8"))["results"],
            bridge=bridge,
            capability_index_path=str(index),
        )
        systems = [c["system"] for c in bridge.captures if c["label"] == "tuner.planner"]
        assert systems, "no planner call was captured"
        assert all("### BASELINE REFERENCE RULE:" in s for s in systems)


# ======================================================================
# 2. Prompt template constants — the bytes C7 edits
# ======================================================================

#: ``name -> sha256`` over each LLM-facing production prompt constant and
#: template file PR-12a's C7 touches. Frozen at ``eeb073dc``; the rows marked
#: below were RE-FROZEN inside PR-12a itself, so this table's epoch is "the
#: tree as PR-12a landed it" (``15554174``) rather than the C0 base for those
#: rows. See ``POST_P1B_PROMPT_SOURCE_SHA`` for why that distinction now
#: matters.
PROMPT_SOURCE_SHA: dict[str, str] = {
    # RE-FROZEN by C7-2, with the evidence its own docstring demanded.
    #
    #   C0 base   PLANNER   43366ba9be8e01d08908a906fa474de13424afb92ff3ff63cb0fdbace2da6f71
    #             REFLECTOR 2ea3baf227d970bff6ab58a80ed4aeb7377de40a32ad3d2c9f613040d634cef4
    #
    # C7-3 re-froze two more: `PROPOSAL_REASONING_PROMPT` and
    # `proposing_stage.md`, whose TIDMAD prose moved into
    # `configs/task_proposal/tidmad.yaml`. That relocation is proved
    # BYTE-EXACT — substituting the declared blocks back reproduces these
    # files' pre-C7 sha256 — by
    # `test_step12_pr12a_c7_proposal_blocks.TestTheRelocationIsBYTE_EXACT`,
    # which hardcodes the ORIGINAL digests rather than recomputing them.
    #
    # SEVEN blocks became named substitution TOKENS
    # (`{AVAILABLE_MODELS_BLOCK}`, `{PER_FILE_TABLE_PROTOCOL}`,
    # `{SCORE_FIELD_NOUN}`, `{SCORE_DISPLAY_NOUN}`,
    # `{TARGET_STRATEGY_IMPACT_NOTE}`, `{SAMPLING_IMPACT_TRADEOFF}`,
    # `{PER_FILE_COMPARISON_BLOCK}`), and their legacy bytes
    # moved VERBATIM into the render authority. The condition this test's
    # docstring set for re-freezing — "prove the legacy rendered manifest is
    # still identical" — is met: `LEGACY_TUNER_PROMPT_MANIFEST_SHA` is
    # UNCHANGED at 6e8de64b…, so what an un-composed run actually sends is
    # byte-for-byte what it sent before. The constants moved; the prompt did
    # not.
    "agent.prompts.PLANNER_PROMPT": (
        "c039c89092e98a152a42fb9ac60920068e57fc995e363474e30c789ec6bb521b"
    ),
    "agent.prompts.REFLECTOR_PROMPT": (
        "94cdf8ba464792d0cf4a4f7ced7c283cd856598bab91ed551c50544273e4fbee"
    ),
    "implementor.IMPLEMENTOR_CODE_PROMPT": (
        "e14e9db5b26d1a4802d798215025c92928bdc079f360d0f7b65f425a473c9b98"
    ),
    # RE-FROZEN by C7-4 on the same condition, and it is met the same way:
    # the role line became `{ENGINEER_ROLE}` and its TIDMAD specialism moved
    # into `configs/task_implementor/tidmad.yaml`. Substituting the declared
    # blocks back reproduces the ORIGINAL
    # 5f32ce79e121318360a6cf72d907d87bd3cfb2598e0a6a6536c4d4d1696c020b —
    # hardcoded, not recomputed, in
    # `test_step12_pr12a_c7_implementor_blocks.TestLegacyRenderedPromptByteParity`
    # — and the PB-5 prompt goldens are UNCHANGED, so an un-composed run still
    # sends exactly the bytes it sent at `eeb073dc`.
    "implementor.IMPLEMENTOR_REASONING_PROMPT": (
        "f484a166249880509ae8f4bdbe4b3ba9adfba8b743fa8b89725662519887bf9a"
    ),
    "implementor.IMPLEMENTOR_REPAIR_PROMPT": (
        "18d51cfe9ea87d6b3cced2fd10ec01565cff04175fda9aec8853770cf4731132"
    ),
    "prompt_templates/proposal/causal_reasoning_stage.md": (
        "b153695681665b847e312a705985ad8654106e7bc932d18325640768420835f0"
    ),
    "prompt_templates/proposal/causal_reasoning_stage_exploit.md": (
        "cbf18435eb5970f142d0bf89b9ac32c8dec2822edbc4d3a6da9a19d720a6f15b"
    ),
    "prompt_templates/proposal/causal_reasoning_stage_explore.md": (
        "654961f557aa98b1e22197f2403fabdcdf4b9cb413b5aa1671b6c951fcedcffa"
    ),
    "prompt_templates/proposal/comparison_stage.md": (
        "f4ef2657e9e499882bfabed0e47211abe802bcf88c38476427fe24aa7da04b48"
    ),
    "prompt_templates/proposal/comparison_stage_exploit.md": (
        "4bd0e8106ec9225e5fa2a294d2055e52f26b59c2740089191557041b8e6d3d7c"
    ),
    "prompt_templates/proposal/comparison_stage_explore.md": (
        "fe0b6212c1dd88981052d4d9fe32429f4fbea4ab6351fdffadcc65db91872ed5"
    ),
    "prompt_templates/proposal/proposing_stage.md": (
        "1d33b844af99f0511c562e98d6b269bd574a2e30fbefb3783a234bd951abf543"
    ),
    "prompt_templates/proposal/proposing_stage_exploit.md": (
        "44dbc4223db1a4634e1c465a4416f7664c45353c05599dc57be0112644cd75ec"
    ),
    "prompt_templates/proposal/proposing_stage_explore.md": (
        "7d6a53af9b44d0922bada12dec4f733741e180e43621965e824539ff59ca05a1"
    ),
    # RE-FROZEN by C7-5 (F-12a-C9-1) — the Pr2/Pr3 residues C7-3 did not reach.
    # The condition is met on the strongest available evidence for each:
    #
    #   PROPOSAL_REASONING_PROMPT  substituted -> 7c69ce7bae2509b8…  == C0 original
    #   PROPOSAL_COMMIT_PROMPT     rendered    == pb4_legacy_commit_system.txt
    #                                             (its golden, UNCHANGED)
    #
    # The commit prompt has no pre-C7 CONSTANT digest to compare against —
    # Step 01a had already tokenized it — so its parity is proved against the
    # committed golden of the RENDER, which is what the model actually reads.
    "proposal.PROPOSAL_COMMIT_PROMPT": (
        "036f3926199a254d936b1d02a42f9c3ab58b686d6e620886e62ae4128dec4972"
    ),
    "proposal.PROPOSAL_REASONING_PROMPT": (
        "a741c831e9fc78d964999191cf7c934096001cb9e87edcba973d9729220ba107"
    ),
}


#: EPOCH 2 — the OVERLAY for surfaces a LATER, deliberate change has moved
#: since ``PROMPT_SOURCE_SHA`` was last frozen. Keys here shadow the table
#: above; every other surface stays pinned at its epoch-1 value.
#:
#: WHY AN OVERLAY AND NOT A RE-FREEZE IN PLACE. ``test_prompt_bytes_are_
#: unchanged``'s message says a moved constant may be re-frozen once "the
#: legacy rendered manifest is still identical". That condition was written
#: for C7-2/C7-3, which TOKENIZED these templates — the bytes moved while what
#: a real model reads did not, so re-freezing recorded a relocation.
#:
#: Step 12 / C12-P-P's P1-B is NOT that. It rewrites three lines of
#: ``proposing_stage.md`` from TIDMAD-specific tensor shapes into task-neutral
#: static wording, so a LEGACY un-composed proposer run genuinely sends
#: different bytes to the model. The named condition is nevertheless
#: technically satisfiable, because ``LEGACY_TUNER_PROMPT_MANIFEST_SHA``
#: covers the TUNER's assembly and never covered a proposer template at all —
#: i.e. a bare re-freeze here would have passed its own stated test while
#: recording a real legacy behaviour change as if it were byte-neutral. That
#: is the "green for the wrong reason" shape, so the two epochs are named
#: separately instead.
#:
#: DERIVATION, and the only one permitted: apply
#: ``tests/helpers/c12pp_p1b_delta.P1B_TEMPLATE_DELTA`` to the epoch-1 bytes
#: (``bca52bca~1``, digest ``1d33b844…``). That yields ``75932e34…``, verified
#: equal to the value hardcoded here. It is deliberately NOT "whatever the
#: tree hashes to" — ``TestTheProposingStageIsOneDeclaredEditFromEpochOne``
#: proves the two constants are exactly one declared edit apart.
POST_P1B_PROMPT_SOURCE_SHA: dict[str, str] = {
    "prompt_templates/proposal/proposing_stage.md": (
        "75932e347b87a4bbfabf0b207701acae7e0cb6d213ab188a4f6cd3005121ca39"
    ),
}


def _prompt_sources() -> dict[str, str]:
    """The live prompt bytes, by name."""
    from agent.prompts import PLANNER_PROMPT, REFLECTOR_PROMPT
    from nodes.ml_model_implementor.ml_model_implementor import (
        IMPLEMENTOR_CODE_PROMPT,
        IMPLEMENTOR_REASONING_PROMPT,
        IMPLEMENTOR_REPAIR_PROMPT,
    )
    from nodes.ml_model_proposal_agent.ml_model_proposal_agent import (
        PROPOSAL_COMMIT_PROMPT,
        PROPOSAL_REASONING_PROMPT,
    )

    sources = {
        "agent.prompts.PLANNER_PROMPT": PLANNER_PROMPT,
        "agent.prompts.REFLECTOR_PROMPT": REFLECTOR_PROMPT,
        "proposal.PROPOSAL_REASONING_PROMPT": PROPOSAL_REASONING_PROMPT,
        "proposal.PROPOSAL_COMMIT_PROMPT": PROPOSAL_COMMIT_PROMPT,
        "implementor.IMPLEMENTOR_REASONING_PROMPT": IMPLEMENTOR_REASONING_PROMPT,
        "implementor.IMPLEMENTOR_CODE_PROMPT": IMPLEMENTOR_CODE_PROMPT,
        "implementor.IMPLEMENTOR_REPAIR_PROMPT": IMPLEMENTOR_REPAIR_PROMPT,
    }
    template_dir = REPO_ROOT / "agent" / "prompt_templates" / "proposal"
    for path in sorted(template_dir.glob("*.md")):
        sources[f"prompt_templates/proposal/{path.name}"] = path.read_text(encoding="utf-8")
    return sources


class TestLegacyPromptSourceBytes:
    """Every prompt constant/template C7 may touch, pinned by content.

    This is NOT a duplicate of the rendered manifest: the manifest covers the
    TUNER's assembly only, while the proposer and implementor surfaces are
    rendered by other nodes. Pinning their source bytes is what makes a C7
    edit to them a deliberate, recorded act rather than a silent one.
    """

    def test_the_baseline_covers_every_prompt_surface_c7_touches(self):
        assert set(PROMPT_SOURCE_SHA) == set(_prompt_sources()), (
            "a prompt surface appeared or disappeared. Add or remove it in the "
            "SAME commit that changes it, with the reason recorded in the "
            "design ledger — never let the baseline silently follow the source."
        )

    @pytest.mark.parametrize("name", sorted(PROMPT_SOURCE_SHA))
    def test_prompt_bytes_are_unchanged(self, name):
        expected = POST_P1B_PROMPT_SOURCE_SHA.get(name, PROMPT_SOURCE_SHA[name])
        assert _sha(_prompt_sources()[name]) == expected, (
            f"{name} changed. If C7 gated TIDMAD science at the ASSEMBLY, this "
            f"should not move. If the surface genuinely had to change, do NOT "
            f"re-point the row above: state whether a legacy un-composed run's "
            f"LLM-facing bytes moved, declare the edit in "
            f"tests/helpers/c12pp_p1b_delta.py, and add an epoch row to "
            f"POST_P1B_PROMPT_SOURCE_SHA with a bridge proving the new value "
            f"is the old one plus exactly that edit."
        )


class TestTheProposingStageIsOneDeclaredEditFromEpochOne:
    """The bridge between ``PROMPT_SOURCE_SHA`` and its P1-B overlay.

    Two digests over the same file cannot detect a SILENT REPIN: each is
    individually satisfied by any bytes at all, so a contributor who edits the
    template and pastes the new digest into the overlay gets a green suite and
    an unreviewable change. Reversing the ENUMERATED edit and landing on the
    epoch-1 digest is the only assertion here that spans both epochs, which is
    why it is a separate row rather than an extra line in the pin above.
    """

    def test_reversing_p1b_reproduces_the_epoch_one_template_bytes(self):
        """DEFECT ONLY THIS CATCHES: ``POST_P1B_PROMPT_SOURCE_SHA`` re-pointed
        to whatever ``proposing_stage.md`` currently hashes to, without
        declaring what changed — including an undeclared edit riding along in
        the same commit as a declared one.

        HOW IT FAILS WHEN THE BEHAVIOUR BREAKS: either a line declared in
        ``P1B_TEMPLATE_DELTA`` stops occurring exactly once in the live
        template (``reverse_p1b`` raises, naming the stale table), or the
        reversed bytes miss ``PROMPT_SOURCE_SHA``'s hardcoded epoch-1 digest,
        proving the tree differs from the recorded past by more than the
        declared edit.
        """
        from tests.helpers.c12pp_p1b_delta import P1B_TEMPLATE_DELTA, reverse_p1b

        name = "prompt_templates/proposal/proposing_stage.md"
        reverted = reverse_p1b(_prompt_sources()[name], P1B_TEMPLATE_DELTA, surface=f"live {name}")
        assert _sha(reverted) == PROMPT_SOURCE_SHA[name], (
            "reversing P1-B's declared edit did NOT reproduce the epoch-1 "
            "bytes of proposing_stage.md. The current template differs from "
            "the recorded past by something OTHER than the declared edit. "
            "Declare that change in tests/helpers/c12pp_p1b_delta.py; do NOT "
            "re-point PROMPT_SOURCE_SHA."
        )

    def test_the_overlay_shadows_only_surfaces_the_declared_edit_reaches(self):
        """DEFECT ONLY THIS CATCHES: an overlay row for a surface the declared
        edit does not touch — the shape a silent repin takes when it is
        dressed as P1-B. Such a row would disable that surface's epoch-1 pin
        permanently while the bridge above, which only ever looks at the
        proposing stage, stayed green.

        HOW IT FAILS: an overlay key is absent from the epoch-1 table, or its
        live bytes carry none of the declared post-P1-B lines.
        """
        from tests.helpers.c12pp_p1b_delta import P1B_TEMPLATE_DELTA

        sources = _prompt_sources()
        for name in POST_P1B_PROMPT_SOURCE_SHA:
            assert name in PROMPT_SOURCE_SHA, (
                f"{name} is overlaid at epoch 2 but has no epoch-1 row — an "
                "overlay must record a MOVE, never introduce a surface"
            )
            assert any(post in sources[name] for post, _pre in P1B_TEMPLATE_DELTA), (
                f"{name} is overlaid as a P1-B consequence but carries none of "
                "P1-B's declared lines — its epoch-1 pin has been disabled by "
                "an unrelated change wearing P1-B's name"
            )


# ======================================================================
# 3. The legacy run-invariants lock and effective Health config
# ======================================================================

#: The serialized key set of an un-composed lock. The composition key is
#: OMITTED, never ``null`` — the property C2 must not disturb.
LEGACY_LOCK_KEYS: frozenset[str] = frozenset(
    {
        "resolved_data_scope",
        "health_gate_enabled",
        "health_config_sha256",
        "ordering_override_strategy",
        "ordering_override_file_order",
        "structured_health_feedback_enabled",
        "health_feedback_history_window_iterations",
        "health_feedback_history_max_entries_per_model",
        "runtime_estimator_identity",
        "runtime_policy_identity",
        "created_at",
        "execution_calibration",
    }
)


class TestLegacyLockShape:
    def test_an_un_composed_tuner_run_writes_exactly_these_keys(self, tmp_path, monkeypatch):
        from tests.helpers.step00_pseudo_iteration import run_bounded_pseudo_iteration
        from tests.helpers.step12_pr12a_prompt_capture import PREFLIGHT_FIXTURE

        _output, _bridge, _sandbox, workspace = run_bounded_pseudo_iteration(
            tmp_path,
            monkeypatch,
            preflight_results=json.loads(PREFLIGHT_FIXTURE.read_text(encoding="utf-8"))["results"],
        )
        locks = sorted(pathlib.Path(workspace).rglob("run_invariants_lock.json"))
        assert locks, "the run must write a lock, or this baseline is vacuous"
        for lock in locks:
            payload = json.loads(lock.read_text(encoding="utf-8"))
            assert set(payload) == LEGACY_LOCK_KEYS, lock
            assert payload["health_gate_enabled"] is False
            assert payload["health_config_sha256"] is None

    def test_the_legacy_health_binding_still_resolves_state_a(self, tmp_path):
        """C1 changes what the tuner is HANDED, not what an un-composed run
        resolves. The legacy effective document must keep the
        ``legacy_default`` marker and its body sha must stay reproducible from
        the same inputs."""
        from core.run_invariants import build_run_invariants

        first, path_a = build_run_invariants(
            resolved_data_scope=list(range(20)),
            health_gate_enabled=True,
            health_gate_files=None,
            health_checks_config=None,
            workspace=str(tmp_path / "a"),
        )
        (tmp_path / "b").mkdir(parents=True, exist_ok=True)
        second, path_b = build_run_invariants(
            resolved_data_scope=list(range(20)),
            health_gate_enabled=True,
            health_gate_files=None,
            health_checks_config=None,
            workspace=str(tmp_path / "b"),
        )
        assert first.health_config_sha256 == second.health_config_sha256
        assert first.task_composition_fingerprint is None
        body_a = pathlib.Path(path_a).read_text(encoding="utf-8")
        body_b = pathlib.Path(path_b).read_text(encoding="utf-8")
        assert "task_health_binding: legacy_default" in body_a
        assert body_a == body_b

    def test_the_workspace_dir_must_exist_for_the_baseline_above(self, tmp_path):
        """Guards the fixture itself: ``build_run_invariants`` writes into the
        workspace, so a baseline written against a missing directory would be
        measuring an exception, not a document."""
        (tmp_path / "a").mkdir(parents=True, exist_ok=True)
        assert (tmp_path / "a").is_dir()


# ======================================================================
# 4. Cited, not duplicated
# ======================================================================


class TestLegacyArgvIsOwnedElsewhere:
    """PR-12a emits no argv. The legacy argv surface stays owned by the
    Step-11 C0 census; this test exists so the citation is executable — if
    that owner is renamed away, PR-12a's parity claim loses its basis and
    someone has to decide where it moved."""

    def test_the_step11_argv_census_still_exists(self):
        source = (REPO_ROOT / "tests" / "unit" / "core" / "test_step11_c0_baselines.py").read_text(
            encoding="utf-8"
        )
        assert "class TestLegacyArgvFlagBaseline:" in source
        assert "def test_no_composition_means_no_task_data_path_flag" in source
