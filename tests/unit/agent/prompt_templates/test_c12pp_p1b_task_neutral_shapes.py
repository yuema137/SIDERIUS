"""C12-P-P / P1-B — the proposing template asserts no task's shapes as universal.

WHAT P1-B CHANGED
-----------------
``proposing_stage.md`` hardcoded ``[B, 256, T]`` (:41, :70) and ``[B, T]``
(:71) as THE classifier / regressor output shapes. Those are TIDMAD's: 256 is
the int8 ADC amplitude axis and ``[B, T]`` is a 1-D sequence. They had no
placeholder, so no declared channel could suppress them.

CLASSIFICATION B — rewrite in task-neutral terms, no new channel.

WHY REMOVING THEM IS SAFE, NOT LOSSY
------------------------------------
The run's REAL shapes are already in the SAME prompt: ``{forward_contract}``
at :130, fed at ``ml_model_proposal_agent.py`` by
``render_forward_contract(inp.forward_contract)``. The removed literals were a
redundant duplicate that happened to be right for exactly one task. ``B2``
below is the executable form of that safety argument — it is the test that
would have blocked this change had the claim been false.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent.schemas.task_config import ForwardContract
from workflows.task_config import render_forward_contract

REPO_ROOT = Path(__file__).resolve().parents[4]
TEMPLATE = REPO_ROOT / "agent" / "prompt_templates" / "proposal" / "proposing_stage.md"

#: Hardcoded TIDMAD shape literals. Never derived from a config — a marker read
#: back from the thing under test follows it when it changes and can never fail.
_TIDMAD_SHAPE_LITERALS = ("[B, 256, T]", "[B, T]")

#: The generic vocabulary that must SURVIVE. Removing the examples must not
#: remove the concept.
_REQUIRED_CONCEPTS = (
    "classifier",
    "regressor",
    "{CLASSIFIER_LOSS_LIST}",
    "{REGRESSOR_LOSS_LIST}",
    "{forward_contract}",
)

_TASK_CONFIGS = {
    "tidmad": REPO_ROOT / "configs" / "task_config.yaml",
    "pets": REPO_ROOT / "examples" / "oxford_iiit_pet" / "declared" / "task_config.yaml",
    "davis": REPO_ROOT / "examples" / "davis_future_prediction" / "declared" / "task_config.yaml",
}


def _template() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def _rendered_contract(task: str) -> str:
    """Render one task's DECLARED contract.

    Reads the YAML and renders directly — deliberately NOT through
    ``load_task_config``, which resolves the contract against the ambient
    dataset profile and raises ``DatasetContradictionError`` for a pack whose
    class count differs from TIDMAD's. That resolution is not what B2 is about:
    B2 asks what the CONTRACT BLOCK says, and the aggregate test (which does
    need production resolution) binds a real composition instead.
    """
    raw = yaml.safe_load(_TASK_CONFIGS[task].read_text(encoding="utf-8"))
    return render_forward_contract(ForwardContract(**raw["forward_contract"]))


# ==========================================================================
# B1 — no task's shapes are asserted as universal
# ==========================================================================


def test_b1_template_asserts_no_hardcoded_task_shape() -> None:
    """The proposing template contains no TIDMAD output-shape literal.

    DEFECT THIS ALONE CATCHES
        A TIDMAD shape re-entering the shared template. No channel can suppress
        a literal here, so it reaches EVERY task — the P1-A suppression path
        does not and cannot cover it. This is the only guard on that surface.

    HOW IT FAILS ON REGRESSION
        Any reintroduced ``[B, 256, T]`` or ``[B, T]`` in the template body is
        named in the failure message.
    """
    body = _template()
    found = [lit for lit in _TIDMAD_SHAPE_LITERALS if lit in body]
    assert found == [], (
        f"proposing_stage.md asserts TIDMAD-specific output shapes {found} as "
        "universal. A 37-class image task and a dense video-regression task "
        "have neither. The task's real shapes arrive via {forward_contract}."
    )


# ==========================================================================
# B2 — TIDMAD loses NO required scientific instruction  (the safety proof)
# ==========================================================================


def test_b2_tidmad_still_receives_its_shapes_from_the_forward_contract() -> None:
    """Removing the literals costs TIDMAD nothing: its contract still says them.

    DEFECT THIS ALONE CATCHES
        P1-B being genuinely LOSSY. Its whole safety argument is that
        ``{forward_contract}`` carries the authoritative shapes in the same
        prompt. If that block ever stopped rendering TIDMAD's ``[B, 256, T]``,
        the removal in B1 would have deleted the only statement of it — and B1
        would still pass, because B1 only checks absence.

        This is the test that makes the pair honest rather than merely green.

    HOW IT FAILS ON REGRESSION
        The rendered TIDMAD contract no longer contains the shape, and the
        assertion says so explicitly.
    """
    rendered = _rendered_contract("tidmad")
    assert "[B, 256, T]" in rendered, (
        "TIDMAD's forward contract no longer states [B, 256, T]. P1-B removed "
        "the template's duplicate on the express grounds that this block "
        "carries it — so that removal is now LOSSY and must be revisited."
    )
    assert "[B, T]" in rendered


# ==========================================================================
# B3' — the generic concept survives the rewrite
# ==========================================================================


@pytest.mark.parametrize("concept", _REQUIRED_CONCEPTS)
def test_b3_generic_output_contract_vocabulary_survives(concept: str) -> None:
    """classifier/regressor and both loss lists still render.

    DEFECT THIS ALONE CATCHES
        Over-deletion. The cheapest way to make B1 pass is to delete the
        Output-contract section outright, which would strip a framework
        decision the proposer must still make and which loss families are
        legal. B1 and B4 would both stay green through that.

    HOW IT FAILS ON REGRESSION
        The missing concept is named.
    """
    assert concept in _template(), (
        f"the generic output-contract vocabulary lost {concept!r}; P1-B removes "
        "TIDMAD's example shapes, never the framework concept"
    )


# ==========================================================================
# B4' — no task is told something its own contract contradicts
# ==========================================================================


@pytest.mark.parametrize("task", ["pets", "davis"])
def test_b4_foreign_contract_is_not_contradicted_by_the_template(task: str) -> None:
    """A foreign task's rendered contract shares no shape claim with the template.

    DEFECT THIS ALONE CATCHES
        The self-contradiction that motivated P1-B. Before the fix one DAVIS
        prompt simultaneously said 'classifier -> [B, 256, T]' (:41) and
        'output: [B, 3, 4, 128, 224] ... NOT logits and NOT class indices'
        (:130). B1 checks the template in isolation; this asserts the template
        against what each foreign task actually declares, which is the property
        a reader of the assembled prompt would notice.

    HOW IT FAILS ON REGRESSION
        A reintroduced literal is reported together with the contract line it
        contradicts.
    """
    body = _template()
    rendered = _rendered_contract(task)
    assert rendered.strip(), f"{task} declares an empty forward contract"

    for literal in _TIDMAD_SHAPE_LITERALS:
        if literal in body and literal not in rendered:
            raise AssertionError(
                f"the shared template asserts {literal!r} while {task}'s own "
                f"contract declares:\n{rendered}"
            )
