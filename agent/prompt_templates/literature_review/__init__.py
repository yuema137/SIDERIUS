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
from typing import Literal

from agent.schemas.literature_review import ConfidenceRubric, SynthesisConfig

# ---------------------------------------------------------------------------
# Synthesis omission-rule blocks (injected at the {OMISSION_RULE} placeholder
# in synthesis_system.md based on SynthesisConfig.transfer_tolerance). The omit
# *threshold* stays in ConfidenceRubric.omit_below; these blocks govern only how
# readily a cross-domain-but-transferable paper yields a finding.
# ---------------------------------------------------------------------------

_SYNTHESIS_OMISSION_STRICT = (
    "Omit a paper if you cannot construct a concrete, directly-applicable "
    "implication. Cross-domain papers with fundamental domain differences "
    "should be omitted."
)

_SYNTHESIS_OMISSION_MODERATE = (
    "Generate a finding if you can construct a concrete implication, even for "
    "cross-domain papers — provided the Adaptation section explicitly states "
    "what transfer assumptions are required. A finding with a clear caveat is "
    "more valuable than no finding at all. Omit only if no plausible mechanism "
    "transfer exists whatsoever."
)

_SYNTHESIS_OMISSION_LIBERAL = (
    "Generate a finding for any paper with a potentially relevant technique, "
    "even if the domain transfer is speculative. The Adaptation section must "
    "honestly flag transfer uncertainty. Let the proposer decide relevance."
)

_SYNTHESIS_OMISSION_RULES: dict[str, str] = {
    "strict": _SYNTHESIS_OMISSION_STRICT,
    "moderate": _SYNTHESIS_OMISSION_MODERATE,
    "liberal": _SYNTHESIS_OMISSION_LIBERAL,
}

# ---------------------------------------------------------------------------
# Synthesis content-format blocks (injected at the {CONTENT_FORMAT_BLOCK}
# placeholder in synthesis_system.md based on findings_verbosity). Kept here so
# the .md template stays neutral and a future verbosity level only needs a new
# block, not a template rewrite.
# ---------------------------------------------------------------------------

_SYNTHESIS_CONTENT_FORMAT_V1 = """Produce EXACTLY this shape (the three separate keys per finding plus
structured `content`):

  {"findings": [
     {"content": "**Implication:** Given the high-frequency-overfitting bottleneck, try a wider dilation schedule for the convolutional decoder.\\n**Mechanism:** WaveNet's dilated causal convolutions widen the receptive field exponentially without extra depth, applied across the full 1-D signal in a single model.\\n**Adaptation:** Replace the current encoder\'s fixed-dilation convs with dilation powers of 2 to cover the high-frequency band without scaling parameters.\\n(rationale: single full-spectrum paper, not yet replicated here.)",
      "cite_id": "arxiv:2406.04378",
      "confidence": <a number assigned per the Confidence rubric below>}
  ]}

`content` format — structured three-part Markdown. Each item\'s `content` MUST
be three labeled parts in this exact order, separated by newlines, followed by
a closing rationale line:

- **Implication:** name the specific current bottleneck (or key finding) it
  addresses, and the concrete thing to try next. Ground every implication in
  one of the listed bottlenecks. NOT "Paper X proposes dilated convolutions",
  but "Given the high-frequency-overfitting bottleneck, Paper X\'s
  receptive-field control suggests a wider dilation schedule." (≤ 40 words)
- **Mechanism:** the specific architectural / loss / training mechanism from
  the paper that supplies the implication — name layers, operations, or loss
  terms concretely. Carry over any training-regime qualifier (e.g. "under
  frequency-split training") and never present a regime-specific result as
  general. (≤ 80 words)
- **Adaptation:** how to bridge from the paper\'s domain/setup to the agent\'s
  task (full-spectrum 1-D SQUID denoising). State a concrete adaptation step
  or flag a transfer caveat. (≤ 50 words)

After the three parts, end with `(rationale: <one line justifying the
confidence per the rubric>)` on its own line.

Use the heading text verbatim — `**Implication:**`, `**Mechanism:**`,
`**Adaptation:**` — so downstream parsing stays trivial. Do NOT write the
paper id inside `content`; the id belongs ONLY in `cite_id`."""

