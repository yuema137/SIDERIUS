# nodes/ml_literature_review/ml_literature_review.py
"""
ml_literature_review node — the external literature-review agent.

Pipeline (one ``run``):
  1. Root-paper resolution (cache-first) via ``paper_resolver_skill``; verbosity
     >= 1 root papers are compressed into a ``PaperExtract`` by the LLM.
  2. Dynamic S2 search loop — each round the LLM decides search / escalate /
     done, grounded in the iteration's ``InterpretationOutput`` (key_findings +
     bottlenecks are the primary signal). Bounded by ``max_rounds``.
  3. Final synthesis — the LLM turns the retrieved papers into
     ``ExpertContextItem`` findings (the always-on channel).
  4. Storage — the validated ``LiteratureReviewOutput`` is dumped to
     ``{workspace}/ml_literature_review_{run_name}.json`` (the inter-node
     communication invariant in CLAUDE.md — a log, not a channel).

Conventions match the existing nodes (confirmed by reading
``nodes/result_interpretation_agent/result_interpretation_agent.py`` and
``nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py``):
  - class with ``.run(inp) -> Output``;
  - the LLMBridge is built lazily in ``run()`` from ``inp.llm_provider`` /
    ``inp.llm_model_id`` via an injectable ``bridge_factory`` (tests pass a fake;
    there is no ``LLMBridge.get_instance()``);
  - ``bridge.generate()`` returns a parsed dict, validated with
    ``model_validate``.

See docs/commit_plan_ml_literature_review.md Commit 4 + Checkpoint C.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from agent.llm_bridge import LLMBridge
from agent.prompt_templates.literature_review import (
    DIMENSION_LABELS,
    render_paper_extract_prompt,
    render_search_decision_prompt,
    render_synthesis_prompt,
)
from agent.schemas.literature_review import (
    ConfidenceRubric,
    LiteratureReviewInput,
    LiteratureReviewOutput,
    PaperExtract,
    PaperSource,
    RetrievedPaper,
    SearchDecisionRecord,
)
from agent.schemas.proposal import AgentCard, ExpertContextItem
from agent.skills.paper_resolver_skill.wrapper import run_skill

logger = logging.getLogger(__name__)

# Default on-disk cache for resolved root papers (overridable for tests).
# (Hits-per-query is now DynamicSearchConfig.results_per_query.)
DEFAULT_ROOT_CACHE_DIR = "reference_data/root_papers_cache"

# Static self-description emitted on every run — tells the proposal LLM how to
# weight this agent's findings (see AgentCard / docs/external_agents_for_proposer.md).
_AGENT_CARD = AgentCard(
    agent_name="ml_literature_review",
    role="Surface ML denoising literature relevant to the current iteration.",
    expertise_domain="ML denoising architectures; Semantic Scholar corpus.",
    coverage="ArXiv/S2 results any year; local PDFs in reference_data/.",
    limitations=(
        "Cannot run experiments; cannot judge SQUID-specific applicability "
        "without empirical confirmation."
    ),
    # Survey-style source: literature findings are inspirational priors. The
    # proposer's synthesis rules treat soft_prior findings as candidates that
    # expand the design space beyond what experiment history has tried, but
    # experiment data takes precedence on conflict. See AgentCard.trust_level
    # docstring for the full semantics.
    trust_level="soft_prior",
    # The proposer reads raw confidence numbers off each finding; the rubric
    # legend here tells it what those numbers mean (single source of truth =
    # ConfidenceRubric — invariant 3). Uses the DEFAULT rubric. If a run ever
    # overrides inp.confidence_rubric, this static card would describe the
    # default instead — build the card per-run from inp.confidence_rubric then.
    trust_guidance=ConfidenceRubric().render_for_consumer(),
)


def _utc_now() -> str:
    """ISO-8601 UTC timestamp, e.g. ``2026-05-27T12:00:00Z``."""
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _sanitize_paper_id(paper_id: str) -> str:
    """Map a ``{source_type}:{identifier}`` id to a filesystem-safe filename stem.

    Identifiers contain ``:`` and ``/`` (DOIs, URLs) which are unsafe in a path;
    collapse everything outside ``[A-Za-z0-9._-]`` to ``_``.
    """
    return re.sub(r"[^A-Za-z0-9._-]", "_", paper_id)


def _source_type_from_external_ids(
    ext: dict,
) -> tuple[Literal["arxiv", "doi"] | None, str | None]:
    """Pick a resolvable ``(source_type, identifier)`` from S2 ``externalIds``.

    Prefers ArXiv (the de-facto-primary, reliable PDF path — pilot F1), then
    DOI. Returns ``(None, None)`` when neither is present (the paper cannot be
    escalated, so it is not added to the audit trail).
    """
    if ext.get("ArXiv"):
        return "arxiv", str(ext["ArXiv"])
    if ext.get("DOI"):
        return "doi", str(ext["DOI"])
    return None, None


def _as_verbosity(value) -> Literal[0, 1, 2]:
    """Coerce an untyped value (e.g. a skill-dict field) to the verbosity Literal."""
    if value == 2:
        return 2
    if value == 1:
        return 1
    return 0


# Heading aliases for finding `content` at findings_verbosity=1. The synthesis
# prompt instructs the LLM to use `**Implication:**` / `**Mechanism:**` /
# `**Adaptation:**` verbatim, but LLMs occasionally slip (DeepSeek wrote
# `**Adaption:**` on 1 of 6 findings in the 2026-05-27 validation). The map
# below rewrites known variants to the canonical heading. Identity mappings for
# the canonical forms keep the pattern explicit — when a new variant is
# observed in a real run, add an entry pointing it at the canonical form.
_FINDING_HEADING_ALIASES: dict[str, str] = {
    # canonical -> itself (documents the canonical set; no-op at runtime)
    "**Implication:**": "**Implication:**",
    "**Mechanism:**": "**Mechanism:**",
    "**Adaptation:**": "**Adaptation:**",
    # known variants -> canonical
    "**Adaption:**": "**Adaptation:**",  # DeepSeek typo (2026-05-27 validation)
}


def _normalize_finding_content_headings(content: str) -> str:
    """Rewrite known heading variants in a finding's ``content`` to canonical form.

    Applied in ``_synthesize`` right before each ``ExpertContextItem`` is built,
    so downstream consumers (the proposer's content parser) see canonical
    headings only. Add new entries to ``_FINDING_HEADING_ALIASES`` as new
    variants surface in real runs — identity rows for the canonical forms make
    the pattern obvious.
    """
    for variant, canonical in _FINDING_HEADING_ALIASES.items():
        if variant != canonical:
            content = content.replace(variant, canonical)
    return content


def _validate_content_paper_id(
    finding: dict[str, Any], valid_ids: set[str]
) -> dict[str, Any] | None:
    """Hard-validate ``content_paper_id == source_ref`` on a synthesis finding.

    Layer-2 defence (paired with the synthesis prompt's per-paper-block label
    and the synthesis_system.md hard rule) against the cite-id-vs-content
    mismatch failure mode observed on the first 2d real_run pilot. The
    synthesis prompt requires the LLM to fill BOTH ``source_ref`` and
    ``content_paper_id`` with the same paper_id: ``source_ref`` is the
    citation; ``content_paper_id`` is the id of the paper whose content the
    LLM described in Mechanism. If the two differ, the LLM cited Paper A but
    wrote about Paper B — the finding is a hallucination and is dropped
    before it reaches ``ExpertContextItem``.

    Follows the soft-drop hook contract: returns the ``finding`` dict
    unchanged when validation passes, returns ``None`` to signal the
    caller's loop to ``continue`` (with a ``logger.warning`` already
    emitted, matching the source_ref soft-drop in ``_synthesize``).

    Args:
      finding:   The raw finding dict from the synthesis JSON output.
                 Expected to carry ``content_paper_id`` per the 2d
                 synthesis-prompt contract; absence is itself a drop.
      valid_ids: The set of corpus paper_ids — defence in depth against
                 the LLM emitting a content_paper_id outside the corpus.

    Returns:
      ``finding`` (unchanged) on pass; ``None`` on any of the three drop
      conditions (missing field / not in corpus / != source_ref). The
      ``content_paper_id`` field is consumed here and not forwarded
      downstream — ``ExpertContextItem`` schema is unchanged.
    """
    source_ref = str(finding.get("source_ref") or "")
    content_paper_id = str(finding.get("content_paper_id") or "")
    if not content_paper_id:
        logger.warning(
            "dropping finding citing %r: missing content_paper_id "
            "(the 2d synthesis prompt requires it as a content-vs-source_ref "
            "consistency check)",
            source_ref,
        )
        return None
    if content_paper_id not in valid_ids:
        logger.warning(
            "dropping finding citing %r: content_paper_id %r is not in the "
            "retrieved-paper set (hallucination)",
            source_ref,
            content_paper_id,
        )
        return None
    if content_paper_id != source_ref:
        logger.warning(
            "dropping finding: content_paper_id %r != source_ref %r — the LLM "
            "described one paper's content but cited another (hallucination "
            "the per-paper block format did not prevent)",
            content_paper_id,
            source_ref,
        )
        return None
    return finding


def _override_year_from_metadata(extract: PaperExtract | None, s2_metadata: dict | None) -> None:
    """Overwrite the LLM-extracted ``year`` with S2's authoritative value when available.

    The compression LLM reads ``year`` from degraded PDF text and is sometimes
    wrong (e.g. it picks a revision-stamp year). ``s2_metadata['year']`` is the
    canonical source. No-op for ``local`` sources (no metadata) or a missing year.
    """
    if extract is None or not s2_metadata:
        return
    year = s2_metadata.get("year")
    if year:
        extract.year = str(year)


def _parse_dimension(reasoning: str) -> str | None:
    """Scan ``reasoning`` for the first ``DIMENSION_LABELS`` token (case-
    insensitive, substring match) and return it. Returns None when none of
    the four labels appears — a diagnostic signal that the LLM did not
    follow the dimension-labelling rule in search_decision_system.md.

    Multi-label reasoning ("targets bottleneck AND adjacent_technique"):
    returns the label whose earliest occurrence is leftmost in the string.
    The dynamic-search rule says "label which dimension the query targets"
    (singular), so the leftmost-mention heuristic picks the primary one.

    Fix 5 (Commit 6.5b-4).
    """
    if not reasoning:
        return None
    lowered = reasoning.lower()
    hits = [(lowered.find(label), label) for label in DIMENSION_LABELS]
    hits = [(idx, label) for idx, label in hits if idx != -1]
    if not hits:
        return None
    hits.sort()
    return hits[0][1]


class MLLiteratureReviewAgent:
    """Resolve root papers, run the dynamic search loop, synthesise findings.

    Args:
        bridge_factory: callable constructing an ``LLMBridge``-compatible object.
            Defaults to the real ``LLMBridge``; tests inject a fake. The bridge
            is built inside ``run()`` from the input's llm config.
        root_cache_dir: directory for the root-paper JSON cache. Defaults to
            ``reference_data/root_papers_cache``; tests point it at a tmp dir.
    """

    # Built in run() from the validated input's llm config (the provider/model
    # live on the input, not the constructor — matching the tuner's lazy bridge).
    # Declared here so they are non-Optional for the helper methods that use them.
    # ``search_bridge`` drives the cheap/templated search-decision step (may be a
    # cheaper model than the main reasoning bridge); falls back to ``bridge``.
    bridge: LLMBridge
    search_bridge: LLMBridge
    _task_description: str  # Fix 6 (6.5b-5): set in run() from inp.task_description

    def __init__(self, bridge_factory=None, root_cache_dir: str = DEFAULT_ROOT_CACHE_DIR):
        self._bridge_factory = bridge_factory or LLMBridge
        self._root_cache_dir = root_cache_dir

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------
    def run(self, inp: LiteratureReviewInput) -> LiteratureReviewOutput:
        inp = LiteratureReviewInput.model_validate(inp)
        started_at = _utc_now()
        self.bridge = self._bridge_factory(provider=inp.llm_provider, model_id=inp.llm_model_id)
        # Search-decision bridge: the cheap, templated query/escalate/done step may
        # run on a cheaper model (e.g. deepseek-v4) while compression + synthesis
        # stay on the main model. Falls back to the main bridge when unconfigured.
        if inp.search_llm_provider or inp.search_llm_model_id:
            self.search_bridge = self._bridge_factory(
                provider=inp.search_llm_provider or inp.llm_provider,
                model_id=inp.search_llm_model_id or inp.llm_model_id,
            )
        else:
            self.search_bridge = self.bridge
        # Fix 6 (6.5b-5) + Commit F: the task description threaded into all
        # three render call sites (compression / search-decision / synthesis).
        # When the input field is empty (the workflow warns at YAML-load time),
        # the empty string flows through to the {TASK_DESCRIPTION} placeholder
        # — operator should fill the YAML's task_description: key.
        self._task_description = inp.task_description
        cache_dir = Path(self._root_cache_dir)

        retrieved: list[RetrievedPaper] = []
        index: dict[str, RetrievedPaper] = {}  # paper_id -> RetrievedPaper (dedup + escalation)

        # 1. Root papers (cache-first).
        for src in inp.root_papers:
            rp = self._resolve_root_paper(src, cache_dir)
            if rp.paper_id not in index:
                retrieved.append(rp)
                index[rp.paper_id] = rp

        # 2. Dynamic search loop.
        rounds_used = 0
        search_decisions: list[SearchDecisionRecord] = []  # Fix 4 (6.5b-3)
        if inp.dynamic_search.enabled:
            rounds_used, search_decisions = self._run_search_loop(inp, retrieved, index)

        # 3. Synthesis -> findings.
        findings = self._synthesize(inp, retrieved)

        out = LiteratureReviewOutput(
            agent_card=_AGENT_CARD,
            findings=findings,
            new_vocab_candidates=[],  # v1: deliberately empty
            suggested_mindset=None,  # v1: deliberately empty
            retrieved_papers=retrieved,
            search_rounds_used=rounds_used,
            search_decisions=search_decisions,  # Fix 4 (6.5b-3)
            run_name=inp.run_name,
            started_at=started_at,
            finished_at=_utc_now(),
        )
        self._write_output(inp, out)
        return out

    # ------------------------------------------------------------------
    # Root-paper resolution
    # ------------------------------------------------------------------
    def _resolve_root_paper(self, src: PaperSource, cache_dir: Path) -> RetrievedPaper:
        paper_id = f"{src.source_type}:{src.identifier}"
        cache_path = cache_dir / f"{_sanitize_paper_id(paper_id)}.json"

        if cache_path.exists():
            try:
                return RetrievedPaper.model_validate_json(cache_path.read_text())
            except (ValidationError, OSError, ValueError) as e:
                logger.warning("root cache unreadable at %s (%s); re-resolving", cache_path, e)

        result = run_skill(
            None,
            mode="resolve",
            source_type=src.source_type,
            identifier=src.identifier,
            verbosity=src.verbosity,
        )
        rp = self._build_retrieved_from_resolve(paper_id, src, result)

        # Cache anything that produced at least metadata/text; skip hard errors
        # so they are retried on the next run.
        if result.get("status") in ("ok", "partial"):
            try:
                cache_dir.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(rp.model_dump_json(indent=2))
            except OSError as e:
                logger.warning("failed to write root cache %s: %s", cache_path, e)
        return rp

    def _build_retrieved_from_resolve(
        self, paper_id: str, src: PaperSource, result: dict
    ) -> RetrievedPaper:
        data = result.get("data") or {}
        status = result.get("status")
        s2_meta = data.get("s2_metadata")
        full_text = data.get("full_text")
        # Skill response carries the extraction tier (Commit 2c-b). Pre-2c
        # cached entries don't have it — default to the conservative tier.
        extraction_method = data.get("extraction_method") or "pdfplumber_llm"
        error = None if status == "ok" else result.get("message")

        extract: PaperExtract | None = None
        stored_full_text = full_text if (src.verbosity == 2 and full_text) else None
        achieved: Literal[0, 1, 2] = _as_verbosity(data.get("verbosity_achieved", 0))

        if src.verbosity >= 1 and full_text:
            extract = self._compress(full_text, extraction_method=extraction_method)
            # On compression failure keep full text only if it was requested
            # (verbosity 2); otherwise degrade to metadata-only.
            achieved = src.verbosity if extract is not None else (2 if stored_full_text else 0)
            _override_year_from_metadata(extract, s2_meta)

        return RetrievedPaper(
            paper_id=paper_id,
            source=src,
            s2_metadata=s2_meta,
            extract=extract,
            full_text=stored_full_text,
            verbosity_achieved=achieved,
            error=error,
            discovered_in_round=0,  # Fix 4.D (6.5b-3): root paper marker
            discovered_via_query=None,  # explicit None for forward-clarity
        )

    # ------------------------------------------------------------------
    # Dynamic search loop
    # ------------------------------------------------------------------
    def _run_search_loop(
        self,
        inp: LiteratureReviewInput,
        retrieved: list[RetrievedPaper],
        index: dict[str, RetrievedPaper],
    ) -> tuple[int, list[SearchDecisionRecord]]:
        cfg = inp.dynamic_search
        hist = inp.experiment_history
        rounds = 0  # search rounds executed (== search_rounds_used)
        escalations_this_round = 0  # reset on each search; capped per round
        prior_search_results: list[tuple[str, int]] = []  # (query, hit_count) fed back per round
        prior_escalation_results: list[
            tuple[str, str, str]
        ] = []  # (paper_id, status, reasoning); status ∈ {"ok","noop","error"} — Fix 3 (6.5b-2)
        decisions: list[SearchDecisionRecord] = []  # Fix 4 (6.5b-3): audit trail
        dimension_counts: dict[str, int] = {
            label: 0 for label in DIMENSION_LABELS
        }  # Fix 5 (6.5b-4): per-dim query coverage

        # Fix 4 (6.5b-3): build one SearchDecisionRecord per LLM call.
        # Defined at method scope (not inside the while loop) so pyright
        # can resolve its type without circular inference, and takes
        # `dec` + `current_rounds` as explicit args so there's no B023
        # loop-variable-capture risk either. Captures `decisions` (the
        # list — stable identity across iterations) via closure.
        def _append_decision(
            action_str: str,
            outcome: str,
            dec: dict[str, Any],
            current_rounds: int,
        ) -> None:
            decisions.append(
                SearchDecisionRecord(
                    round_index=current_rounds + 1,  # 1-indexed
                    action=action_str,
                    query=(dec.get("query") or None) if action_str == "search" else None,
                    paper_id=(dec.get("paper_id") or None) if action_str == "escalate" else None,
                    verbosity=dec.get("verbosity") if action_str == "escalate" else None,
                    reasoning=str(dec.get("reasoning") or ""),
                    outcome=outcome,
                )
            )

        # A misbehaving LLM that only ever escalates must still terminate:
        # searches consume the round budget, escalations do not. This hard
        # iteration ceiling is the backstop (searches + capped escalations).
        max_iters = cfg.max_rounds * (1 + cfg.max_escalations_per_round) + 1
        iters = 0

        while rounds < cfg.max_rounds and iters < max_iters:
            iters += 1
            papers_seen = [self._paper_summary(rp) for rp in retrieved]
            sys_prompt, user_prompt = render_search_decision_prompt(
                key_findings=hist.key_findings,
                bottlenecks=hist.bottlenecks,
                take_home_message=hist.take_home_message,
                explored_models=hist.model_types,
                papers_seen=papers_seen,
                escalation_allowed=cfg.escalation_allowed,
                prior_search_results=prior_search_results,
                prior_escalation_results=prior_escalation_results,  # Fix 3 (6.5b-2)
                dimension_counts=dimension_counts,  # Fix 5 (6.5b-4)
                task_description=self._task_description,  # Fix 6 (6.5b-5)
            )
            # The search-decision is the cheap, templated step — routed through
            # self.search_bridge (a cheaper model when configured; else the main
            # bridge). Compression + synthesis stay on self.bridge.
            try:
                decision = self.search_bridge.generate(
                    sys_prompt, user_prompt, label="lit_review.search_decision"
                )
            except Exception as e:  # resilience boundary — a bad call ends the loop, not the run
                logger.warning(
                    "search-decision call failed at round %d: %s; ending loop", rounds, e
                )
                break
            if not isinstance(decision, dict):
                logger.warning("search-decision returned non-dict at round %d; ending loop", rounds)
                break

            action = decision.get("action")
            logger.info("[lit_review] round %d decision: %s", rounds, json.dumps(decision)[:500])

            if action == "done":
                _append_decision("done", "done", decision, rounds)
                break
            if action == "search":
                query = (decision.get("query") or "").strip()
                if not query:
                    _append_decision("search", "empty_query", decision, rounds)
                    logger.warning(
                        "search action with empty query at round %d; ending loop", rounds
                    )
                    break
                n_hits = self._do_search(
                    query,
                    retrieved,
                    index,
                    cfg.results_per_query,
                    cfg.initial_verbosity,
                    round_index=rounds + 1,  # Fix 4.E: tag new papers with their discovery round
                )
                prior_search_results.append((query, n_hits))
                _append_decision("search", f"n_hits={n_hits}", decision, rounds)
                # Fix 5 (6.5b-4): parse the dimension label from the LLM's
                # reasoning and tally it. None means the LLM didn't follow
                # the labelling rule — diagnostic signal, no tally.
                dim = _parse_dimension(str(decision.get("reasoning") or ""))
                if dim is not None:
                    dimension_counts[dim] = dimension_counts.get(dim, 0) + 1
                rounds += 1
                escalations_this_round = 0  # fresh escalation budget for the new round
            elif action == "escalate" and cfg.escalation_allowed:
                if escalations_this_round >= cfg.max_escalations_per_round:
                    logger.info(
                        "escalation cap (%d) reached this round; dropping escalate of %r",
                        cfg.max_escalations_per_round,
                        decision.get("paper_id"),
                    )
                    _append_decision("escalate", "budget_exceeded", decision, rounds)
                else:
                    pid = decision.get("paper_id")
                    target = index.get(pid) if isinstance(pid, str) else None
                    if target is not None:
                        # `target is not None` implies the `isinstance(pid, str)` branch
                        # of the conditional above fired — i.e. pid is a str. The
                        # assert restates the invariant for pyright's narrowing.
                        assert isinstance(pid, str)
                        status = self._escalate(target, decision.get("verbosity", 1))
                        prior_escalation_results.append(
                            (pid, status, str(decision.get("reasoning") or ""))
                        )
                        _append_decision("escalate", status, decision, rounds)
                        escalations_this_round += (
                            1  # charges budget on every outcome (Decision 2, 2026-06-12)
                        )
                    else:
                        logger.warning("escalate target %r not found at round %d", pid, rounds)
                        _append_decision("escalate", "target_not_found", decision, rounds)
            else:
                # Catch-all: escalate-while-disabled is distinguished from
                # truly-unknown action so the audit trail captures the config
                # mismatch separately from LLM hallucinations.
                if action == "escalate" and not cfg.escalation_allowed:
                    logger.warning("escalate action at round %d but escalation is disabled", rounds)
                    _append_decision("escalate", "escalation_disabled", decision, rounds)
                else:
                    logger.warning("unhandled action %r at round %d", action, rounds)
                    _append_decision(
                        str(action) if action is not None else "",
                        "unknown_action",
                        decision,
                        rounds,
                    )
                rounds += 1

        return rounds, decisions

    def _do_search(
        self,
        query: str,
        retrieved: list[RetrievedPaper],
        index: dict[str, RetrievedPaper],
        limit: int,
        initial_verbosity: Literal[0, 1, 2] = 0,
        *,
        round_index: int,
    ) -> int:
        """Run one S2 search; append new papers; return the number of hits S2
        returned for ``query`` (fed back to the next round for self-correction).

        ``initial_verbosity`` is recorded on each new ``RetrievedPaper.source``
        as the operator's requested resolve depth (``DynamicSearchConfig.initial_verbosity``,
        2026-06-11 Pre-flight B fix). The S2 search itself stays at metadata-only
        (verbosity=0 in ``run_skill``); ``verbosity_achieved`` therefore also
        stays at 0 — actual deep-reads happen via the LLM's escalation decisions
        in ``_run_search_loop``.
        """
        result = run_skill(None, mode="search", query=query, limit=limit, verbosity=0)
        if result.get("status") not in ("ok", "partial"):
            logger.warning("search failed for query %r: %s", query, result.get("message"))
            return 0
        results = (result.get("data") or {}).get("results", [])
        for r in results:
            rp = self._retrieved_from_search_result(
                r, initial_verbosity, round_index=round_index, query=query
            )
            if rp is not None and rp.paper_id not in index:
                retrieved.append(rp)
                index[rp.paper_id] = rp
        return len(results)

    def _retrieved_from_search_result(
        self,
        r: dict,
        initial_verbosity: Literal[0, 1, 2] = 0,
        *,
        round_index: int,
        query: str,
    ) -> RetrievedPaper | None:
        source_type, identifier = _source_type_from_external_ids(r.get("externalIds") or {})
        if source_type is None or identifier is None:
            # No resolvable id → cannot be escalated; skip the audit entry.
            logger.debug("skipping search hit with no arxiv/doi id: %s", r.get("title"))
            return None
        paper_id = f"{source_type}:{identifier}"
        # ``source.verbosity`` records the operator's requested resolve depth
        # (``DynamicSearchConfig.initial_verbosity``, default 0). ``verbosity_achieved``
        # stays at 0 because the S2 search call itself is metadata-only; subsequent
        # LLM-driven escalation calls in ``_run_search_loop`` raise the achieved
        # value when they fetch + compress the full text. 2026-06-11 Pre-flight B —
        # the field was dormant before this fix.
        return RetrievedPaper(
            paper_id=paper_id,
            source=PaperSource(
                source_type=source_type, identifier=identifier, verbosity=initial_verbosity
            ),
            s2_metadata=r,
            verbosity_achieved=0,
            discovered_in_round=round_index,  # Fix 4.E (6.5b-3)
            discovered_via_query=query,
        )

    def _escalate(self, target: RetrievedPaper, verbosity) -> Literal["ok", "noop", "error"]:
        """Escalate ``target`` to verbosity 1 or 2; return a 3-state status.

        Returns:
            ``"ok"``    — verbosity_achieved was raised; new content captured.
            ``"noop"``  — the call succeeded but produced no new content
                          (paper already at requested verbosity, or fetch
                          returned an empty full_text). Charges the budget
                          regardless — Decision 2, 2026-06-12.
            ``"error"`` — the resolve call failed (PDF 404, S2 down, etc).
                          ``target.error`` is set; the LLM should not retry
                          this paper.
        """
        target_verbosity: Literal[1, 2] = 2 if verbosity == 2 else 1
        if target.verbosity_achieved >= target_verbosity:
            return "noop"  # already at requested verbosity — skip the API call
        # Layer 2 PDF-availability gate (post-Checkpoint-S, 2026-06-13).
        # Mirrors the resolver's PDF URL resolution priority
        # (agent/skills/paper_resolver_skill/wrapper.py:405-420):
        #   1. openAccessPdf.url if non-empty
        #   2. arxiv-fallback URL from externalIds.ArXiv
        #   3. otherwise: resolver returns "partial" with no full_text → noop
        # We short-circuit case (3) by checking the same two fields. Arxiv
        # sources are exempt because the resolver first tries Tier 1
        # (arxiv.org/src .tex) which doesn't depend on either field —
        # short-circuiting would skip a path that could succeed.
        # Behavior to the LLM is identical: it still sees a "noop" outcome
        # in prior_escalation_results and the do-not-retry nudge tells it
        # to pick a different paper.
        if target.source.source_type != "arxiv":
            s2_meta = target.s2_metadata or {}
            oa_pdf = s2_meta.get("openAccessPdf") or {}
            external_ids = s2_meta.get("externalIds") or {}
            has_pdf_url = bool(oa_pdf.get("url")) or bool(external_ids.get("ArXiv"))
            if not has_pdf_url:
                return "noop"
        pre_verbosity = target.verbosity_achieved  # snapshot for post-call detection
        result = run_skill(
            None,
            mode="resolve",
            source_type=target.source.source_type,
            identifier=target.source.identifier,
            verbosity=target_verbosity,
        )
        if result.get("status") not in ("ok", "partial"):
            target.error = result.get("message")
            return "error"
        data = result.get("data") or {}
        if data.get("s2_metadata"):
            target.s2_metadata = data["s2_metadata"]
        full_text = data.get("full_text")
        if not full_text:
            return "noop"  # call succeeded, but no new full text -> no content gain
        extraction_method = data.get("extraction_method") or "pdfplumber_llm"
        extract = self._compress(full_text, extraction_method=extraction_method)
        if extract is not None:
            _override_year_from_metadata(extract, target.s2_metadata)
            target.extract = extract
            target.verbosity_achieved = target_verbosity
            target.full_text = full_text if target_verbosity == 2 else None
        elif target_verbosity == 2:
            # Compression failed but we still hold the full text.
            target.full_text = full_text
            target.verbosity_achieved = 2
        return "ok" if target.verbosity_achieved > pre_verbosity else "noop"

    # ------------------------------------------------------------------
    # LLM compression (verbosity-1 extract)
    # ------------------------------------------------------------------
    def _compress(
        self,
        full_text: str,
        extraction_method: Literal[
            "arxiv_source", "pdfplumber_llm", "abstract_only"
        ] = "pdfplumber_llm",
    ) -> PaperExtract | None:
        """Compress full text into a PaperExtract; never raises (returns None).

        ``extraction_method`` selects the per-tier instruction block in
        ``render_paper_extract_prompt`` AND is stamped onto the resulting
        ``PaperExtract.extraction_method`` (the field is set node-side, not by
        the LLM — see §5a invariant). Defaults to ``"pdfplumber_llm"`` for
        pre-cascade safety; callers should pass the value from the skill
        response (``data["extraction_method"]``).
        """
        try:
            sys_prompt, user_prompt = render_paper_extract_prompt(
                full_text,
                extraction_method=extraction_method,
                task_description=self._task_description,  # Fix 6 (6.5b-5)
            )
            raw = self.bridge.generate(sys_prompt, user_prompt, label="lit_review.paper_extract")
            extract = PaperExtract.model_validate(raw)
            # Skill is authoritative for the tier signal; override any value
            # the LLM may have accidentally emitted.
            extract.extraction_method = extraction_method
            return extract
        except Exception as e:  # resilience boundary — a bad extract must not abort the run
            logger.warning("paper compression failed: %s", e)
            return None

    # ------------------------------------------------------------------
    # Synthesis
    # ------------------------------------------------------------------
    def _synthesize(
        self, inp: LiteratureReviewInput, retrieved: list[RetrievedPaper]
    ) -> list[ExpertContextItem]:
        hist = inp.experiment_history
        papers = [self._paper_for_synthesis(rp) for rp in retrieved]
        try:
            sys_prompt, user_prompt = render_synthesis_prompt(
                key_findings=hist.key_findings,
                bottlenecks=hist.bottlenecks,
                take_home_message=hist.take_home_message,
                papers=papers,
                confidence_rubric=inp.confidence_rubric,
                findings_verbosity=inp.findings_verbosity,
                synthesis_config=inp.synthesis_config,
                task_description=self._task_description,  # Fix 6 (6.5b-5)
            )
            raw = self.bridge.generate(sys_prompt, user_prompt, label="lit_review.synthesis")
        except Exception as e:  # resilience boundary
            logger.warning("synthesis call failed: %s", e)
            return []

        findings_raw = raw.get("findings") if isinstance(raw, dict) else None
        if not isinstance(findings_raw, list):
            return []

        valid_ids = {rp.paper_id for rp in retrieved}
        verbosity_by_id = {rp.paper_id: rp.verbosity_achieved for rp in retrieved}
        ceiling = inp.confidence_rubric.abstract_only_ceiling
        now = _utc_now()
        items: list[ExpertContextItem] = []
        for f in findings_raw:
            if not isinstance(f, dict) or not f.get("content"):
                continue
            source_ref = str(f.get("source_ref") or "")
            if source_ref not in valid_ids:
                # Soft-drop: a hallucinated source_ref must not discard an otherwise
                # useful list — log and omit just this item (plan open questions).
                logger.warning(
                    "dropping finding with unmatched source_ref %r (not in retrieved papers)",
                    source_ref,
                )
                continue
            # 2d hook: hard-validate content_paper_id == source_ref. The synthesis
            # prompt requires the LLM to name the paper its Mechanism describes;
            # the name must match the citation. Mismatch → soft-drop (same
            # contract as the source_ref check above; the hook emits its own
            # logger.warning). content_paper_id is consumed here and not
            # forwarded to ExpertContextItem (schema unchanged).
            if _validate_content_paper_id(f, valid_ids) is None:
                continue
            confidence = self._clamp_abstract_only_confidence(
                f.get("confidence"), source_ref, verbosity_by_id, ceiling
            )
            try:
                items.append(
                    ExpertContextItem(
                        source="ml_literature_review",
                        kind="literature",
                        content=_normalize_finding_content_headings(str(f["content"])),
                        source_ref=source_ref,
                        confidence=confidence,
                        produced_at=now,
                    )
                )
            except ValidationError as e:
                logger.warning("dropping invalid finding %s: %s", f, e)
        return items

    @staticmethod
    def _clamp_abstract_only_confidence(
        confidence, source_ref: str, verbosity_by_id: dict[str, int], ceiling: float
    ):
        """Cap a verbosity-0 (abstract-only) paper's finding confidence at ``ceiling``.

        The rubric's top confidence band requires a deep-read (verbosity >= 1), so
        a finding citing a paper that was never deep-read must not exceed the
        ceiling (``ConfidenceRubric.abstract_only_ceiling``). The threshold is the
        single source of truth in the schema — this node only enforces it. Non-
        numeric / ``None`` confidences pass through untouched (``ExpertContextItem``
        validates them); ``bool`` is excluded so a stray ``true`` is not treated as 1.0.
        """
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            return confidence
        if verbosity_by_id.get(source_ref, 0) == 0 and confidence > ceiling:
            logger.info(
                "clamping finding confidence %.2f -> %.2f (cite %s is abstract-only, v0)",
                confidence,
                ceiling,
                source_ref,
            )
            return ceiling
        return confidence

    # ------------------------------------------------------------------
    # Prompt-input formatting helpers
    # ------------------------------------------------------------------
    def _paper_summary(self, rp: RetrievedPaper) -> dict:
        """Compact view for the search-decision prompt's retrieved-papers menu."""
        title = year = None
        snippet = ""
        if rp.s2_metadata:
            title = rp.s2_metadata.get("title")
            year = rp.s2_metadata.get("year")
            snippet = (rp.s2_metadata.get("abstract") or "")[:240]
        if rp.extract:
            title = title or rp.extract.title
            year = year or rp.extract.year
            snippet = rp.extract.core_idea or rp.extract.relevance_to_task or snippet
        return {
            "paper_id": rp.paper_id,
            "title": title,
            "year": year,
            "verbosity_achieved": rp.verbosity_achieved,
            "snippet": snippet,
        }

    def _paper_for_synthesis(self, rp: RetrievedPaper) -> dict:
        """Fuller view for the synthesis prompt — prefers the compressed extract.

        Returns a dict carrying the per-paper context the synthesis LLM sees.
        Six fields:

          - ``paper_id`` / ``title`` / ``year`` — citation header.
          - ``summary`` — prose blob (architecture / results / relevance from
            the extract, or the s2 abstract as fallback).
          - ``key_equations_md`` / ``pseudocode_md`` / ``extraction_method``
            (Commit 2d) — extracted-content fields the synthesis prompt uses
            to quote equations and pseudocode directly inside the finding's
            **Mechanism** section. Empty strings (and ``"abstract_only"`` for
            ``extraction_method``) when the paper has no extract — the
            renderer skips the corresponding blocks in that case.
        """
        title = year = None
        summary = ""
        key_equations_md = ""
        pseudocode_md = ""
        extraction_method = "abstract_only"
        if rp.s2_metadata:
            title = rp.s2_metadata.get("title")
            year = rp.s2_metadata.get("year")
            summary = rp.s2_metadata.get("abstract") or ""
        if rp.extract:
            title = title or rp.extract.title
            year = year or rp.extract.year
            parts = []
            if rp.extract.architecture_details:
                parts.append(f"Architecture: {rp.extract.architecture_details}")
            if rp.extract.key_results:
                parts.append(f"Results: {rp.extract.key_results}")
            if rp.extract.relevance_to_task:
                parts.append(f"Relevance: {rp.extract.relevance_to_task}")
            if parts:
                summary = "\n".join(parts)
            # Commit 2d: surface equation + pseudocode + tier so the synthesis
            # prompt can quote them inline inside Mechanism. extraction_method
            # is always set when an extract exists (PaperExtract schema default
            # is "abstract_only" — see agent/schemas/literature_review.py).
            key_equations_md = rp.extract.key_equations_md
            pseudocode_md = rp.extract.pseudocode_md
            extraction_method = rp.extract.extraction_method
        return {
            "paper_id": rp.paper_id,
            "title": title,
            "year": year,
            "summary": summary,
            "key_equations_md": key_equations_md,
            "pseudocode_md": pseudocode_md,
            "extraction_method": extraction_method,
        }

    # ------------------------------------------------------------------
    # Storage (log, not a channel — see CLAUDE.md inter-node invariant)
    # ------------------------------------------------------------------
    def _write_output(self, inp: LiteratureReviewInput, out: LiteratureReviewOutput) -> None:
        local = inp.storage.local
        if local is None:
            logger.warning("storage.local is None; skipping node output dump")
            return
        workspace = Path(local.workspace)
        try:
            workspace.mkdir(parents=True, exist_ok=True)
            path = workspace / f"ml_literature_review_{inp.run_name}.json"
            path.write_text(out.model_dump_json(indent=2))
        except OSError as e:
            logger.warning("failed to write node output: %s", e)
