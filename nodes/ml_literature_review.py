# nodes/ml_literature_review.py
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
``nodes/result_interpretation_agent.py`` and ``ml_hyperparameter_tune_agent.py``):
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
from typing import Literal

from pydantic import ValidationError

from agent.llm_bridge import LLMBridge
from agent.prompt_templates.literature_review import (
    render_paper_extract_prompt,
    render_search_decision_prompt,
    render_synthesis_prompt,
)
from agent.schemas.literature_review import (
    LiteratureReviewInput,
    LiteratureReviewOutput,
    PaperExtract,
    PaperSource,
    RetrievedPaper,
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
    trust_guidance=(
        "Treat findings as promising priors; only experiment runs confirm applicability."
    ),
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
    # Declared here so it is non-Optional for the helper methods that use it.
    bridge: LLMBridge

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
        if inp.dynamic_search.enabled:
            rounds_used = self._run_search_loop(inp, retrieved, index)

        # 3. Synthesis -> findings.
        findings = self._synthesize(inp, retrieved)

        out = LiteratureReviewOutput(
            agent_card=_AGENT_CARD,
            findings=findings,
            new_vocab_candidates=[],  # v1: deliberately empty
            suggested_mindset=None,  # v1: deliberately empty
            retrieved_papers=retrieved,
            search_rounds_used=rounds_used,
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
        error = None if status == "ok" else result.get("message")

        extract: PaperExtract | None = None
        stored_full_text = full_text if (src.verbosity == 2 and full_text) else None
        achieved: Literal[0, 1, 2] = _as_verbosity(data.get("verbosity_achieved", 0))

        if src.verbosity >= 1 and full_text:
            extract = self._compress(full_text)
            # On compression failure keep full text only if it was requested
            # (verbosity 2); otherwise degrade to metadata-only.
            achieved = src.verbosity if extract is not None else (2 if stored_full_text else 0)

        return RetrievedPaper(
            paper_id=paper_id,
            source=src,
            s2_metadata=s2_meta,
            extract=extract,
            full_text=stored_full_text,
            verbosity_achieved=achieved,
            error=error,
        )

    # ------------------------------------------------------------------
    # Dynamic search loop
    # ------------------------------------------------------------------
    def _run_search_loop(
        self,
        inp: LiteratureReviewInput,
        retrieved: list[RetrievedPaper],
        index: dict[str, RetrievedPaper],
    ) -> int:
        cfg = inp.dynamic_search
        hist = inp.experiment_history
        rounds = 0  # search rounds executed (== search_rounds_used)
        escalations_this_round = 0  # reset on each search; capped per round
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
            )
            # TODO(reflector-split): this decision step is the natural future
            # reflector-model candidate (cheap, templated) — route it through a
            # cheaper model once the bridge's reflect split is generalised.
            try:
                decision = self.bridge.generate(
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
                break
            if action == "search":
                query = (decision.get("query") or "").strip()
                if not query:
                    logger.warning(
                        "search action with empty query at round %d; ending loop", rounds
                    )
                    break
                self._do_search(query, retrieved, index, cfg.results_per_query)
                rounds += 1
                escalations_this_round = 0  # fresh escalation budget for the new round
            elif action == "escalate" and cfg.escalation_allowed:
                if escalations_this_round >= cfg.max_escalations_per_round:
                    logger.info(
                        "escalation cap (%d) reached this round; dropping escalate of %r",
                        cfg.max_escalations_per_round,
                        decision.get("paper_id"),
                    )
                else:
                    pid = decision.get("paper_id")
                    target = index.get(pid) if isinstance(pid, str) else None
                    if target is not None:
                        self._escalate(target, decision.get("verbosity", 1))
                        escalations_this_round += 1
                    else:
                        logger.warning("escalate target %r not found at round %d", pid, rounds)
            else:
                # Unknown action (or escalate while disabled). Consume a round so
                # a misbehaving LLM cannot spin forever — max_rounds is the net.
                logger.warning("unhandled action %r at round %d", action, rounds)
                rounds += 1

        return rounds

    def _do_search(
        self,
        query: str,
        retrieved: list[RetrievedPaper],
        index: dict[str, RetrievedPaper],
        limit: int,
    ) -> None:
        result = run_skill(None, mode="search", query=query, limit=limit, verbosity=0)
        if result.get("status") not in ("ok", "partial"):
            logger.warning("search failed for query %r: %s", query, result.get("message"))
            return
        for r in (result.get("data") or {}).get("results", []):
            rp = self._retrieved_from_search_result(r)
            if rp is not None and rp.paper_id not in index:
                retrieved.append(rp)
                index[rp.paper_id] = rp

    def _retrieved_from_search_result(self, r: dict) -> RetrievedPaper | None:
        source_type, identifier = _source_type_from_external_ids(r.get("externalIds") or {})
        if source_type is None or identifier is None:
            # No resolvable id → cannot be escalated; skip the audit entry.
            logger.debug("skipping search hit with no arxiv/doi id: %s", r.get("title"))
            return None
        paper_id = f"{source_type}:{identifier}"
        return RetrievedPaper(
            paper_id=paper_id,
            source=PaperSource(source_type=source_type, identifier=identifier, verbosity=0),
            s2_metadata=r,
            verbosity_achieved=0,
        )

    def _escalate(self, target: RetrievedPaper, verbosity) -> None:
        target_verbosity: Literal[1, 2] = 2 if verbosity == 2 else 1
        result = run_skill(
            None,
            mode="resolve",
            source_type=target.source.source_type,
            identifier=target.source.identifier,
            verbosity=target_verbosity,
        )
        if result.get("status") not in ("ok", "partial"):
            target.error = result.get("message")
            return
        data = result.get("data") or {}
        if data.get("s2_metadata"):
            target.s2_metadata = data["s2_metadata"]
        full_text = data.get("full_text")
        if not full_text:
            return
        extract = self._compress(full_text)
        if extract is not None:
            target.extract = extract
            target.verbosity_achieved = target_verbosity
            target.full_text = full_text if target_verbosity == 2 else None
        elif target_verbosity == 2:
            # Compression failed but we still hold the full text.
            target.full_text = full_text
            target.verbosity_achieved = 2

    # ------------------------------------------------------------------
    # LLM compression (verbosity-1 extract)
    # ------------------------------------------------------------------
    def _compress(self, full_text: str) -> PaperExtract | None:
        """Compress full text into a PaperExtract; never raises (returns None)."""
        try:
            sys_prompt, user_prompt = render_paper_extract_prompt(full_text)
            raw = self.bridge.generate(sys_prompt, user_prompt, label="lit_review.paper_extract")
            return PaperExtract.model_validate(raw)
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
            )
            raw = self.bridge.generate(sys_prompt, user_prompt, label="lit_review.synthesis")
        except Exception as e:  # resilience boundary
            logger.warning("synthesis call failed: %s", e)
            return []

        findings_raw = raw.get("findings") if isinstance(raw, dict) else None
        if not isinstance(findings_raw, list):
            return []

        valid_ids = {rp.paper_id for rp in retrieved}
        now = _utc_now()
        items: list[ExpertContextItem] = []
        for f in findings_raw:
            if not isinstance(f, dict) or not f.get("content"):
                continue
            cite_id = str(f.get("cite_id") or "")
            if cite_id not in valid_ids:
                # Soft-drop: a hallucinated cite_id must not discard an otherwise
                # useful list — log and omit just this item (plan open questions).
                logger.warning(
                    "dropping finding with unmatched cite_id %r (not in retrieved papers)",
                    cite_id,
                )
                continue
            try:
                items.append(
                    ExpertContextItem(
                        source="ml_literature_review",
                        kind="literature",
                        content=str(f["content"]),
                        cite_id=cite_id,
                        confidence=f.get("confidence"),
                        produced_at=now,
                    )
                )
            except ValidationError as e:
                logger.warning("dropping invalid finding %s: %s", f, e)
        return items

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
        """Fuller view for the synthesis prompt — prefers the compressed extract."""
        title = year = None
        summary = ""
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
        return {"paper_id": rp.paper_id, "title": title, "year": year, "summary": summary}

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
