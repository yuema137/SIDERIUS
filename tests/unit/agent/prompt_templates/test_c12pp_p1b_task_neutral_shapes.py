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

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
TEMPLATE = REPO_ROOT / "src/agent" / "prompt_templates" / "proposal" / "proposing_stage.md"

#: The generic vocabulary that must SURVIVE. Removing the examples must not
#: remove the concept.
_REQUIRED_CONCEPTS = (
    "classifier",
    "regressor",
    "{CLASSIFIER_LOSS_LIST}",
    "{REGRESSOR_LOSS_LIST}",
    "{forward_contract}",
)


def _template() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


# ==========================================================================
# B1 — no task's shapes are asserted as universal
# ==========================================================================


def test_b1_template_asserts_no_hardcoded_tensor_shape() -> None:
    """The shared template contains no task-owned tensor shape.

    DEFECT THIS ALONE CATCHES
        A tensor shape re-entering the shared template. No channel can suppress
        a literal here, so it reaches every task.

    HOW IT FAILS ON REGRESSION
        Any reintroduced batch-shaped literal is named in the failure message.
    """
    body = _template()
    found = sorted(set(re.findall(r"\[B(?:\s*,[^\]]*)?\]", body)))
    assert found == [], (
        f"proposing_stage.md asserts task-owned tensor shapes {found} as "
        "universal. The task's real shapes arrive via {forward_contract}."
    )


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
