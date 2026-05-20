"""Shared test helpers for ml_model_proposal_agent prompt inspection.

The pipeline stage user prompt is now a markdown + JSON hybrid (see
``nodes.ml_model_proposal_agent._render_stage_user_prompt``):

    ## Candidate Models — detailed view
    ...  (per-candidate rendered_markdown + source code)
    ---

    ## Accumulated context

    ```json
    {...}
    ```

    (optional) agent cards / expert context / vocabulary blocks

Tests that introspect the ``accumulated`` dict need to pull the JSON
payload out of the fenced block. The old ``split("\\n\\n")[0]`` trick no
longer works because the prompt no longer starts with raw JSON.
"""

from __future__ import annotations

import json
from typing import Any, Dict


def extract_accumulated_json(user_prompt: str) -> dict[str, Any]:
    """Parse the ``## Accumulated context`` JSON fence from a stage prompt.

    Raises ``ValueError`` when the expected fence is missing or
    unterminated — making prompt-format regressions fail loudly rather
    than silently returning ``{}``.
    """
    marker = "```json\n"
    start = user_prompt.find(marker)
    if start < 0:
        raise ValueError(
            "No ```json fence found in stage user prompt — has the prompt format changed?"
        )
    start += len(marker)
    end = user_prompt.find("\n```", start)
    if end < 0:
        raise ValueError("Unterminated ```json fence in stage user prompt")
    return json.loads(user_prompt[start:end])
