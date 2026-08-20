"""The narrow strategy vocabularies threaded through the exploration workflow.

Extracted from ``workflows.model_exploration`` in Step 09.5a C2 so that
:mod:`workflows.run_config` can type its fields without importing the workflow
module — which would be a cycle, since the workflow imports the carrier.

These are the SAME aliases, moved rather than redefined:
``model_exploration`` re-exports them, so every existing import keeps working
and there is exactly one definition of each.
"""

from __future__ import annotations

from typing import Literal

#: How the proposer's reasoning pipeline chooses between exploring a new
#: architecture family and exploiting the current one. ``"auto"`` lets the
#: pipeline resolver decide from ``n_agent_proposed`` and the vocabulary
#: diversity ratio.
ExplorationMode = Literal["auto", "explore", "exploit"]

#: How a round selects the files it trains or evaluates on. Under a partial
#: ``DataScope`` only ``"snapshot"`` is legal — see
#: ``docs/design/enable_partial_file_list.md``.
StrategyMode = Literal["snapshot", "anchors", "target"]

#: How a forced formal round derives its candidate from the trial rounds.
FormalRoundStrategy = Literal[
    "full_clone",
    "hybrid_params",
    "independent",
    "inherit_best_trial",
    "llm_propose",
]
