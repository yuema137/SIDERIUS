# agent/prompt_templates/literature_review/__init__.py
"""
Prompt templates for the ml_literature_review node's paper-compression step.

The compression prompt turns one paper's full extracted text into a
``PaperExtract`` (agent/schemas/literature_review.py) — the verbosity-1 view a
model-proposing agent reads instead of the source paper.

The system prompt is stored as a ``.md`` template in this directory
(``paper_extract_system.md``) with a single ``{TASK_DESCRIPTION}`` placeholder,
matching the ``agent/prompt_templates/proposal`` convention (load + ``.replace``).
The user prompt is a trivial wrapper around the raw paper text and is built
inline.

Design decisions (see docs/commit_plan_ml_literature_review.md Commit 3 and
docs/paper_resolver_pilot.md findings F1-F4):
  - ``MAX_RAW_TEXT_CHARS`` caps the raw text injected into the user prompt.
    LLMBridge itself imposes NO length cap (it sends the prompt verbatim), so
    this guardrail lives here. 120k chars is ~30k tokens — roughly 1.6x the
    73.6k-char TIDMAD paper (F2) and well inside a 128k-token context window,
    leaving ample room for the system prompt and completion.
  - ``task_description`` is an optional parameter defaulting to ``SIDERIUS_TASK``
    so the same prompt generalises to other downstream tasks without a rewrite,
    while today's (raw_text)-only call site keeps working.
"""

import os

_PROMPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Maximum number of raw-text characters injected into the user prompt. Text
# beyond this is dropped and replaced with _TRUNCATION_MARKER. The bridge does
# not truncate, so this is the only guard against a pathological PDF blowing the
# context window / cost. ~30k tokens at 4 chars/token.
MAX_RAW_TEXT_CHARS = 120_000
_TRUNCATION_MARKER = "\n\n[...TRUNCATED...]"

# Default downstream task injected into the compression prompt's
# {TASK_DESCRIPTION} placeholder. Task-agnostic by parameter so the framework
# generalises beyond SQUID; this default describes the SIDERIUS denoising task.
SIDERIUS_TASK = (
    "full-spectrum 1-D time-series denoising of SQUID dark-matter\n"
    "detector data: map a noisy [B, T] integer signal to a clean\n"
    "[B, 256, T] reconstruction, trained across the whole frequency\n"
    "spectrum at once (not split into per-band models)."
)

_USER_PROMPT_TEMPLATE = (
    "Here is the full extracted text of one paper. Compress it into the JSON "
    "object described in the system instructions.\n\n"
    "--- BEGIN PAPER TEXT ---\n"
    "{RAW_TEXT}\n"
    "--- END PAPER TEXT ---\n"
)


def load_prompt(filename: str) -> str:
    """Load a prompt template from this directory."""
    path = os.path.join(_PROMPT_DIR, filename)
    with open(path, encoding="utf-8") as f:
        return f.read()


def render_paper_extract_prompt(
    raw_text: str,
    task_description: str = SIDERIUS_TASK,
) -> tuple[str, str]:
    """Build the (system, user) prompt pair for compressing one paper.

    Args:
        raw_text:         The paper's full extracted text. Truncated to
                          ``MAX_RAW_TEXT_CHARS`` (with a trailing marker) before
                          injection — the bridge does not enforce any cap.
        task_description: Concrete downstream task the proposer works on, used
                          to ground ``relevance_to_task``. Defaults to
                          ``SIDERIUS_TASK``.

    Returns:
        ``(system_prompt, user_prompt)``. The system prompt instructs the LLM to
        emit JSON matching ``PaperExtract``; the user prompt carries the (capped)
        raw text. Feed straight into ``LLMBridge.generate(system, user)``, which
        returns the parsed dict for ``PaperExtract.model_validate``.
    """
    system_prompt = load_prompt("paper_extract_system.md").replace(
        "{TASK_DESCRIPTION}", task_description
    )

    text = raw_text
    if len(text) > MAX_RAW_TEXT_CHARS:
        text = text[:MAX_RAW_TEXT_CHARS] + _TRUNCATION_MARKER

    user_prompt = _USER_PROMPT_TEMPLATE.replace("{RAW_TEXT}", text)
    return system_prompt, user_prompt
