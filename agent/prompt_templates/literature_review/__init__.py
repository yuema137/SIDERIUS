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

from agent.schemas.literature_review import ConfidenceRubric

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


def _bullets(items: list[str]) -> str:
    """Render a list of strings as markdown bullets, or '(none)' when empty."""
    cleaned = [s.strip() for s in (items or []) if s and s.strip()]
    if not cleaned:
        return "(none)"
    return "\n".join(f"- {s}" for s in cleaned)


def render_search_decision_prompt(
    *,
    key_findings: list[str],
    bottlenecks: list[str],
    take_home_message: str,
    explored_models: list[str],
    papers_seen: list[dict],
    escalation_allowed: bool,
    prior_search_results: list[tuple[str, int]] | None = None,
    task_description: str = SIDERIUS_TASK,
) -> tuple[str, str]:
    """Build the (system, user) prompt for one dynamic-search-loop decision.

    The LLM returns one JSON action — ``search`` | ``escalate`` | ``done``.
    Keyword-only so the node passes already-extracted primitives (the prompt
    module stays free of schema coupling — it only formats strings).

    Args:
        key_findings/bottlenecks/take_home_message: pulled from the
            InterpretationOutput; key_findings + bottlenecks are the primary
            grounding signal for query generation (Checkpoint C).
        explored_models: model_types already tried — steers away from
            rediscovering known architectures.
        papers_seen: list of ``{paper_id, title, year, verbosity_achieved,
            snippet}`` for the papers retrieved so far (the escalation menu).
        escalation_allowed: when False, the prompt tells the LLM to choose
            ``search`` or ``done`` only.
        prior_search_results: ``(query, hit_count)`` for each search already run
            this run. Fed back so the LLM self-corrects — a 0-hit query is
            flagged "too specific" and the LLM is nudged to broaden. Omitted on
            the first round.
    """
    system_prompt = load_prompt("search_decision_system.md").replace(
        "{TASK_DESCRIPTION}", task_description
    )

    explored = ", ".join(m for m in (explored_models or []) if m) or "(none recorded)"

    prior_block = ""
    if prior_search_results:
        lines = ["## Queries already tried this run"]
        any_zero = False
        for query, hits in prior_search_results:
            lines.append(f'- "{query}" → {hits} hits')
            if hits == 0:
                lines.append("  (too specific — try broader terms for the same concept)")
                any_zero = True
        if any_zero:
            lines.append(
                "\nA query that returned 0 hits was too narrow or off-vocabulary — "
                "broaden it or try different keywords; do NOT repeat a 0-hit query."
            )
        prior_block = "\n".join(lines) + "\n\n"

    if papers_seen:
        lines = []
        for p in papers_seen:
            snippet = (p.get("snippet") or "").strip()
            lines.append(
                f"- [{p.get('paper_id', '?')}] (v{p.get('verbosity_achieved', 0)}) "
                f"{p.get('title') or '(untitled)'} ({p.get('year') or 'n.d.'})"
                + (f" — {snippet}" if snippet else "")
            )
        papers_block = "\n".join(lines)
    else:
        papers_block = "None yet — this is the first round."

    escalation_note = (
        ""
        if escalation_allowed
        else '\nEscalation is DISABLED this run — choose "search" or "done" only.\n'
    )

    user_prompt = (
        "## Current experiment state\n\n"
        f"Models already explored (do not rediscover): {explored}\n\n"
        f"Key findings so far:\n{_bullets(key_findings)}\n\n"
        f"Open bottlenecks:\n{_bullets(bottlenecks)}\n\n"
        f"Take-home message: {take_home_message or '(none)'}\n\n"
        f"{prior_block}"
        "## Papers retrieved so far this run\n"
        f"{papers_block}\n"
        f"{escalation_note}\n"
        "Decide the single best next action as one JSON object."
    )
    return system_prompt, user_prompt


def render_synthesis_prompt(
    *,
    key_findings: list[str],
    bottlenecks: list[str],
    take_home_message: str,
    papers: list[dict],
    confidence_rubric: ConfidenceRubric | None = None,
    task_description: str = SIDERIUS_TASK,
) -> tuple[str, str]:
    """Build the (system, user) prompt for the final findings synthesis.

    The LLM emits ``{"findings": [{content, cite_id, confidence}]}``. The node
    wraps each into an ``ExpertContextItem``. ``papers`` is a list of
    ``{paper_id, title, year, summary}`` where ``summary`` is the compressed
    extract (preferred) or the abstract.

    ``confidence_rubric`` (default = the standard ``ConfidenceRubric``) is the
    single source of confidence semantics; its rendered form is injected into
    the ``{CONFIDENCE_RUBRIC}`` placeholder. The ``.md`` template carries no
    numeric thresholds — see "Scoring and rubric design invariants" in
    docs/external_agents_architecture.md.
    """
    rubric = confidence_rubric or ConfidenceRubric()
    system_prompt = (
        load_prompt("synthesis_system.md")
        .replace("{TASK_DESCRIPTION}", task_description)
        .replace("{CONFIDENCE_RUBRIC}", rubric.render())
    )

    if papers:
        blocks = []
        for p in papers:
            summary = (p.get("summary") or "").strip() or "(no extract or abstract available)"
            blocks.append(
                f"### [{p.get('paper_id', '?')}] {p.get('title') or '(untitled)'} "
                f"({p.get('year') or 'n.d.'})\n{summary}"
            )
        papers_block = "\n\n".join(blocks)
    else:
        papers_block = "(no papers were retrieved this run)"

    user_prompt = (
        "## Current experiment state (PRIMARY — ground every finding in these)\n\n"
        f"Open bottlenecks:\n{_bullets(bottlenecks)}\n\n"
        f"Key findings:\n{_bullets(key_findings)}\n\n"
        f"Take-home message: {take_home_message or '(none)'}\n\n"
        "## Papers retrieved this iteration\n\n"
        f"{papers_block}\n\n"
        "Produce the findings JSON. Omit any paper that does not address one of "
        "the bottlenecks above."
    )
    return system_prompt, user_prompt