_SYNTHESIS_CONTENT_FORMAT_V0 = """Produce EXACTLY this shape (note the three separate keys per finding):

  {"findings": [
     {"content": "Given the high-frequency-overfitting bottleneck, WaveNet\'s dilated causal convolutions widen the receptive field without extra depth — try a wider dilation schedule. (rationale: single full-spectrum paper, not yet replicated here.)",
      "cite_id": "arxiv:2406.04378",
      "confidence": <a number assigned per the Confidence rubric below>}
  ]}

`content` format — every item MUST:
- Name the specific current bottleneck (or key finding) it addresses.
- State the concrete implication for what to try next. NOT "Paper X proposes
  dilated convolutions", but "Given the high-frequency-overfitting bottleneck,
  Paper X\'s dilated-convolution receptive-field control suggests a wider
  dilation schedule."
- End with a one-line rationale in parentheses justifying the `confidence` score.
- Carry over any training-regime qualifier from the paper (e.g. "under
  frequency-split training"); never present a regime-specific result as general.
- Do NOT write the paper id inside `content`; the id belongs ONLY in `cite_id`."""

_SYNTHESIS_CONTENT_FORMAT_BLOCKS: dict[int, str] = {
    0: _SYNTHESIS_CONTENT_FORMAT_V0,
    1: _SYNTHESIS_CONTENT_FORMAT_V1,
}

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

# ---------------------------------------------------------------------------
# Paper-extract per-tier instruction blocks (injected at {EXTRACTION_INSTRUCTIONS}
# in paper_extract_system.md). One block per ``PaperExtract.extraction_method``
# value — the template stays neutral; each tier carries its own source-quality
# / equation / pseudocode guidance.
# ---------------------------------------------------------------------------

_PAPER_EXTRACT_INSTRUCTIONS_ARXIV = """## Extraction (clean arXiv .tex / Markdown source)

The text below is **clean LaTeX / Markdown extracted from the arXiv source** —
math symbols are correct, sub / superscripts intact, equations and algorithm
blocks preserved. Treat this as ground truth:

- Extract the paper's key equations DIRECTLY into `key_equations_md`. Use
  `$$...$$` for display math and `$...$` for inline. Preserve the original
  LaTeX where it is clean; do not paraphrase equations as prose.
- Extract algorithm / pseudocode blocks DIRECTLY into `pseudocode_md`, using
  fenced Markdown (e.g. ```python ... ``` or ```algorithm ... ```).
- Use prose only to introduce or contextualise an equation, never to substitute
  for it. The equation IS the contribution; the proposer needs the formula.
- The author affiliations / footnotes / bibliography that may appear in the
  raw `.tex` are noise — ignore them."""

_PAPER_EXTRACT_INSTRUCTIONS_PDFPLUMBER = """## Reading degraded PDF text

The text below is extracted from a PDF via pdfplumber and is **imperfect**. You
MUST read through these artifacts and never reproduce them in your output:

- Glyph codes such as `(cid:88)` or `(cid:16)` — these are unmapped font symbols
  (often math operators like the summation sign). Ignore them; never copy them.
- Run-together words with missing spaces (e.g. "dilatedcausalconvolutions") —
  read them as the intended separate words.
- A rotated arXiv margin stamp that extracts as garbled text (e.g.
  "5202 tcO 82 ]GL.sc[ ..."). Ignore it.
- Author affiliations, email addresses, and table-of-contents regions with
  dot-leaders ("` . . . . . `"). Ignore all of these.

## Mathematics (degraded source)

Equations extract poorly from this source. **Describe** important mathematical
methods in plain prose first (e.g. "the denoising score is a log-ratio of
signal-band to noise-band power"). Then, ONLY when the equation's structure is
clear enough to be useful, emit an approximate LaTeX form in
`key_equations_md`. If a paper's equations cannot be reliably reconstructed,
leave `key_equations_md=""` — degraded LaTeX is worse than no LaTeX.

Pseudocode blocks may survive partially. If you can identify them, put a
best-effort Markdown version in `pseudocode_md`; otherwise leave `""`.

Downstream consumers see `extraction_method="pdfplumber_llm"` and weight these
two fields as approximate / lower-reliability."""

