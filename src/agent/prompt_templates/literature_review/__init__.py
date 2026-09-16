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
  - ``task_description`` is an optional parameter defaulting to ``""``.
    The lit-review node always passes its resolved task description
    (from ``LiteratureReviewInput.task_description``, sourced from the
    caller's task declaration); the default only fires for test
    callers that omit the kwarg, in which case the ``{TASK_DESCRIPTION}``
    placeholder is filled with empty string.
"""

import os
from typing import Any, Literal

from agent.schemas.literature_review import (
    ConfidenceRubric,
    LiteratureReviewOutput,
    RetrievedPaper,
    SynthesisConfig,
)
from agent.schemas.proposal import ExpertContextItem

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

_SYNTHESIS_CONTENT_FORMAT_V1 = """Produce EXACTLY this shape (the four separate keys per finding plus
structured `content`):

  {"findings": [
     {"content": "**Implication:** <one observed bottleneck and a conditional method to investigate>.\\n**Mechanism:** <the paper's source-backed method and its reported regime>.\\n**Adaptation:** <how the method might transfer to the declared task, with assumptions and caveats>.\\n(rationale: <why the cited evidence merits this confidence band>)",
      "source_ref": "<paper_id from the supplied paper block>",
      "content_paper_id": "<paper_id from the supplied paper block>",
      "confidence": <a number assigned per the Confidence rubric below>}
  ]}

`content` format — structured three-part Markdown. Each item's `content` MUST
be three labeled parts in this exact order, separated by newlines, followed by
a closing rationale line.

**Placement rule (LOCKED — do not violate):**

- **Mechanism = source-extracted content ONLY.** Everything in Mechanism is
  lifted from what the per-paper block above provides about the paper —
  architecture / loss / training-regime description, plus any equation or
  pseudocode block the per-paper context exposes. Mechanism contains NO
  LLM-added reasoning, NO speculation, NO task-transfer claims.
- **Adaptation = LLM reasoning on top.** Adaptation is where you write how
  to bridge from the paper's setup to the declared task. Adaptation MUST NOT contain raw equations
  from the source paper —
  those belong in Mechanism. Adaptation references the equation by
  describing the task-specific bridging step, not by re-quoting it.

The three labeled parts:

- **Implication:** name the specific current bottleneck (or key finding) it
  addresses, and the concrete thing to try next. Ground every implication in
  one of the listed bottlenecks. NOT "Paper X proposes a method",
  but "Given the observed bottleneck, the cited method suggests testing a
  particular intervention under its stated assumptions." (≤ 40 words)
- **Mechanism:** the specific architectural / loss / training mechanism from
  the paper — source content only. Quote it directly from the per-paper
  block you were given:
    * When the paper's `Extraction:` marker is `arxiv_source` AND the per-
      paper block contains a `Key equations (verbatim from source ...)`
      sub-block, quote at least one equation **verbatim** here — copy the
      LaTeX exactly as given, preserve `$$...$$` / `$...$` delimiters.
    * When the marker is `pdfplumber_llm`, the equation in the per-paper
      block is best-effort reconstruction from a degraded PDF. Paraphrase
      it in Mechanism and add an explicit flag like "approximate equation,
      reconstructed from a degraded PDF" — do NOT present it as ground
      truth.
    * When the per-paper block contains a `Pseudocode (verbatim from
      source ...)` sub-block AND the algorithm IS the mechanism (e.g.
      reweighting / scheduling / scale-targeting algorithms), reproduce
      the relevant 3-8 lines as a fenced code block inside Mechanism.
      Otherwise just name the algorithm in prose.
    * When the marker is `abstract_only`, the per-paper block carries no
      equations or pseudocode — describe the mechanism in prose only.
    * Carry over any training-regime qualifier and never present a
      regime-specific result as general.
  (≤ 80 words; the equation LaTeX itself does not count toward the cap.)
- **Adaptation:** how to bridge from the paper's domain/setup to the declared
  task. LLM reasoning on top of the
  Mechanism. State a concrete adaptation step or flag a transfer caveat.
  **MUST NOT contain raw equations from the source paper** — those belong
  in Mechanism. Reference equations by their effect, not by re-quoting.
  (≤ 50 words)

After the three parts, end with `(rationale: <one line justifying the
confidence per the rubric>)` on its own line.

Use the heading text verbatim — `**Implication:**`, `**Mechanism:**`,
`**Adaptation:**` — so downstream parsing stays trivial. Do NOT write the
paper id inside `content`; the id belongs ONLY in `source_ref`."""

_SYNTHESIS_CONTENT_FORMAT_V0 = """Produce EXACTLY this shape (note the four separate keys per finding):

  {"findings": [
     {"content": "Given <observed bottleneck>, <cited method> suggests <conditional intervention> if its assumptions hold for the declared task. (rationale: <source support and transfer caveat>)",
      "source_ref": "<paper_id from the supplied paper block>",
      "content_paper_id": "<paper_id from the supplied paper block>",
      "confidence": <a number assigned per the Confidence rubric below>}
  ]}

`content` format — every item MUST:
- Name the specific current bottleneck (or key finding) it addresses.
- State the concrete implication for what to try next. NOT "Paper X proposes
  a method", but "Given the observed bottleneck, the cited method suggests
  testing an intervention under its stated assumptions."
- End with a one-line rationale in parentheses justifying the `confidence` score.
- Carry over any training-regime qualifier from the paper; never present a
  regime-specific result as general.
- Do NOT write the paper id inside `content`; the id belongs ONLY in `source_ref`
  and `content_paper_id` (both must hold the same paper_id — see Hard rules
  in the system prompt)."""

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
methods in plain prose first (e.g. "the reported objective is a ratio of
signal and background power"). Then, ONLY when the equation's structure is
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
    task_description: str = "",
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
                           to ground ``relevance_to_task``. Defaults to ``""``;
                           the lit-review node passes its resolved value from
                           ``inp.task_description``.

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


# Fix 5 (Commit 6.5b-4): the four query-generation dimensions the
# search-decision LLM must cover across a run (see
# search_decision_system.md's "## Query generation — four dimensions to
# cover"). Exported so the node can parse the LLM's self-reported
# dimension label out of `reasoning` and surface a coverage-distribution
# line back to the LLM next round. Trusted labels (no parser-enforced
# contract — Open Q1 resolution, 2026-06-12); a missing label is itself
# a diagnostic signal that Fix 5 is incomplete.
DIMENSION_LABELS: tuple[str, ...] = (
    "bottleneck",
    "take_home",
    "architectural_gap",
    "adjacent_technique",
)


def render_search_decision_prompt(
    *,
    key_findings: list[str],
    bottlenecks: list[str],
    take_home_message: str,
    explored_models: list[str],
    papers_seen: list[dict],
    escalation_allowed: bool,
    prior_search_results: list[tuple[str, int]] | None = None,
    prior_escalation_results: list[tuple[str, str, str]] | None = None,
    dimension_counts: dict[str, int] | None = None,
    task_description: str = "",
    confidence_rubric: ConfidenceRubric | None = None,
    data_analysis_context: str = "",
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
        prior_escalation_results: ``(paper_id, status, reasoning)`` for each
            escalation attempted so far this run. ``status`` is one of ``"ok"``
            (deep-read succeeded), ``"noop"`` (paper was already at the
            requested verbosity, or the fetch returned no new content), or
            ``"error"`` (resolve call failed). Rendered as a sub-block
            parallel to ``prior_search_results`` so the LLM stops
            re-escalating papers whose last attempt was a no-op or error.
            Omitted on the first round.
        dimension_counts: per-dimension query coverage tally — keys come
            from ``DIMENSION_LABELS`` (``bottleneck`` / ``take_home`` /
            ``architectural_gap`` / ``adjacent_technique``), values are
            the count of search queries that targeted each dimension so
            far this run. When non-None and non-empty, a coverage
            distribution line is rendered inside the
            ``## Queries already tried this run`` block so the LLM can
            spread its remaining queries across uncovered dimensions.
            Trusted self-reporting from the LLM's ``reasoning`` field;
            no parser-enforced contract. Omitted on the first round.
        confidence_rubric: optional ``ConfidenceRubric`` to render into the
            ``{CONFIDENCE_RUBRIC_FOR_SEARCH}`` placeholder. When ``None``
            (default), the default rubric is instantiated. Lets the
            search-decision LLM reason about verbosity → confidence-band →
            escalation payoff — see ``search_decision_system.md``'s
            "## Why escalation matters for finding confidence" section.
    """
    system_prompt = (
        load_prompt("search_decision_system.md")
        .replace("{TASK_DESCRIPTION}", task_description)
        .replace(
            "{CONFIDENCE_RUBRIC_FOR_SEARCH}",
            (confidence_rubric or ConfidenceRubric()).render_for_searcher(),
        )
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
        # Fix 5 (Commit 6.5b-4): render coverage distribution AFTER the
        # per-query lines so the LLM sees which dimensions it has and
        # hasn't targeted. Skipped when dimension_counts is None/empty
        # (e.g. first round, or all labels unparseable).
        if dimension_counts:
            counts_str = ", ".join(
                f"{label}={dimension_counts.get(label, 0)}" for label in DIMENSION_LABELS
            )
            lines.append(f"\nCoverage so far: {counts_str}.")
        if any_zero:
            lines.append(
                "\nA query that returned 0 hits was too narrow or off-vocabulary — "
                "broaden it or try different keywords; do NOT repeat a 0-hit query."
            )
        prior_block = "\n".join(lines) + "\n\n"

    # Fix 3 (Commit 6.5b-2): render prior-escalation feedback as a top-level
    # sub-block parallel to "## Queries already tried this run". Placed just
    # above the papers block so the LLM sees recent escalation outcomes in
    # the context of which papers they apply to.
    escalation_history_block = ""
    if prior_escalation_results:
        _STATUS_LABEL = {
            "ok": "success — paper now deep-read",
            "noop": "no-change — paper was already at the requested verbosity OR fetch returned no new content",
            "error": "error — resolve call failed; do not retry this paper",
        }
        lines = ["## Escalations already attempted this run"]
        for pid, status, reasoning in prior_escalation_results:
            label = _STATUS_LABEL.get(status, f"unknown status: {status}")
            excerpt = (reasoning or "").strip().replace("\n", " ")
            if len(excerpt) > 200:
                excerpt = excerpt[:200] + "…"
            lines.append(f'- [{pid}] {label} (your reasoning: "{excerpt}")')
        lines.append(
            "\nDo NOT re-escalate a paper whose last status was 'no-change' or "
            "'error' — pick a different paper, search for a new one, or stop."
        )
        escalation_history_block = "\n".join(lines) + "\n\n"

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
        f"{data_analysis_context}"
        f"{prior_block}"
        f"{escalation_history_block}"
        "## Papers retrieved so far this run\n"
        f"{papers_block}\n"
        f"{escalation_note}\n"
        "Decide the single best next action as one JSON object."
    )
    return system_prompt, user_prompt


# ---------------------------------------------------------------------------
# Synthesis per-paper-block formatter (Commit 2d).
#
# Each retrieved paper renders as one block inside the synthesis user prompt.
# The block carries:
#   - citation header (paper_id, title, year)
#   - extraction-tier marker so the LLM knows whether to quote verbatim
#     (Tier 1) or paraphrase with a flag (Tier 2)
#   - the prose summary (architecture / results / relevance)
#   - the verbatim ``key_equations_md`` block (when non-empty)
#   - the verbatim ``pseudocode_md`` block (when non-empty)
#
# The synthesis LLM lifts equations / pseudocode out of the labeled blocks
# directly into the finding's **Mechanism** section — see
# ``_SYNTHESIS_CONTENT_FORMAT_V1`` for the placement rule (Mechanism =
# source-extracted content; Adaptation = LLM reasoning on top, never raw
# equations from source).
# ---------------------------------------------------------------------------

# Per-tier marker shown in each paper block. The phrasing tells the LLM
# *how* to quote when it lifts the equation into Mechanism. abstract-only
# papers carry no equations, so the marker says so explicitly.
_SYNTHESIS_EXTRACTION_MARKERS: dict[str, str] = {
    "arxiv_source": "arxiv_source (Tier 1 — ground-truth LaTeX; quote equations verbatim)",
    "pdfplumber_llm": (
        "pdfplumber_llm (Tier 2 — degraded PDF; paraphrase equations and flag as approximate)"
    ),
    "abstract_only": "abstract_only (no full text — no equations or pseudocode to quote)",
}

# Per-tier label that precedes the verbatim ``key_equations_md`` block.
# Tier 1 carries ground-truth LaTeX (quote verbatim); Tier 2 is best-effort
# reconstruction (the LLM must paraphrase + flag when lifting it into
# Mechanism). For ``abstract_only`` the block is skipped entirely because
# the field is empty by extraction contract.
_SYNTHESIS_EQUATION_HEADERS: dict[str, str] = {
    "arxiv_source": "Key equations (verbatim from source — quote as-is in Mechanism)",
    "pdfplumber_llm": (
        "Key equations (best-effort reconstruction from degraded PDF — paraphrase + "
        "flag as approximate when lifting into Mechanism)"
    ),
    "abstract_only": "Key equations",
}

_SYNTHESIS_PSEUDOCODE_HEADERS: dict[str, str] = {
    "arxiv_source": "Pseudocode (verbatim from source — reproduce as-is when the algorithm IS the mechanism)",
    "pdfplumber_llm": (
        "Pseudocode (best-effort reconstruction from degraded PDF — reproduce as-is "
        "but flag as approximate)"
    ),
    "abstract_only": "Pseudocode",
}


def _render_synthesis_paper_block(p: dict) -> str:
    """Render one per-paper block for the synthesis user prompt.

    See the module-level comment above for the structure and the lift-into-
    Mechanism contract. Skips the equation / pseudocode sub-blocks when the
    corresponding field is empty; the LLM doesn't need to be told something
    is missing — the absence is the signal.
    """
    paper_id = p.get("paper_id", "?")
    title = p.get("title") or "(untitled)"
    year = p.get("year") or "n.d."
    summary = (p.get("summary") or "").strip() or "(no extract or abstract available)"
    method = p.get("extraction_method") or "abstract_only"
    marker = _SYNTHESIS_EXTRACTION_MARKERS.get(method, method)

    lines = [
        f"### {title} ({year})",
        f"**source_ref / content_paper_id (use this exact string for both):** `{paper_id}`",
        f"Extraction: {marker}",
        "",
        summary,
    ]

    key_equations = (p.get("key_equations_md") or "").strip()
    if key_equations:
        header = _SYNTHESIS_EQUATION_HEADERS.get(method, "Key equations")
        lines += ["", f"{header}:", key_equations]

    pseudocode = (p.get("pseudocode_md") or "").strip()
    if pseudocode:
        header = _SYNTHESIS_PSEUDOCODE_HEADERS.get(method, "Pseudocode")
        lines += ["", f"{header}:", pseudocode]

    return "\n".join(lines)


def render_synthesis_prompt(
    *,
    key_findings: list[str],
    bottlenecks: list[str],
    take_home_message: str,
    papers: list[dict],
    confidence_rubric: ConfidenceRubric | None = None,
    findings_verbosity: Literal[0, 1] = 1,
    synthesis_config: SynthesisConfig | None = None,
    task_description: str = "",
    data_analysis_context: str = "",
) -> tuple[str, str]:
    """Build the (system, user) prompt for the final findings synthesis.

    The LLM emits ``{"findings": [{content, source_ref, confidence}]}``. The node
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

    Empty-bottlenecks (cold-start) render — issue #303: when ``bottlenecks``
    is empty after ``_bullets``' whitespace cleaning (the list renders as
    ``(none)``), the closing instruction switches from the bottleneck-omission
    rule — which, against an empty list, would instruct omitting EVERY
    paper — to grounding on the task description. The branch keys on the
    RENDERED block (``== "(none)"``), never on a separate emptiness
    predicate, so the instruction can never contradict what the prompt
    shows. Non-empty renders are byte-identical to the pre-#303 prompt
    (pinned by the PB-9 user-prompt golden).
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
        blocks = [_render_synthesis_paper_block(p) for p in papers]
        papers_block = "\n\n".join(blocks)
    else:
        papers_block = "(no papers were retrieved this run)"

    bottlenecks_block = _bullets(bottlenecks)
    if bottlenecks_block == "(none)":
        # Cold-start branch (issue #303): with zero bottlenecks the legacy
        # closing line would instruct omitting every paper ("omit any paper
        # that does not address one of the bottlenecks above" — and there
        # are none). Redirect the grounding to the task description, which
        # the system prompt carries under "The task the proposer is working
        # on". Keyed on the rendered block so the instruction and the list
        # it points at can never disagree.
        closing_instruction = (
            "Produce the findings JSON. No open bottlenecks are recorded yet — "
            "ground each finding in the task described in the system prompt "
            "('The task the proposer is working on') instead, and omit any "
            "paper that is not relevant to that task."
        )
    else:
        closing_instruction = (
            "Produce the findings JSON. Omit any paper that does not address one of "
            "the bottlenecks above."
        )

    user_prompt = (
        "## Current experiment state (PRIMARY — ground every finding in these)\n\n"
        f"Open bottlenecks:\n{bottlenecks_block}\n\n"
        f"Key findings:\n{_bullets(key_findings)}\n\n"
        f"Take-home message: {take_home_message or '(none)'}\n\n"
        f"{data_analysis_context}"
        "## Papers retrieved this iteration\n\n"
        f"{papers_block}\n\n"
        f"{closing_instruction}"
    )
    return system_prompt, user_prompt


def render_data_analysis_context(evidence) -> str:
    """Render bounded observed-data evidence without turning it into authority."""

    if evidence is None:
        return ""
    if hasattr(evidence, "model_dump"):
        evidence = evidence.model_dump(mode="json")
    lines = [
        "## Observations measured by Data Analysis",
        f"Report {evidence['report_id']}: {evidence['executive_summary']}",
    ]
    for finding in evidence.get("findings", []):
        lines.append(f"- [{finding['confidence_level']} confidence] {finding['statement']}")
        lines.append(f"  Modeling relevance: {finding['modeling_relevance']}")
        for measurement in finding.get("measurements", []):
            unit = f" {measurement['unit']}" if measurement.get("unit") else ""
            lines.append(
                f"  Measurement {measurement['result_key']}: "
                f"{measurement.get('value')}{unit} ({measurement['description']})"
            )
    for limitation in evidence.get("limitations", []):
        lines.append(f"- Measurement limitation: {limitation}")
    for question in evidence.get("unresolved_questions", []):
        lines.append(f"- Unresolved measured-data question: {question}")
    lines.append(
        "Use these as observations that may motivate searches. Do not claim that a cited "
        "paper validated this specific dataset, and do not treat this context as data access."
    )
    return "\n".join(lines) + "\n\n"


# ---------------------------------------------------------------------------
# render_review_report — deterministic Markdown view of a LiteratureReviewOutput.
#
# Pure function: no LLM, no I/O, no time-of-day; deterministic from its input.
# Used as the canonical artifact for §10 Checkpoints E + F (extraction quality
# review) and as a human-facing report for production runs. The caller is
# responsible for writing the returned string to disk.
#
# The renderer accepts the validated ``LiteratureReviewOutput`` whole — single
# source of truth per CLAUDE.md, future-proof against new output fields.
#
# Trust signals (the §10 contract): every retrieved paper carries a single
# ``extraction_method`` badge in its metadata table and, for the lower-tier
# ``pdfplumber_llm`` source, a callout blockquote and per-section italic
# caveats. ``arxiv_source`` papers carry the same badge with a ✅ marker so the
# tier is visible without reading the prose. The phrasing is fixed across all
# reports so reviewers can grep / search consistently.
# ---------------------------------------------------------------------------

# Extraction-tier badge — fixed across all reports for grep-ability.
# Wording matches the §10 acceptance criteria in external_agents_for_proposer.md
# and the schema docstring on PaperExtract.extraction_method.
_EXTRACTION_BADGES: dict[str, str] = {
    "arxiv_source": "✅ `arxiv_source` (Tier 1 — clean LaTeX from arXiv source)",
    "pdfplumber_llm": "⚠️ `pdfplumber_llm` (Tier 2 — degraded PDF text, LLM-reconstructed)",
    "abstract_only": "⚪ `abstract_only` (no full text retrieved; abstract only)",
}

# Per-section caveat appended to `Key equations` / `Pseudocode` headings when
# the source is degraded. Empty string for trustworthy tiers so the heading
# stays clean. ``abstract_only`` should never reach an equations / pseudocode
# render path (the compression prompt instructs the LLM to leave both empty
# for that tier) but we keep an entry for completeness.
_TIER_CAVEAT_PER_SECTION: dict[str, str] = {
    "arxiv_source": "",
    "pdfplumber_llm": " *(reconstructed from degraded PDF — verify against source)*",
    "abstract_only": "",
}

# Tier-2 blockquote callout — rendered immediately under the metadata table
# for ``pdfplumber_llm`` papers. Tier 1 and abstract-only papers don't get one.
_TIER2_TRUST_CALLOUT = (
    "> ⚠️ **Trust note — Tier 2 source.** This paper has no arXiv `.tex` "
    "source, so the full text came from `pdfplumber` on the PDF. The "
    "compression LLM reconstructed equations and pseudocode from degraded "
    "glyphs. Prose fields (`core_idea`, `architecture_details`, `key_results`, "
    "`relevance_to_task`) are generally reliable; `key_equations_md` and "
    "`pseudocode_md` below are best-effort and must be verified against the "
    "source PDF before use."
)

# Confidence band labels — derived from the default ConfidenceRubric thresholds
# (0.80 / 0.60 / 0.40). Runs that override the rubric may map numbers to
# different evidence criteria; the summary banner footnote tells the reader.
_CONFIDENCE_BAND_THRESHOLDS: list[tuple[float, str]] = [
    (0.80, "high"),
    (0.60, "moderate"),
    (0.40, "low"),
]


def _confidence_band_label(confidence: float | None) -> str:
    """Map a numeric confidence to a default-rubric band name.

    Returns ``""`` for ``None`` (synthesis didn't report one) so the caller can
    skip the band suffix. Confidences below the lowest band map to
    ``"below threshold"`` — these shouldn't ship in production (synthesis is
    supposed to omit them) but surfacing them in the report aids audit.
    """
    if confidence is None:
        return ""
    for threshold, label in _CONFIDENCE_BAND_THRESHOLDS:
        if confidence >= threshold:
            return label
    return "below threshold"


def _format_authors(raw: Any) -> str:
    """Normalise an author field from S2 metadata or PaperExtract into prose.

    S2 stores authors as ``list[dict[str, Any]]`` with ``"name"`` keys; the
    LLM-emitted ``PaperExtract.authors`` is already a comma-separated string.
    Anything else (None, empty, unexpected shape) collapses to ``"(unknown)"``
    so the renderer never crashes on partial data.
    """
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    if isinstance(raw, list) and raw:
        names = []
        for entry in raw:
            if isinstance(entry, dict):
                name = entry.get("name")
                if isinstance(name, str) and name.strip():
                    names.append(name.strip())
            elif isinstance(entry, str) and entry.strip():
                names.append(entry.strip())
        if names:
            return ", ".join(names)
    return "(unknown)"


def _first_nonempty(*candidates: Any) -> str:
    """Return the first candidate that is a non-empty string, else ``""``."""
    for c in candidates:
        if isinstance(c, str) and c.strip():
            return c.strip()
    return ""


def _render_summary_banner(output: LiteratureReviewOutput) -> str:
    """Top-of-report metadata table + counts + rubric footnote."""
    tier_counts: dict[str, int] = {"arxiv_source": 0, "pdfplumber_llm": 0, "abstract_only": 0}
    unresolved = 0
    for paper in output.retrieved_papers:
        if paper.extract is not None:
            tier_counts[paper.extract.extraction_method] = (
                tier_counts.get(paper.extract.extraction_method, 0) + 1
            )
        else:
            unresolved += 1

    tier_parts = [f"{n} × {tier}" for tier, n in tier_counts.items() if n > 0]
    if unresolved:
        tier_parts.append(f"{unresolved} × unresolved (no extract)")
    tier_breakdown = " · ".join(tier_parts) if tier_parts else "(none)"

    findings_count = len(output.findings)
    total = len(output.retrieved_papers)
    return (
        f"# Literature Review Report — {output.run_name}\n\n"
        "| | |\n"
        "|---|---|\n"
        f"| **Run** | `{output.run_name}` |\n"
        f"| **Started** | `{output.started_at}` |\n"
        f"| **Finished** | `{output.finished_at}` |\n"
        f"| **Papers retrieved** | {total} ({tier_breakdown}) |\n"
        f"| **Findings** | {findings_count} (after rubric filtering) |\n"
        f"| **Search rounds used** | {output.search_rounds_used} |\n"
        "\n"
        "> *Confidence labels (high / moderate / low) follow the default "
        "ConfidenceRubric bands (≥0.80 / ≥0.60 / ≥0.40). Runs that override "
        "the rubric may map numbers to different evidence criteria — see the "
        "input config to verify.*"
    )


def _render_paper_block(idx: int, paper: RetrievedPaper) -> str:
    """Render one ``RetrievedPaper`` as a Markdown sub-section.

    Layout: heading → metadata table → optional Tier-2 callout → optional
    error blockquote → prose sections (each skipped if empty) → equations →
    pseudocode → trailing ``---`` separator.

    ``paper_id`` always renders verbatim in the heading so a reader can grep
    findings ↔ papers. Title falls back through ``extract.title`` →
    ``s2_metadata['title']`` → ``"(untitled)"`` so partial-resolution papers
    still render usefully.
    """
    s2 = paper.s2_metadata or {}
    extract = paper.extract

    title = (
        _first_nonempty(
            extract.title if extract else None,
            s2.get("title"),
        )
        or "(untitled)"
    )

    if extract is not None:
        badge = _EXTRACTION_BADGES.get(
            extract.extraction_method,
            f"`{extract.extraction_method}`",
        )
    else:
        badge = "— (no extract)"

    year = (
        _first_nonempty(
            extract.year if extract else None,
            str(s2.get("year") or ""),
        )
        or "(unknown)"
    )
    authors = _format_authors((extract.authors if extract else None) or s2.get("authors"))
    s2_paper_id = _first_nonempty(s2.get("paperId")) or "(none)"

    metadata_table = (
        "| Field | Value |\n"
        "|---|---|\n"
        f"| Source | `{paper.source.source_type}` : `{paper.source.identifier}` |\n"
        f"| Verbosity achieved | `{paper.verbosity_achieved}` |\n"
        f"| **Extraction** | {badge} |\n"
        f"| Year | {year} |\n"
        f"| Authors | {authors} |\n"
        f"| S2 paperId | `{s2_paper_id}` |"
    )

    blocks: list[str] = [
        f"### {idx}. `{paper.paper_id}` — {title}",
        metadata_table,
    ]

    if extract is not None and extract.extraction_method == "pdfplumber_llm":
        blocks.append(_TIER2_TRUST_CALLOUT)

    if paper.error:
        blocks.append(f"> ❌ **Resolver error:** {paper.error}")

    if extract is not None:
        # Prose sections — skip any field the LLM left empty so the report
        # doesn't show hollow headings. Order matches the schema field order
        # so a reviewer reading top-to-bottom always sees the same shape.
        prose_sections = [
            ("Core idea", extract.core_idea),
            ("Architecture details", extract.architecture_details),
            ("Key results", extract.key_results),
            ("Relevance to task", extract.relevance_to_task),
        ]
        for heading, body in prose_sections:
            body = body.strip()
            if body:
                blocks.append(f"**{heading}.** {body}")

        # Equations / pseudocode get a tier-dependent caveat. Skip the entire
        # section if the LLM produced no content (Tier 1 papers may genuinely
        # have nothing publishable; abstract-only always does).
        caveat = _TIER_CAVEAT_PER_SECTION.get(extract.extraction_method, "")
        if extract.key_equations_md.strip():
            blocks.append(f"**Key equations.**{caveat}\n\n{extract.key_equations_md.strip()}")
        if extract.pseudocode_md.strip():
            blocks.append(f"**Pseudocode.**{caveat}\n\n{extract.pseudocode_md.strip()}")

    blocks.append("---")
    return "\n\n".join(blocks)


def _render_retrieved_papers_section(papers: list[RetrievedPaper]) -> str:
    """The full "## Retrieved papers" section, numbered 1..N in input order.

    Input order matters: root papers come first (as listed in the input),
    then dynamic-search hits in the order they were discovered. Re-sorting
    would obscure the agent's actual search trajectory.
    """
    if not papers:
        return "## Retrieved papers\n\n*(none — the agent retrieved zero papers this run.)*"
    blocks = [_render_paper_block(i + 1, p) for i, p in enumerate(papers)]
    return "## Retrieved papers\n\n" + "\n\n".join(blocks)


def _build_paper_title_lookup(papers: list[RetrievedPaper]) -> dict[str, str]:
    """Map ``paper_id`` → resolved title for finding-heading cross-reference.

    Falls back through ``extract.title`` → ``s2_metadata['title']``; ``None``
    if neither is available so the caller can render source_ref-only headings.
    """
    lookup: dict[str, str] = {}
    for paper in papers:
        s2 = paper.s2_metadata or {}
        title = _first_nonempty(
            paper.extract.title if paper.extract else None,
            s2.get("title"),
        )
        if title:
            lookup[paper.paper_id] = title
    return lookup


def _render_finding_block(idx: int, item: ExpertContextItem, title_lookup: dict[str, str]) -> str:
    """Render one ExpertContextItem as a Markdown sub-section.

    Heading construction (per the design): ``source_ref — matched_title — confidence``
    when a paper with ``paper_id == source_ref`` is in the lookup, else ``source_ref —
    confidence``. We do NOT extract a title from the finding's ``content`` —
    that proved fragile because the three-part format varies and any heuristic
    would silently mislabel findings. ``content`` is rendered verbatim below
    the heading.
    """
    confidence = item.confidence
    band = _confidence_band_label(confidence)
    conf_suffix = (
        f" — confidence `{confidence:.2f}` ({band})"
        if confidence is not None and band
        else f" — confidence `{confidence:.2f}`"
        if confidence is not None
        else ""
    )

    matched_title = title_lookup.get(item.source_ref)
    if matched_title:
        heading = f"### {idx}. `{item.source_ref}` — {matched_title}{conf_suffix}"
    else:
        heading = f"### {idx}. `{item.source_ref}`{conf_suffix}"

    metadata_line = f"**Cite:** `{item.source_ref}` · **Source agent:** `{item.source}` · **Kind:** `{item.kind}`"

    return "\n\n".join([heading, metadata_line, item.content.strip(), "---"])


def _render_findings_section(
    findings: list[ExpertContextItem], title_lookup: dict[str, str]
) -> str:
    """The full "## Findings" section, sorted high→low by confidence.

    Deterministic sort key: ``(-confidence, source_ref)``. ``None`` confidences
    sort last (treated as ``-inf`` for the negated key). Findings are rendered
    verbatim — the three-part Implication / Mechanism / Adaptation format
    (when ``findings_verbosity=1`` was used) lives inside ``content`` already.
    """
    if not findings:
        return (
            "## Findings\n\n"
            "*(none — either this report covers a Phase-1-only extraction "
            "run (synthesis was not invoked) or synthesis ran and no findings "
            "cleared the confidence threshold. Cross-check `search_rounds_used` "
            "and the input config to disambiguate.)*"
        )

    def sort_key(item: ExpertContextItem) -> tuple[float, str]:
        c = item.confidence if item.confidence is not None else float("-inf")
        return (-c, item.source_ref)

    sorted_findings = sorted(findings, key=sort_key)
    blocks = [
        _render_finding_block(i + 1, item, title_lookup) for i, item in enumerate(sorted_findings)
    ]
    return f"## Findings ({len(findings)} total, sorted by confidence)\n\n" + "\n\n".join(blocks)


def render_review_report(output: LiteratureReviewOutput) -> str:
    """Render a ``LiteratureReviewOutput`` as a Markdown report for human review.

    Pure function — no I/O, no LLM, deterministic from its input. Callers
    write the returned string to disk (e.g. ``docs/validation_suite_runs.md``).

    Handles two scenarios with the same code path:

    1. **§10 Phase 1 extraction reports** (Checkpoints E / F): the caller
       constructs a minimal ``LiteratureReviewOutput`` with the resolved
       papers and ``findings=[]``. The findings section honestly reports
       "(none)" alongside ``search_rounds_used = 0`` so the reader sees
       synthesis was not run.
    2. **Production runs**: the renderer shows the same per-paper detail
       plus the synthesised findings section, sorted high→low by confidence.

    The Pydantic-validated ``LiteratureReviewOutput`` is the single source of
    truth — per CLAUDE.md's "validated schema is the only execution input"
    principle.

    Confidence band labels (high / moderate / low) are derived from the
    *default* ``ConfidenceRubric`` thresholds; runs that override the rubric
    may map the same numbers to different evidence criteria — the summary
    banner carries a footnote pointing readers at the input config.

    Args:
        output: A validated ``LiteratureReviewOutput`` produced by the
                ml_literature_review node. Must be schema-valid; the renderer
                does no further validation.

    Returns:
        A single Markdown document as a string. The same input always
        produces the same output (deterministic sort, no time-of-day, no
        randomness).
    """
    title_lookup = _build_paper_title_lookup(output.retrieved_papers)
    sections = [
        _render_summary_banner(output),
        _render_retrieved_papers_section(output.retrieved_papers),
        _render_findings_section(output.findings, title_lookup),
    ]
    return "\n\n".join(sections) + "\n"
