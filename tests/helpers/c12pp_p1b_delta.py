"""The ONE declaration of P1-B's edit to ``proposing_stage.md``.

Step 12 / C12-P-P, P1-B (``bca52bca``). P1-B rewrote three lines of
``agent/prompt_templates/proposal/proposing_stage.md`` from TIDMAD-specific
tensor shapes into task-neutral language, so that the exact shapes come from
the task's own ``{forward_contract}`` declaration (already carried by the same
prompt) instead of from a literal baked into a shared template.

WHY THIS MODULE EXISTS AT ALL
-----------------------------
P1-B moved bytes that FOUR independent frozen baselines pin:

  * ``tests/unit/workflows/test_step12_pr12a_c7_proposal_blocks.py`` — the
    C7 relocation proof, over the ``{OUTPUT_CONTRACT_GUIDANCE}``-substituted
    stage;
  * ``tests/unit/guardrails/test_step12_pr12a_c0_legacy_parity.py`` — the raw
    template bytes;
  * the four ``goldens/*_proposing_*_system.txt`` prompt goldens (PB-3 and
    P3-C0), which hold the same lines FULLY RENDERED.

Each of those has to answer the same question — "is the current tree the
recorded past plus exactly ONE declared, reviewable edit?" — and each answers
it by reversing the edit and landing back on a recorded digest. Three private
copies of the same line table would drift: a contributor amending the edit in
one module would leave the other two describing a file that no longer exists,
and a stale table CANNOT fail loudly on its own (it fails as "not present
exactly once", which reads like a bug in the guard). Declaring the edit once,
here, is what makes "the SAME edit" a mechanical fact rather than a claim
repeated in three places.

This module holds NO digests. Each consumer keeps its own hardcoded epoch-1
and epoch-2 digests, because those are statements about that consumer's own
surface and must not be centralized into something a single edit could move.
"""

from __future__ import annotations

#: P1-B's edit as ``(post_p1b_line, pre_p1b_line)`` pairs, in the form the
#: RAW TEMPLATE carries — i.e. with ``{CLASSIFIER_LOSS_LIST}`` and
#: ``{REGRESSOR_LOSS_LIST}`` still unsubstituted.
#:
#: Used by the raw-template pin (C0 legacy parity) and by the C7 relocation
#: proof, whose reconstruction substitutes ``{OUTPUT_CONTRACT_GUIDANCE}``
#: ONLY and therefore still carries the loss-list placeholders.
P1B_TEMPLATE_DELTA: tuple[tuple[str, str], ...] = (
    (
        '  "output_type": "classifier | regressor — REQUIRED. See \'Output contract\' above '
        "and this task's forward contract below for the exact shapes. classifier -> a "
        "per-class score axis, with ce/focal/focal_cw; regressor -> continuous values, with "
        'smooth_l1. Independent of loss_type: state it explicitly, never infer it.",',
        '  "output_type": "classifier | regressor — REQUIRED. See \'Output contract\' above. '
        "classifier -> [B, 256, T] with ce/focal/focal_cw; regressor -> [B, T] with "
        'smooth_l1. Independent of loss_type: state it explicitly, never infer it.",',
    ),
    (
        '| `"classifier"` | a per-class score axis (exact shape: forward contract below) '
        "| {CLASSIFIER_LOSS_LIST} |",
        '| `"classifier"` | `[B, 256, T]` float | {CLASSIFIER_LOSS_LIST} |',
    ),
    (
        '| `"regressor"`  | continuous values (exact shape: forward contract below)      '
        "| {REGRESSOR_LOSS_LIST}               |",
        '| `"regressor"`  | `[B, T]` float      | {REGRESSOR_LOSS_LIST}               |',
    ),
)

#: The SAME edit as it appears in a fully rendered prompt: the loss-list
#: placeholders have been replaced by ``_render_loss_legality``'s output, so
#: the two table rows differ from `P1B_TEMPLATE_DELTA` in that column only.
#: The ``output_type`` line carries no placeholder and is shared verbatim.
#:
#: Derived from the template pairs by the same substitution production
#: performs, so the two tables cannot describe different edits.
P1B_RENDERED_DELTA: tuple[tuple[str, str], ...] = tuple(
    (
        post.replace("{CLASSIFIER_LOSS_LIST}", "`ce`, `focal`, `focal_cw`").replace(
            "{REGRESSOR_LOSS_LIST}", "`smooth_l1`"
        ),
        pre.replace("{CLASSIFIER_LOSS_LIST}", "`ce`, `focal`, `focal_cw`").replace(
            "{REGRESSOR_LOSS_LIST}", "`smooth_l1`"
        ),
    )
    for post, pre in P1B_TEMPLATE_DELTA
)


def reverse_p1b(text: str, delta: tuple[tuple[str, str], ...], *, surface: str) -> str:
    """Undo P1-B's declared edit, failing loudly if the table is stale.

    Args:
        text: The CURRENT (post-P1-B) bytes of the surface.
        delta: `P1B_TEMPLATE_DELTA` or `P1B_RENDERED_DELTA`.
        surface: Human name of the surface, for the failure message.

    Returns:
        ``text`` with each declared post-P1-B line replaced by its pre-P1-B
        original — i.e. what the surface looked like before P1-B, IF P1-B's
        edit is the only difference.

    Raises:
        AssertionError: if a declared line does not occur EXACTLY once. That
            is not "the guard failed"; it means the declared edit no longer
            describes the file, so the caller's epoch bridge is stale and
            must be re-declared rather than re-pointed.
    """
    for post_p1b, pre_p1b in delta:
        occurrences = text.count(post_p1b)
        assert occurrences == 1, (
            f"[{surface}] a line declared in the P1-B delta occurs "
            f"{occurrences} times, expected exactly 1: {post_p1b[:70]!r}… — "
            "the declared edit no longer describes this surface, so the "
            "epoch bridge is STALE. Re-declare the edit in "
            "tests/helpers/c12pp_p1b_delta.py; do not re-point a digest."
        )
        text = text.replace(post_p1b, pre_p1b)
    return text