_PAPER_EXTRACT_INSTRUCTIONS_ABSTRACT = """## Abstract-only input

You have access to **only the paper's abstract** — no full text. Fill the prose
fields (`title`, `authors`, `year`, `core_idea`, `architecture_details`,
`key_results`, `relevance_to_task`) at the level of detail the abstract
supports. Leave `key_equations_md` and `pseudocode_md` as `""` — abstracts do
not contain extractable equations or pseudocode."""

_PAPER_EXTRACT_INSTRUCTIONS: dict[str, str] = {
    "arxiv_source": _PAPER_EXTRACT_INSTRUCTIONS_ARXIV,
    "pdfplumber_llm": _PAPER_EXTRACT_INSTRUCTIONS_PDFPLUMBER,
    "abstract_only": _PAPER_EXTRACT_INSTRUCTIONS_ABSTRACT,
}


def load_prompt(filename: str) -> str:
    """Load a prompt template from this directory."""
    path = os.path.join(_PROMPT_DIR, filename)
    with open(path, encoding="utf-8") as f:
        return f.read()


def render_paper_extract_prompt(
    raw_text: str,
    extraction_method: Literal[
        "arxiv_source", "pdfplumber_llm", "abstract_only"
    ] = "pdfplumber_llm",
    task_description: str = SIDERIUS_TASK,
) -> tuple[str, str]:
    """Build the (system, user) prompt pair for compressing one paper.

    Args:
        raw_text:          The paper's full extracted text. Truncated to
                           ``MAX_RAW_TEXT_CHARS`` (with a trailing marker)
                           before injection — the bridge does not enforce any cap.
        extraction_method: Which extraction tier produced ``raw_text``. Selects
                           the per-tier instruction block injected at the
                           ``{EXTRACTION_INSTRUCTIONS}`` placeholder. Default
                           ``"pdfplumber_llm"`` matches the Tier-2 fallback;
                           callers (the lit-review node) pass the actual tier
                           explicitly based on the skill's ``extraction_method``.
        task_description:  Concrete downstream task the proposer works on, used
                           to ground ``relevance_to_task``. Defaults to
                           ``SIDERIUS_TASK``.

    Returns:
        ``(system_prompt, user_prompt)``. The system prompt instructs the LLM to
        emit a 9-key JSON object matching ``PaperExtract``'s LLM-emitted fields
        (``extraction_method`` is set node-side, not by the LLM). Feed straight
        into ``LLMBridge.generate(system, user)``, which returns the parsed dict
        for ``PaperExtract.model_validate``.
    """
    instructions = _PAPER_EXTRACT_INSTRUCTIONS[extraction_method]
    system_prompt = (
        load_prompt("paper_extract_system.md")
        .replace("{TASK_DESCRIPTION}", task_description)
        .replace("{EXTRACTION_INSTRUCTIONS}", instructions)
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
    findings_verbosity: Literal[0, 1] = 1,
    synthesis_config: SynthesisConfig | None = None,
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

    ``findings_verbosity`` (default 1) selects the content-format block injected
    at ``{CONTENT_FORMAT_BLOCK}``. 1 = structured three-part Markdown
    (Implication / Mechanism / Adaptation + closing rationale); 0 = the
    single-paragraph backward-compat format. Only the prompt format changes;
    ``ExpertContextItem.content`` is still a single string either way.

    ``synthesis_config`` (default = the standard ``SynthesisConfig``,
    ``transfer_tolerance="moderate"``) selects the ``{OMISSION_RULE}`` block.
    'strict' omits cross-domain papers; 'moderate' emits a finding for a
    transferable cross-domain mechanism with an explicit Adaptation caveat;
    'liberal' emits for any potentially relevant technique.
    """
    rubric = confidence_rubric or ConfidenceRubric()
    syn_cfg = synthesis_config or SynthesisConfig()
    content_format = _SYNTHESIS_CONTENT_FORMAT_BLOCKS[findings_verbosity]
    omission_rule = _SYNTHESIS_OMISSION_RULES[syn_cfg.transfer_tolerance]
    system_prompt = (
        load_prompt("synthesis_system.md")
        .replace("{TASK_DESCRIPTION}", task_description)
        .replace("{CONFIDENCE_RUBRIC}", rubric.render())
        .replace("{CONTENT_FORMAT_BLOCK}", content_format)
        .replace("{OMISSION_RULE}", omission_rule)
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
