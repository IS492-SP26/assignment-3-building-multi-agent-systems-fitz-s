"""
Orchestrates the 4-stage deep-research workflow with parallel evidence
gathering and bull/bear debate loop.

Created: 2026-05-07
Last reused or audited: 2026-05-08 (Path C Fix 4A: Stage 3 restructured —
ResearchManager runs in PRE-DEBATE mode first to select ONE specific contested
claim with supporting + opposing source IDs. Optimist + Skeptic then receive
that claim and argue for/against using ONLY their assigned sources. RM then
runs in POST-DEBATE mode to judge WINNER + emit standard pipeline VERDICT.
If RM cannot find a contested claim, debate is skipped and debate_skipped:true
is propagated to the writer.)
Authority basis: Plan §Architecture (mirrors TauricResearch/TradingAgents
debate structure adapted to HCI deep research); critic_report_v2 finding 3.5.

Stage 2 runs three researchers concurrently via asyncio.gather. Stage 3
loops up to 2 times if Research Manager verdicts NEEDS_MORE. Stage 4
allows 1 revise cycle between Writer and Editor. All agent outputs
flow through strip_thinking() to remove Qwen3 <think> tags.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.messages import TextMessage
from autogen_core import CancellationToken

from src.agents.autogen_agents import (
    create_agents,
    create_model_client,
    strip_thinking,
)
from src.tools.citation_tool import SourceRegistry, format_sources_for_writer
from src.tools.web_search import web_search_structured
from src.tools.paper_search import paper_search_structured
from src.guardrails.safety_manager import SafetyManager
from src.guardrails.input_guardrail import InputGuardrail
from src.guardrails.output_guardrail import OutputGuardrail


logger = logging.getLogger("autogen_orchestrator")


# Fix 2 (2026-05-07): Qwen3-8B has a 40k token (~32k char safe) context window.
# When debate findings + 30+ sources accumulate, the writer prompt overflows.
# This helper truncates a list of string parts to fit a char budget.
def _truncate_for_context(parts: list, max_chars: int = 30000) -> str:
    """Concatenate parts, truncating to fit Qwen3-8B's 40k token limit (~30k chars safe)."""
    out = []
    used = 0
    for p in parts:
        if used >= max_chars:
            break
        if used + len(p) > max_chars:
            out.append(p[:max(0, max_chars - used)])
            break
        out.append(p)
        used += len(p)
    return "\n\n".join(out)


def _truncate_msg(text: str, limit: int = 800) -> str:
    """Truncate a single agent message (used for debate messages going into writer)."""
    if not text:
        return ""
    cleaned = strip_thinking(text)
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit] + "\n... [truncated]"


# ---------------------------------------------------------------------------
# Regexes (compiled once)
# ---------------------------------------------------------------------------

_JSON_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)
_BARE_JSON = re.compile(r"(\{[^{}]*?\"sub_questions\"\s*:\s*\[.*?\]\s*\})", re.DOTALL)

_MGR_VERDICT = re.compile(r"VERDICT\s*:\s*(APPROVED|NEEDS_MORE)", re.IGNORECASE)
_MGR_SUBQ = re.compile(r"sub[- ]?question\s*(?:#|id\s*[:=]?\s*)?(\d+)", re.IGNORECASE)

# Path C Fix 4A: pre-debate claim selection from ResearchManager.
_CLAIM_FOR_DEBATE = re.compile(
    r"CLAIM_FOR_DEBATE\s*:\s*(?P<claim>.+?)(?=\n[A-Z_]+\s*:|\Z)",
    re.IGNORECASE | re.DOTALL,
)
_SUPPORTING_SOURCES = re.compile(
    r"SUPPORTING_SOURCES\s*:\s*\[?(?P<ids>[^\]\n]+)\]?",
    re.IGNORECASE,
)
_OPPOSING_SOURCES = re.compile(
    r"OPPOSING_SOURCES\s*:\s*\[?(?P<ids>[^\]\n]+)\]?",
    re.IGNORECASE,
)
_DEBATE_SKIPPED = re.compile(r"DEBATE_SKIPPED\s*:\s*true", re.IGNORECASE)
# Post-debate winner field
_WINNER = re.compile(
    r"WINNER\s*:\s*(?P<side>optimist|skeptic|tie)",
    re.IGNORECASE,
)
_RATIONALE = re.compile(
    r"RATIONALE\s*:\s*(?P<text>.+?)(?=\nVERDICT\s*:|\Z)",
    re.IGNORECASE | re.DOTALL,
)
_SID_TOKEN = re.compile(r"S\d+", re.IGNORECASE)

_EDITOR_VERDICT = re.compile(
    r"EDITOR_VERDICT\s*:\s*(APPROVED|REVISE)\s*[:\-]?\s*(.*)",
    re.IGNORECASE | re.DOTALL,
)

# Source-block parser for researcher findings
# Tolerant: matches each "### Source:" block until "---" or next "### Source:" or EOF
_SOURCE_BLOCK = re.compile(
    r"###\s*Source:\s*(?:\[?TYPE\s*:\s*(?P<type>web|academic|counter)\]?\s*)?(?P<title>[^\n]+)\n"
    r"(?P<body>.*?)(?=\n---|\n###\s*Source:|\Z)",
    re.DOTALL | re.IGNORECASE,
)

_FIELD_URL = re.compile(r"^\s*[-*]\s*URL\s*[:\-]\s*(?P<v>\S.+?)\s*$", re.IGNORECASE | re.MULTILINE)
_FIELD_AUTHORS = re.compile(
    r"^\s*[-*]\s*(?:Authors?(?:/site)?|Site|Author)\s*[:\-]\s*(?P<v>.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_FIELD_YEAR = re.compile(r"^\s*[-*]\s*Year\s*[:\-]\s*(?P<v>\d{4}|n\.?d\.?)\s*$", re.IGNORECASE | re.MULTILINE)
_FIELD_VENUE = re.compile(r"^\s*[-*]\s*Venue\s*[:\-]\s*(?P<v>.+?)\s*$", re.IGNORECASE | re.MULTILINE)
_FIELD_CLAIM = re.compile(r"^\s*[-*]\s*Key\s+claim\s*[:\-]\s*(?P<v>.+?)\s*$", re.IGNORECASE | re.MULTILINE)


class AutoGenOrchestrator:
    """
    4-stage deep-research orchestrator.

    Stage 1: Planner decomposes query → JSON sub_questions.
    Stage 2: web/academic/counter researchers run in PARALLEL (asyncio.gather).
    Stage 3: Optimist→Skeptic→ResearchManager debate, looping up to 2 iterations
             if the manager verdict is NEEDS_MORE (one targeted research round
             between iterations).
    Stage 4: Writer drafts with [S\\d+] citations; Editor reviews; up to 1 revise
             cycle if EDITOR_VERDICT: REVISE.

    Public API:
        process_query(query, max_rounds=25) -> dict (sync wrapper)
        process_query_async(query, max_rounds=25) -> dict
        visualize_workflow() -> str
        get_agent_descriptions() -> dict[str, str]

    Hooks (set externally; Phase 4 wires guardrails):
        self.input_guardrail
        self.output_guardrail
        self.safety_manager
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = logger

        self.logger.info("Creating model client and agent team...")
        self.model_client = create_model_client(config)
        self.agents: Dict[str, AssistantAgent] = create_agents(config, self.model_client)
        self.logger.info("Agent team ready (%d agents): %s",
                         len(self.agents), ", ".join(self.agents.keys()))

        # Phase-4 guardrails
        if config.get("safety", {}).get("enabled", True):
            self.safety_manager = SafetyManager(config)
            self.input_guardrail = InputGuardrail(config, model_client=self.model_client)
            self.output_guardrail = OutputGuardrail(config)
        else:
            self.safety_manager = None
            self.input_guardrail = None
            self.output_guardrail = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_query(self, query: str, max_rounds: int = 25, progress_callback=None) -> Dict[str, Any]:
        """Synchronous wrapper for process_query_async."""
        return asyncio.run(self.process_query_async(query, max_rounds, progress_callback))

    async def process_query_async(self, query: str, max_rounds: int = 25, progress_callback=None) -> Dict[str, Any]:
        """Run the full 4-stage pipeline. See module docstring for flow.

        progress_callback: optional callable(snapshot: dict) called after each
        agent turn completes. The snapshot dict contains:
            agent, stage, role, history (list), sources (dict), elapsed (s),
            debate_rounds, revisions, status="running".
        Exceptions from the callback are swallowed so they never abort the
        pipeline.
        """
        start = time.monotonic()
        registry = SourceRegistry()
        history: List[Dict[str, Any]] = []
        debate_rounds = 0
        revisions = 0
        safety_events: List[Dict[str, Any]] = []

        def record(agent: str, content: str, stage: str, role: str = "agent"):
            cleaned = strip_thinking(content) if isinstance(content, str) else str(content)
            history.append({
                "agent": agent,
                "source": agent,  # backward-compat key for example_autogen.py
                "content": cleaned,
                "timestamp": datetime.utcnow().isoformat(),
                "stage": stage,
                "role": role,
            })
            if progress_callback is not None and role != "user":
                try:
                    progress_callback({
                        "agent": agent,
                        "stage": stage,
                        "role": role,
                        "history": list(history),
                        "sources": registry.as_dict(),
                        "elapsed": round(time.monotonic() - start, 2),
                        "debate_rounds": debate_rounds,
                        "revisions": revisions,
                        "status": "running",
                    })
                except Exception as _cb_exc:
                    print(f"[orchestrator] progress_callback error: {_cb_exc}", flush=True)

        record("user", query, "input", role="user")

        # ---------- Pre-query guardrail (Phase 4) ----------
        if self.safety_manager is not None:
            query_id = f"q_{int(start * 1000)}"
            self.safety_manager.reset_for_query(query_id)
            try:
                passed, event = self.safety_manager.check_input(query, self.input_guardrail)
                if not passed:
                    return {
                        "query": query,
                        "response": f"REFUSED: {event.message}",
                        "sources": {},
                        "source_list_apa": [],
                        "conversation_history": history,
                        "safety_events": self.safety_manager.get_events(),
                        "metadata": {
                            "num_messages": len(history),
                            "num_sources": 0,
                            "agents_involved": [],
                            "debate_rounds": 0,
                            "revisions": 0,
                            "total_duration_seconds": round(time.monotonic() - start, 2),
                            "status": "refused",
                            "refusal_category": event.category,
                        },
                    }
            except Exception as exc:  # never crash on guardrail failure
                self.logger.warning("input guardrail raised: %s", exc)

        # ===== STAGE 1: PLANNING =====
        try:
            plan_text = await self._run_single_agent(
                self.agents["planner"],
                f"User query: {query}\n\nProduce the JSON plan now.",
            )
        except Exception as exc:
            self.logger.error("Planner failed: %s", exc, exc_info=True)
            plan_text = ""
        record("planner", plan_text or "[planner returned no text]", "stage_1_planning")
        if self.safety_manager:
            self.safety_manager.set_active_agent("planner")
        sub_questions = self._parse_plan_json(plan_text, fallback_query=query)

        # ===== STAGE 2: PARALLEL EVIDENCE =====
        # Orchestrator calls tools directly (avoids vLLM 400 errors from tool-calling protocol)
        # then feeds raw results as text to each researcher for pure synthesis.

        async def _fetch_web(sq_list: List[Dict[str, Any]], per_q: int = 6) -> List[Dict[str, Any]]:
            out = []
            for sq in sq_list:
                try:
                    results = await asyncio.to_thread(web_search_structured, sq["question"], per_q)
                    out.append({"sub_question_id": sq["id"], "sub_question": sq["question"], "results": results})
                except Exception as exc:
                    self.logger.warning("web fetch failed for sq %s: %s", sq["id"], exc)
                    out.append({"sub_question_id": sq["id"], "sub_question": sq["question"], "results": []})
            return out

        async def _fetch_papers(sq_list: List[Dict[str, Any]], per_q: int = 8) -> List[Dict[str, Any]]:
            # Throttle to avoid OpenAlex/arXiv rate-limiting when 5+ sub-questions fan out.
            out = []
            for i, sq in enumerate(sq_list):
                if i > 0:
                    await asyncio.sleep(0.6)  # 600ms between sub-question fetches
                try:
                    results = await asyncio.to_thread(paper_search_structured, sq["question"], per_q)
                    out.append({"sub_question_id": sq["id"], "sub_question": sq["question"], "results": results})
                except Exception as exc:
                    self.logger.warning("paper fetch failed for sq %s: %s", sq["id"], exc)
                    out.append({"sub_question_id": sq["id"], "sub_question": sq["question"], "results": []})
            return out

        async def _fetch_counter(sq_list: List[Dict[str, Any]], per_q: int = 4) -> List[Dict[str, Any]]:
            out = []
            for sq in sq_list:
                inverted_q = sq["question"] + " limitations criticism failure cases skeptical view"
                combined: List[Dict[str, Any]] = []
                try:
                    combined += await asyncio.to_thread(web_search_structured, inverted_q, per_q)
                except Exception as exc:
                    self.logger.warning("counter web fetch failed for sq %s: %s", sq["id"], exc)
                try:
                    papers = await asyncio.to_thread(paper_search_structured, inverted_q, per_q)
                    # Normalize paper fields to match web result shape
                    for p in papers:
                        combined.append({
                            "title": p.get("title", ""),
                            "url": p.get("url", ""),
                            "snippet": p.get("abstract", "")[:300],
                            "published_date": str(p.get("year", "")),
                            "authors": p.get("authors", []),
                            "year": p.get("year"),
                            "source_provider": "semantic_scholar",
                        })
                except Exception as exc:
                    self.logger.warning("counter paper fetch failed for sq %s: %s", sq["id"], exc)
                out.append({"sub_question_id": sq["id"], "sub_question": sq["question"], "results": combined})
            return out

        # Run all three fetches concurrently
        web_raw, acad_raw, counter_raw = await asyncio.gather(
            _fetch_web(sub_questions),
            _fetch_papers(sub_questions),
            _fetch_counter(sub_questions),
        )

        # Register sources into registry BEFORE agents see them (deterministic IDs)
        def _register_web_results(sq_blocks: List[Dict[str, Any]]) -> None:
            for blk in sq_blocks:
                for r in blk.get("results", []):
                    if not r.get("url"):
                        continue
                    registry.add({
                        "title": r.get("title", "Untitled"),
                        "url": r["url"],
                        "authors": r.get("authors", []),
                        "year": r.get("published_date") or "n.d.",
                        "venue": r.get("source_provider", ""),
                        "type": "web",
                        "key_claim": r.get("snippet", "")[:200],
                        "source": "orchestrator",
                        "authority": "UNVERIFIED",
                    })

        def _register_paper_results(sq_blocks: List[Dict[str, Any]]) -> None:
            for blk in sq_blocks:
                for p in blk.get("results", []):
                    if not p.get("url"):
                        continue
                    registry.add({
                        "title": p.get("title", "Untitled"),
                        "url": p["url"],
                        "authors": p.get("authors", []),
                        "year": p.get("year") or "n.d.",
                        "venue": p.get("venue", ""),
                        "type": "academic",
                        "key_claim": (p.get("abstract", "") or "")[:200],
                        "source": "orchestrator",
                        "authority": "UNVERIFIED",
                    })

        def _register_counter_results(sq_blocks: List[Dict[str, Any]]) -> None:
            for blk in sq_blocks:
                for r in blk.get("results", []):
                    if not r.get("url"):
                        continue
                    registry.add({
                        "title": r.get("title", "Untitled"),
                        "url": r["url"],
                        "authors": r.get("authors", []),
                        "year": r.get("published_date") or r.get("year") or "n.d.",
                        "venue": r.get("source_provider", ""),
                        "type": "counter",
                        "key_claim": r.get("snippet", "")[:200],
                        "source": "orchestrator",
                        "authority": "UNVERIFIED",
                    })

        _register_web_results(web_raw)
        _register_paper_results(acad_raw)
        _register_counter_results(counter_raw)

        self.logger.info("Stage 2 fetched: %d web, %d acad, %d counter blocks → %d sources registered",
                         len(web_raw), len(acad_raw), len(counter_raw), len(registry.all()))

        # Format raw results as text for each researcher (with pre-assigned [S#] IDs)
        web_input = "Raw web search results to synthesize:\n\n" + self._format_raw_for_researcher(
            web_raw, "web", registry
        )
        acad_input = "Raw academic search results to synthesize:\n\n" + self._format_raw_for_researcher(
            acad_raw, "academic", registry
        )
        counter_input = "Raw counter-evidence search results to synthesize (TYPE: counter for all findings):\n\n" + self._format_raw_for_researcher(
            counter_raw, "counter", registry
        )

        # Run researchers as pure synthesizers (no tool calls needed)
        web_task = self._run_single_agent(self.agents["web_researcher"], web_input)
        acad_task = self._run_single_agent(self.agents["academic_researcher"], acad_input)
        counter_task = self._run_single_agent(self.agents["counter_evidence"], counter_input)
        web_out, acad_out, counter_out = await asyncio.gather(
            web_task, acad_task, counter_task, return_exceptions=False
        )

        record("web_researcher", web_out, "stage_2_evidence")
        record("academic_researcher", acad_out, "stage_2_evidence")
        record("counter_evidence", counter_out, "stage_2_evidence")
        if self.safety_manager:
            self.safety_manager.set_active_agent("counter_evidence")
        # Sources already in registry — no re-extraction needed

        # ===== STAGE 3: DEBATE LOOP =====
        # Path C Fix 4A: bull/bear restructure.
        #   (1) RM in PRE-DEBATE mode picks ONE contested claim + supporting + opposing source IDs.
        #   (2) If no contested claim: skip debate, set debate_skipped=True for writer.
        #   (3) Otherwise: Optimist argues FOR the claim using only supporting sources.
        #       Skeptic argues AGAINST using only opposing sources.
        #   (4) RM in POST-DEBATE mode picks WINNER + emits standard VERDICT.
        debate_findings = (
            f"=== WEB RESEARCHER ===\n{web_out}\n\n"
            f"=== ACADEMIC RESEARCHER ===\n{acad_out}\n\n"
            f"=== COUNTER-EVIDENCE HUNTER ===\n{counter_out}"
        )
        mgr_out = ""  # ensure defined for Stage 4 even if debate skipped
        debate_verdict_for_writer = ""  # propagates RM's WINNER + RATIONALE to writer
        debate_skipped = False
        debate_claim = ""
        supporting_ids: List[str] = []
        opposing_ids: List[str] = []

        for debate_iter in range(2):
            debate_rounds += 1
            iter_label = f"stage_3_debate_r{debate_iter + 1}"

            # ---------- 3.1 Pre-debate claim selection ----------
            pre_debate_out = await self._run_single_agent(
                self.agents["research_manager"],
                self._format_pre_debate_input(query, sub_questions, debate_findings, registry),
            )
            record("research_manager", pre_debate_out, iter_label + "_claim_selection")
            if self.safety_manager:
                self.safety_manager.set_active_agent("research_manager")

            debate_claim, supporting_ids, opposing_ids, debate_skipped = (
                self._parse_pre_debate_output(pre_debate_out, registry)
            )

            if debate_skipped:
                self.logger.info(
                    "RM declared debate_skipped (no contested claim with both sides). "
                    "Skipping Optimist/Skeptic; writer will see debate_skipped=true."
                )
                # Still emit a synthesis-direction message so writer has guidance.
                # Use RM as a final approver of the no-debate path.
                mgr_out = (
                    f"DEBATE_SKIPPED: true\n"
                    f"RATIONALE_FOR_SKIP: {strip_thinking(pre_debate_out)[:600]}\n"
                    f"VERDICT: APPROVED"
                )
                debate_verdict_for_writer = (
                    "DEBATE SKIPPED — no contested claim with both supporting AND opposing "
                    "sources was found in the evidence base. Writer should OMIT the "
                    "'Active debates and contested points' section per WRITER_PROMPT's "
                    "section-conditionality rule."
                )
                break

            # ---------- 3.2 Optimist argues FOR claim ----------
            opt_out = await self._run_single_agent(
                self.agents["optimist"],
                self._format_optimist_input(
                    query, debate_claim, supporting_ids, debate_findings, registry,
                ),
            )
            record("optimist", opt_out, iter_label)
            if self.safety_manager:
                self.safety_manager.set_active_agent("optimist")

            # ---------- 3.3 Skeptic argues AGAINST claim ----------
            skp_out = await self._run_single_agent(
                self.agents["skeptic"],
                self._format_skeptic_input(
                    query, debate_claim, opposing_ids, debate_findings, registry, opt_out,
                ),
            )
            record("skeptic", skp_out, iter_label)
            if self.safety_manager:
                self.safety_manager.set_active_agent("skeptic")

            # ---------- 3.4 RM post-debate: WINNER + VERDICT ----------
            mgr_out = await self._run_single_agent(
                self.agents["research_manager"],
                self._format_post_debate_input(
                    query, sub_questions, debate_claim,
                    supporting_ids, opposing_ids, opt_out, skp_out, registry,
                ),
            )
            record("research_manager", mgr_out, iter_label)
            if self.safety_manager:
                self.safety_manager.set_active_agent("research_manager")

            winner, rationale = self._parse_winner(mgr_out)
            debate_verdict_for_writer = (
                f"DEBATE CLAIM: {debate_claim}\n"
                f"SUPPORTING_SOURCES: {supporting_ids}\n"
                f"OPPOSING_SOURCES: {opposing_ids}\n"
                f"WINNER: {winner}\n"
                f"RATIONALE: {rationale}"
            )

            verdict, target_id = self._parse_manager_verdict(mgr_out)

            if verdict == "APPROVED":
                break

            # NEEDS_MORE — run targeted research IF we still have an iteration left
            if debate_iter < 1:
                target_sq = next(
                    (sq for sq in sub_questions if sq.get("id") == target_id),
                    sub_questions[0],
                )
                # Fetch targeted results via orchestrator (same pattern as Stage 2)
                t_web_raw, t_acad_raw = await asyncio.gather(
                    _fetch_web([target_sq], per_q=6),
                    _fetch_papers([target_sq], per_q=8),
                )
                _register_web_results(t_web_raw)
                _register_paper_results(t_acad_raw)

                t_web_input = (
                    f"Targeted research for sub-question #{target_sq.get('id', '?')}: "
                    f"{target_sq.get('question', query)}\n\n"
                    "Raw web search results:\n\n"
                    + self._format_raw_for_researcher(t_web_raw, "web", registry)
                )
                t_acad_input = (
                    f"Targeted research for sub-question #{target_sq.get('id', '?')}: "
                    f"{target_sq.get('question', query)}\n\n"
                    "Raw academic paper results:\n\n"
                    + self._format_raw_for_researcher(t_acad_raw, "academic", registry)
                )
                t_web, t_acad = await asyncio.gather(
                    self._run_single_agent(self.agents["web_researcher"], t_web_input),
                    self._run_single_agent(self.agents["academic_researcher"], t_acad_input),
                    return_exceptions=False,
                )
                record("web_researcher", t_web, "stage_3_targeted_research")
                record("academic_researcher", t_acad, "stage_3_targeted_research")
                # Sources already registered above before agents ran

                debate_findings = (
                    debate_findings
                    + f"\n\n=== ROUND 2 TARGETED (sub-question {target_sq.get('id', '?')}) ===\n"
                    + f"--- WEB ---\n{t_web}\n\n--- ACADEMIC ---\n{t_acad}"
                )

        # ===== STAGE 4: WRITING + EDITING =====
        # Path C Fix 4C: pass debate verdict (WINNER + RATIONALE + claim) and
        # debate_skipped flag to the writer so it can correctly populate / omit
        # the "Active debates" section per WRITER_PROMPT's section conditionality.
        writer_input_base = self._format_writer_input(
            query, sub_questions, mgr_out, debate_findings, registry,
            debate_verdict=debate_verdict_for_writer,
            debate_skipped=debate_skipped,
        )

        # ---------- Pre-writer hook (Phase 4) ----------
        if hasattr(self, "pre_writer_hook") and callable(getattr(self, "pre_writer_hook", None)):
            try:
                writer_input_base = await self._maybe_await(
                    self.pre_writer_hook(writer_input_base, registry)
                ) or writer_input_base
            except Exception as exc:
                self.logger.warning("pre_writer_hook raised: %s", exc)

        writer_input = writer_input_base
        draft = ""

        for revise_attempt in range(2):  # initial + 1 revision
            try:
                draft = await self._run_single_agent(self.agents["writer"], writer_input)
            except Exception as exc:
                self.logger.error("Writer failed: %s", exc, exc_info=True)
                draft = "[writer agent failed to produce a draft]"
            record("writer", draft, "stage_4_writing")
            if self.safety_manager:
                self.safety_manager.set_active_agent("writer")

            try:
                editor_out = await self._run_single_agent(
                    self.agents["editor"],
                    self._format_editor_input(query, sub_questions, draft, registry),
                )
            except Exception as exc:
                self.logger.error("Editor failed: %s", exc, exc_info=True)
                editor_out = "EDITOR_VERDICT: APPROVED (editor failed; defaulting to approve)"
            record("editor", editor_out, "stage_4_editing")

            ed_verdict, ed_reason = self._parse_editor_verdict(editor_out)
            if ed_verdict == "APPROVED":
                break
            if revise_attempt == 0:
                revisions += 1
                writer_input = (
                    writer_input_base
                    + "\n\n=== EDITOR FEEDBACK (please REVISE per these notes) ===\n"
                    + ed_reason
                )

        final = strip_thinking(draft) if isinstance(draft, str) else str(draft)

        # ---------- Post-output guardrail (Phase 4) ----------
        if self.safety_manager is not None:
            _output_revised = False
            try:
                passed, out_events, sanitized = self.safety_manager.check_output(
                    final, registry, self.output_guardrail
                )
                # If any event requests a revise, re-prompt writer ONCE
                needs_revise = any(e.action == "revise" for e in out_events)
                if needs_revise and not _output_revised:
                    _output_revised = True
                    revisions += 1
                    revise_reason = "; ".join(
                        e.message for e in out_events if e.action == "revise"
                    )
                    self.logger.info("Output guardrail requesting revise: %s", revise_reason)
                    try:
                        revised_draft = await self._run_single_agent(
                            self.agents["writer"],
                            writer_input_base
                            + "\n\n=== OUTPUT GUARDRAIL FEEDBACK (MUST FIX before finalizing) ===\n"
                            + revise_reason
                            + "\nEnsure every factual claim has a valid [S#] citation from the registry. "
                            "Do NOT invent citation IDs. End with DRAFT COMPLETE.",
                        )
                        record("writer", revised_draft, "stage_4_guardrail_revise")
                        revised_editor = await self._run_single_agent(
                            self.agents["editor"],
                            self._format_editor_input(query, sub_questions, revised_draft, registry),
                        )
                        record("editor", revised_editor, "stage_4_guardrail_revise")
                        final = strip_thinking(revised_draft)
                        # Re-run output guardrail on revised output
                        passed2, out_events2, sanitized2 = self.safety_manager.check_output(
                            final, registry, self.output_guardrail
                        )
                        if sanitized2:
                            final = sanitized2
                    except Exception as exc:
                        self.logger.warning("Guardrail revise attempt failed: %s", exc)
                elif sanitized:
                    final = sanitized
            except Exception as exc:
                self.logger.warning("output guardrail raised: %s", exc)

        # ---------- Finalize ----------
        sources_dict = registry.as_dict()
        ordered_ids = sorted(sources_dict.keys(), key=lambda s: int(s[1:]) if s[1:].isdigit() else 0)
        apa_list = [registry.format_apa(sid) for sid in ordered_ids]

        return {
            "query": query,
            "response": final,
            "sources": sources_dict,
            "source_list_apa": apa_list,
            "conversation_history": history,
            "safety_events": self.safety_manager.get_events() if self.safety_manager else safety_events,
            "metadata": {
                "num_messages": len(history),
                "num_sources": len(sources_dict),
                "agents_involved": sorted({h["agent"] for h in history}),
                "debate_rounds": debate_rounds,
                "revisions": revisions,
                "total_duration_seconds": round(time.monotonic() - start, 2),
                "status": "complete",
            },
        }

    # ------------------------------------------------------------------
    # Visualization & metadata helpers
    # ------------------------------------------------------------------

    def visualize_workflow(self) -> str:
        return r"""
4-Stage Deep-Research Workflow
==============================

  [USER QUERY]
       |
       v
  +-------------+
  |  PLANNER    |  Stage 1 — JSON sub_questions
  +-------------+
       |
       v
  +----------+   +--------------+   +-----------------+
  |  WEB     |   |  ACADEMIC    |   |  COUNTER-       |   Stage 2 — PARALLEL
  | RESEARCH |   |  RESEARCH    |   |  EVIDENCE HUNT  |   (asyncio.gather)
  +----------+   +--------------+   +-----------------+
        \              |                     /
         \             v                    /
          +-------- registry merge --------+
                       |
                       v
              +-----------------+
              |    OPTIMIST     |  bull case
              +-----------------+
                       |
                       v
              +-----------------+
              |    SKEPTIC      |  bear case
              +-----------------+         Stage 3 — DEBATE LOOP (<= 2 iters)
                       |
                       v
              +-----------------+
              |  RESEARCH MGR   |  VERDICT: APPROVED | NEEDS_MORE
              +-----------------+
                  |        |
        APPROVED  |        | NEEDS_MORE  -> targeted research, repeat once
                  v        v
              (continue)  (loop)
                  |
                  v
              +-----------------+
              |    WRITER       |  inline [S#] citations
              +-----------------+         Stage 4 — WRITE/EDIT (<= 1 revise)
                       |
                       v
              +-----------------+
              |    EDITOR       |  EDITOR_VERDICT: APPROVED | REVISE
              +-----------------+
                       |
                       v
              [FINAL REPORT + SOURCE LIST]
""".rstrip()

    def get_agent_descriptions(self) -> Dict[str, str]:
        return {
            "planner": "Stage 1: decomposes the query into 5-7 JSON sub-questions.",
            "web_researcher": "Stage 2 (parallel): gathers web evidence per sub-question.",
            "academic_researcher": "Stage 2 (parallel): gathers peer-reviewed papers per sub-question.",
            "counter_evidence": "Stage 2 (parallel): hunts dissenting / cautionary sources.",
            "optimist": "Stage 3: argues the strongest case for the emerging consensus.",
            "skeptic": "Stage 3: stress-tests the optimist's case and flags weak evidence.",
            "research_manager": "Stage 3: adjudicates the debate and issues APPROVED / NEEDS_MORE.",
            "writer": "Stage 4: produces the inline-cited Markdown report.",
            "editor": "Stage 4: reviews the draft for coverage and citation completeness.",
        }

    # ------------------------------------------------------------------
    # Internal: agent invocation
    # ------------------------------------------------------------------

    async def _run_single_agent(self, agent: AssistantAgent, content: str) -> str:
        """Invoke ONE agent with a single user message; return its assistant text."""
        try:
            response = await agent.on_messages(
                [TextMessage(content=content, source="user")],
                cancellation_token=CancellationToken(),
            )
        except Exception as exc:
            self.logger.warning("Agent %s raised: %s", getattr(agent, "name", "?"), exc)
            return f"[agent {getattr(agent, 'name', '?')} error: {exc}]"

        msg = getattr(response, "chat_message", None)
        if msg is None:
            return ""
        text = getattr(msg, "content", None)
        if text is None:
            return str(msg)
        if isinstance(text, str):
            return text
        # If content is a list of message parts, join their str repr
        try:
            return "\n".join(str(part) for part in text)
        except Exception:
            return str(text)

    @staticmethod
    async def _maybe_await(value):
        """Await value if awaitable, else return as-is. Lets hooks be sync or async."""
        if asyncio.iscoroutine(value) or asyncio.isfuture(value):
            return await value
        return value

    # ------------------------------------------------------------------
    # Internal: planner JSON parsing
    # ------------------------------------------------------------------

    def _parse_plan_json(self, text: str, fallback_query: str) -> List[Dict[str, Any]]:
        """Extract sub_questions list from planner output. Tolerant fallback."""
        if not text:
            self.logger.warning("Empty planner text — falling back to single sub-question.")
            return self._fallback_plan(fallback_query)

        cleaned = strip_thinking(text)
        candidates: List[str] = []
        for m in _JSON_FENCE.finditer(cleaned):
            candidates.append(m.group(1))
        for m in _BARE_JSON.finditer(cleaned):
            candidates.append(m.group(1))

        for raw in candidates:
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            sqs = obj.get("sub_questions") if isinstance(obj, dict) else None
            if isinstance(sqs, list) and sqs:
                normalized = []
                for i, sq in enumerate(sqs, 1):
                    if not isinstance(sq, dict):
                        continue
                    normalized.append({
                        "id": int(sq.get("id", i)) if str(sq.get("id", i)).isdigit() else i,
                        "question": str(sq.get("question", "")).strip() or f"Sub-question {i}",
                        "rationale": str(sq.get("rationale", "")).strip(),
                    })
                if normalized:
                    return normalized

        self.logger.warning("Planner JSON not parseable — falling back to single sub-question.")
        return self._fallback_plan(fallback_query)

    @staticmethod
    def _fallback_plan(query: str) -> List[Dict[str, Any]]:
        return [{
            "id": 1,
            "question": query,
            "rationale": "fallback: planner output was missing/unparseable",
        }]

    # ------------------------------------------------------------------
    # Internal: prompt assembly
    # ------------------------------------------------------------------

    @staticmethod
    def _format_raw_for_researcher(
        sq_blocks: List[Dict[str, Any]],
        source_type: str,
        registry: "SourceRegistry",
    ) -> str:
        """
        Format raw tool results (list of sub-question blocks) as text for a researcher agent.
        Each result is annotated with its pre-assigned [S#] ID from the registry.
        The agent must use these exact IDs — it must not renumber.
        """
        lines: List[str] = []
        for blk in sq_blocks:
            sq_id = blk.get("sub_question_id", "?")
            sq_text = blk.get("sub_question", "")
            results = blk.get("results", [])
            lines.append(f"Sub-question {sq_id}: {sq_text}")
            if not results:
                lines.append("  (no results retrieved for this sub-question)")
                lines.append("")
                continue
            lines.append("Sources found:")
            for r in results:
                url = r.get("url", "")
                # Look up the registry ID assigned when we registered this source
                assigned_id = registry._url_index.get(url, "?") if url else "?"
                title = r.get("title", "Untitled")
                year = r.get("published_date") or r.get("year") or "n.d."
                authors = r.get("authors", [])
                authors_str = ", ".join(authors[:3]) if authors else r.get("source_provider", "")
                snippet = r.get("snippet") or r.get("abstract") or ""
                snippet = snippet[:300]
                lines.append(f"- [{assigned_id}] {title} ({year})")
                if authors_str:
                    lines.append(f"  Authors/site: {authors_str}")
                if url:
                    lines.append(f"  URL: {url}")
                if snippet:
                    lines.append(f"  Snippet/Abstract: {snippet}")
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _format_research_brief(query: str, sub_questions: List[Dict[str, Any]]) -> str:
        """Legacy helper — kept for backward compat; not called in main Stage 2 flow."""
        lines = [f'Research brief for query: "{query}"', "", "Sub-questions to investigate:"]
        for sq in sub_questions:
            lines.append(f"{sq['id']}. {sq['question']}")
            if sq.get("rationale"):
                lines.append(f"   Rationale: {sq['rationale']}")
        lines.append("")
        lines.append(
            "For each sub-question, synthesize the provided raw results in the structured "
            "format defined in your system prompt. End with RESEARCH COMPLETE."
        )
        return "\n".join(lines)

    @staticmethod
    def _format_debate_input(
        query: str,
        sub_questions: List[Dict[str, Any]],
        findings: str,
        registry: SourceRegistry,
        role: str,
        optimist_msg: Optional[str] = None,
    ) -> str:
        sq_lines = "\n".join(f"  {sq['id']}. {sq['question']}" for sq in sub_questions)
        sources_md = format_sources_for_writer(registry)
        parts = [
            f'Original research query: "{query}"',
            "",
            "Sub-questions:",
            sq_lines,
            "",
            "=== Stage-2 evidence (from web, academic, and counter researchers) ===",
            findings,
            "",
            "=== Sources currently registered (S# IDs you may reference) ===",
            sources_md,
        ]
        if role == "skeptic" and optimist_msg:
            parts += [
                "",
                "=== Optimist's argument (your job is to stress-test it) ===",
                strip_thinking(optimist_msg),
            ]
        parts += [
            "",
            "Now produce your turn per your system prompt. End with TURN COMPLETE.",
        ]
        return "\n".join(parts)

    @staticmethod
    def _format_manager_input(
        query: str,
        sub_questions: List[Dict[str, Any]],
        optimist_msg: str,
        skeptic_msg: str,
        registry: SourceRegistry,
    ) -> str:
        sq_lines = "\n".join(f"  {sq['id']}. {sq['question']}" for sq in sub_questions)
        return (
            f'Original research query: "{query}"\n\n'
            f"Sub-questions:\n{sq_lines}\n\n"
            f"=== Optimist's case ===\n{strip_thinking(optimist_msg)}\n\n"
            f"=== Skeptic's critique ===\n{strip_thinking(skeptic_msg)}\n\n"
            f"=== Source registry summary ({len(registry.all())} sources) ===\n"
            f"{format_sources_for_writer(registry)}\n\n"
            "Adjudicate per your system prompt. Output EXACTLY one verdict line: "
            "'VERDICT: APPROVED' or 'VERDICT: NEEDS_MORE'. If NEEDS_MORE, name the "
            "specific sub-question id that needs more evidence."
        )

    # ------------------------------------------------------------------
    # Path C Fix 4A: bull/bear debate prompt formatters
    # ------------------------------------------------------------------

    @staticmethod
    def _format_pre_debate_input(
        query: str,
        sub_questions: List[Dict[str, Any]],
        findings: str,
        registry: SourceRegistry,
    ) -> str:
        """Pre-debate: ask RM to pick ONE contested claim with both sides cited."""
        sq_lines = "\n".join(f"  {sq['id']}. {sq['question']}" for sq in sub_questions)
        truncated_findings = findings[:6000] if findings and len(findings) > 6000 else (findings or "")
        return (
            f"=== MODE: PRE-DEBATE (claim selection) ===\n\n"
            f'Original research query: "{query}"\n\n'
            f"Sub-questions:\n{sq_lines}\n\n"
            f"=== Stage-2 findings (web + academic + counter-evidence) ===\n"
            f"{truncated_findings}\n\n"
            f"=== Source registry ({len(registry.all())} sources) ===\n"
            f"{format_sources_for_writer(registry)}\n\n"
            "Your task: pick ONE specific claim from the evidence with BOTH "
            "supporting and opposing source IDs. Output the CLAIM_FOR_DEBATE / "
            "SUPPORTING_SOURCES / OPPOSING_SOURCES / RATIONALE_FOR_SELECTION block "
            "per MODE 1 of your system prompt. If no contested claim exists, output "
            "CLAIM_FOR_DEBATE: NONE and DEBATE_SKIPPED: true with a one-line rationale."
        )

    @staticmethod
    def _format_optimist_input(
        query: str,
        debate_claim: str,
        supporting_ids: List[str],
        findings: str,
        registry: SourceRegistry,
    ) -> str:
        """Optimist: argue FOR the claim using only the supporting sources."""
        sources_md = format_sources_for_writer(registry)
        truncated_findings = findings[:5000] if findings and len(findings) > 5000 else (findings or "")
        sids_str = ", ".join(supporting_ids) if supporting_ids else "(none specified — use any source)"
        return (
            f'Original research query: "{query}"\n\n'
            f"=== ASSIGNED CLAIM (you argue FOR this claim) ===\n{debate_claim}\n\n"
            f"=== Supporting source IDs you may cite ===\n{sids_str}\n\n"
            f"=== Source registry (cite only the IDs assigned above) ===\n{sources_md}\n\n"
            f"=== Stage-2 findings (background; cite only assigned sources) ===\n"
            f"{truncated_findings}\n\n"
            "Per your system prompt: argue the STRONGEST POSSIBLE CASE that the "
            "assigned claim is TRUE. Use only the supporting sources. Do NOT concede "
            "the central point. End with: OPTIMIST CASE COMPLETE."
        )

    @staticmethod
    def _format_skeptic_input(
        query: str,
        debate_claim: str,
        opposing_ids: List[str],
        findings: str,
        registry: SourceRegistry,
        optimist_msg: str,
    ) -> str:
        """Skeptic: argue AGAINST the claim using only the opposing sources."""
        sources_md = format_sources_for_writer(registry)
        truncated_findings = findings[:5000] if findings and len(findings) > 5000 else (findings or "")
        sids_str = ", ".join(opposing_ids) if opposing_ids else "(none specified — use any counter source)"
        return (
            f'Original research query: "{query}"\n\n'
            f"=== ASSIGNED CLAIM (you argue AGAINST this claim) ===\n{debate_claim}\n\n"
            f"=== Opposing source IDs you may cite ===\n{sids_str}\n\n"
            f"=== Source registry (cite only the IDs assigned above) ===\n{sources_md}\n\n"
            f"=== Stage-2 findings (background; cite only assigned sources) ===\n"
            f"{truncated_findings}\n\n"
            f"=== Optimist's defense (your job is to refute it) ===\n"
            f"{strip_thinking(optimist_msg)}\n\n"
            "Per your system prompt: argue the STRONGEST POSSIBLE CASE that the "
            "assigned claim is FALSE / incomplete / methodologically unsupported. "
            "Use only the opposing sources. Do NOT concede that the Optimist is "
            "correct. End with: SKEPTIC CASE COMPLETE."
        )

    @staticmethod
    def _format_post_debate_input(
        query: str,
        sub_questions: List[Dict[str, Any]],
        debate_claim: str,
        supporting_ids: List[str],
        opposing_ids: List[str],
        optimist_msg: str,
        skeptic_msg: str,
        registry: SourceRegistry,
    ) -> str:
        """Post-debate: ask RM to judge winner + emit pipeline VERDICT."""
        sq_lines = "\n".join(f"  {sq['id']}. {sq['question']}" for sq in sub_questions)
        return (
            f"=== MODE: POST-DEBATE (winner judgement + verdict) ===\n\n"
            f'Original research query: "{query}"\n\n'
            f"Sub-questions:\n{sq_lines}\n\n"
            f"=== Original CLAIM_FOR_DEBATE ===\n{debate_claim}\n"
            f"SUPPORTING_SOURCES: {supporting_ids}\n"
            f"OPPOSING_SOURCES: {opposing_ids}\n\n"
            f"=== Optimist's case (FOR the claim) ===\n{strip_thinking(optimist_msg)}\n\n"
            f"=== Skeptic's case (AGAINST the claim) ===\n{strip_thinking(skeptic_msg)}\n\n"
            f"=== Source registry summary ({len(registry.all())} sources) ===\n"
            f"{format_sources_for_writer(registry)}\n\n"
            "Per MODE 2 of your system prompt: output WINNER (optimist|skeptic|tie) + "
            "RATIONALE referencing specific [Sn] used by each side, then VERDICT "
            "(APPROVED or NEEDS_MORE with sub-question id). Do NOT hedge."
        )

    @staticmethod
    def _format_writer_input(
        query: str,
        sub_questions: List[Dict[str, Any]],
        manager_msg: str,
        findings: str,
        registry: SourceRegistry,
        debate_verdict: str = "",
        debate_skipped: bool = False,
    ) -> str:
        sq_lines = "\n".join(f"  {sq['id']}. {sq['question']}" for sq in sub_questions)

        # Fix 2 (2026-05-07): Cap sources to top 10, snippet 150 chars; truncate
        # debate transcript to 800 chars per message; final assembled prompt
        # capped at ~30k chars to fit Qwen3-8B's 40k token context window.
        all_sources = registry.all()
        sources_for_writer = all_sources[:10]  # max 10 sources (was 12)
        source_lines = ["**Sources:**"]
        for s in sources_for_writer:
            sid = s.get("_id", "?")
            title = s.get("title", "Untitled")
            url = s.get("url", "")
            year = s.get("year", "n.d.")
            snippet = s.get("snippet", s.get("abstract", ""))[:150]  # 150 chars (was 200)
            line = f"- [{sid}] {title} ({year})"
            if url:
                line += f" — {url}"
            if snippet:
                line += f"\n  Preview: {snippet}"
            source_lines.append(line)
        if len(all_sources) > 10:
            source_lines.append(f"  _(and {len(all_sources) - 10} more sources omitted to fit context)_")
        sources_text = "\n".join(source_lines)

        # Truncate the debate manager's verdict + findings transcript to keep
        # the writer prompt within ~30k chars total.
        truncated_manager = _truncate_msg(manager_msg, 800)
        truncated_findings = findings[:8000] if findings and len(findings) > 8000 else (findings or "")
        if findings and len(findings) > 8000:
            truncated_findings += "\n... [findings truncated to fit context]"

        # Path C Fix 4C: include debate verdict block so writer narrates the REAL
        # debate (claim + winner + rationale) rather than inventing one.
        debate_block = ""
        if debate_skipped:
            debate_block = (
                "=== Debate verdict (Stage 3) ===\n"
                "debate_skipped: true\n"
                "Per WRITER_PROMPT section conditionality, OMIT the 'Active debates "
                "and contested points' section.\n\n"
            )
        elif debate_verdict:
            debate_block = (
                "=== Debate verdict (Stage 3) ===\n"
                f"{_truncate_msg(debate_verdict, 1200)}\n\n"
            )

        # Assemble parts; if total > 30k chars, drop sources from the bottom
        # (highest IDs first) until under.
        header = (
            f'Original research query: "{query}"\n\n'
            f"Sub-questions to cover:\n{sq_lines}\n\n"
            f"=== Research Manager's approved synthesis direction ===\n"
            f"{truncated_manager}\n\n"
            f"{debate_block}"
        )
        sources_block = (
            f"=== Source registry — ONLY cite these IDs ===\n"
            f"{sources_text}\n\n"
        )
        evidence_block = (
            f"=== Raw evidence (background; do not quote verbatim) ===\n{truncated_findings}\n\n"
        )
        footer = (
            "Produce the report per your system prompt. CRITICAL: every factual "
            "claim must end with one or more [S#] citations matching the registry. "
            "Do NOT invent S# IDs that are not in the registry. End with DRAFT COMPLETE."
        )

        # Drop sources from the bottom if assembled prompt still > 30k chars.
        prompt = header + sources_block + evidence_block + footer
        if len(prompt) > 30000:
            # Rebuild with progressively fewer sources.
            for keep in range(len(sources_for_writer) - 1, 0, -1):
                pruned = sources_for_writer[:keep]
                pruned_lines = ["**Sources:**"]
                for s in pruned:
                    sid = s.get("_id", "?")
                    title = s.get("title", "Untitled")
                    url = s.get("url", "")
                    year = s.get("year", "n.d.")
                    snippet = s.get("snippet", s.get("abstract", ""))[:150]
                    line = f"- [{sid}] {title} ({year})"
                    if url:
                        line += f" — {url}"
                    if snippet:
                        line += f"\n  Preview: {snippet}"
                    pruned_lines.append(line)
                pruned_lines.append(
                    f"  _(and {len(all_sources) - keep} more sources omitted to fit context)_"
                )
                sources_block_pruned = (
                    f"=== Source registry — ONLY cite these IDs ===\n"
                    f"{chr(10).join(pruned_lines)}\n\n"
                )
                prompt = header + sources_block_pruned + evidence_block + footer
                if len(prompt) <= 30000:
                    logger.warning(
                        "writer prompt context-truncation: kept %d/%d sources to fit 30k chars",
                        keep, len(all_sources),
                    )
                    break
            else:
                # Last resort: hard-cap whole prompt
                prompt = _truncate_for_context(
                    [header, sources_block, evidence_block, footer], max_chars=30000
                )
                logger.warning(
                    "writer prompt hard-capped at 30k chars (registry too large to fit)"
                )

        logger.info("writer prompt length: %d chars (%d sources kept)", len(prompt), len(sources_for_writer))
        return prompt

    @staticmethod
    def _format_editor_input(
        query: str,
        sub_questions: List[Dict[str, Any]],
        draft: str,
        registry: SourceRegistry,
    ) -> str:
        sq_lines = "\n".join(f"  {sq['id']}. {sq['question']}" for sq in sub_questions)
        return (
            f'Original research query: "{query}"\n\n'
            f"Sub-questions the draft must cover:\n{sq_lines}\n\n"
            f"=== Source registry ===\n{format_sources_for_writer(registry)}\n\n"
            f"=== Writer's draft ===\n{strip_thinking(draft)}\n\n"
            "Review per your system prompt. Output EXACTLY one verdict line: "
            "'EDITOR_VERDICT: APPROVED' or 'EDITOR_VERDICT: REVISE: <specific notes>'."
        )

    # ------------------------------------------------------------------
    # Internal: verdict parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_pre_debate_output(
        text: str,
        registry: SourceRegistry,
    ) -> Tuple[str, List[str], List[str], bool]:
        """Parse RM's pre-debate output. Returns (claim, supporting_ids, opposing_ids, debate_skipped).

        Path C Fix 4A: tolerant parser. If RM declared DEBATE_SKIPPED or
        could not find a contested claim with both sides, returns
        (claim="", [], [], debate_skipped=True). Otherwise returns the parsed
        claim string and the source-ID lists (filtered against registry).
        """
        if not text:
            return ("", [], [], True)

        cleaned = strip_thinking(text)

        # Check for explicit DEBATE_SKIPPED flag
        if _DEBATE_SKIPPED.search(cleaned):
            return ("", [], [], True)

        # Extract CLAIM_FOR_DEBATE
        m_claim = _CLAIM_FOR_DEBATE.search(cleaned)
        claim_raw = (m_claim.group("claim").strip() if m_claim else "")

        # If RM said NONE for the claim, treat as skipped
        if not claim_raw or claim_raw.strip().upper().startswith("NONE"):
            return ("", [], [], True)

        # Strip trailing meta-fields that may have leaked into the claim regex
        # (since claim regex stops at next [A-Z_]+: but some models add prose).
        for stop in ["\n\n", "SUPPORTING_SOURCES", "OPPOSING_SOURCES"]:
            idx = claim_raw.find(stop)
            if idx > 0:
                claim_raw = claim_raw[:idx].strip()

        # Extract supporting IDs
        registered_ids = set(registry.as_dict().keys())
        supporting_ids: List[str] = []
        opposing_ids: List[str] = []
        m_sup = _SUPPORTING_SOURCES.search(cleaned)
        if m_sup:
            for tok in _SID_TOKEN.findall(m_sup.group("ids")):
                sid = tok.upper()
                if sid in registered_ids and sid not in supporting_ids:
                    supporting_ids.append(sid)
        m_opp = _OPPOSING_SOURCES.search(cleaned)
        if m_opp:
            for tok in _SID_TOKEN.findall(m_opp.group("ids")):
                sid = tok.upper()
                if sid in registered_ids and sid not in opposing_ids:
                    opposing_ids.append(sid)

        # Need both sides for a real debate
        if not supporting_ids or not opposing_ids:
            return (claim_raw, supporting_ids, opposing_ids, True)

        return (claim_raw, supporting_ids, opposing_ids, False)

    @staticmethod
    def _parse_winner(text: str) -> Tuple[str, str]:
        """Parse RM's post-debate WINNER + RATIONALE. Returns (side, rationale_text).

        Side is one of: 'optimist', 'skeptic', 'tie', or 'unknown' on parse failure.
        """
        if not text:
            return ("unknown", "")
        cleaned = strip_thinking(text)
        m_winner = _WINNER.search(cleaned)
        side = (m_winner.group("side").lower() if m_winner else "unknown")
        m_rat = _RATIONALE.search(cleaned)
        rationale = (m_rat.group("text").strip() if m_rat else "")
        # Cap rationale to 800 chars to avoid bloating writer prompt
        if len(rationale) > 800:
            rationale = rationale[:800] + "..."
        return (side, rationale)

    @staticmethod
    def _parse_manager_verdict(text: str) -> Tuple[str, Optional[int]]:
        """Return ('APPROVED', None) or ('NEEDS_MORE', sub_q_id|None)."""
        if not text:
            return ("APPROVED", None)  # tolerant: no verdict means we proceed
        cleaned = strip_thinking(text)
        m = _MGR_VERDICT.search(cleaned)
        if not m:
            return ("APPROVED", None)
        verdict = m.group(1).upper()
        if verdict == "APPROVED":
            return ("APPROVED", None)
        # NEEDS_MORE — try to find sub-question id (look AFTER the verdict line first)
        after = cleaned[m.end():]
        sq_match = _MGR_SUBQ.search(after) or _MGR_SUBQ.search(cleaned)
        target_id = int(sq_match.group(1)) if sq_match else None
        return ("NEEDS_MORE", target_id)

    @staticmethod
    def _parse_editor_verdict(text: str) -> Tuple[str, str]:
        """Return ('APPROVED', '') or ('REVISE', reason_text)."""
        if not text:
            return ("APPROVED", "")
        cleaned = strip_thinking(text)
        m = _EDITOR_VERDICT.search(cleaned)
        if not m:
            # If no explicit verdict found, default to APPROVED to avoid infinite revise
            return ("APPROVED", "")
        verdict = m.group(1).upper()
        reason = (m.group(2) or "").strip()
        if verdict == "APPROVED":
            return ("APPROVED", "")
        return ("REVISE", reason or "Editor requested revisions but gave no specifics.")

    # ------------------------------------------------------------------
    # Internal: source extraction from researcher output
    # ------------------------------------------------------------------

    def _extract_sources_from_research_output(
        self,
        text: str,
        registry: SourceRegistry,
        source_type: str = "web",
    ) -> int:
        """
        Parse '### Source: [TYPE: ...] Title' blocks from researcher output and
        register each via SourceRegistry.add(). Tolerant: skips blocks missing URL.
        Returns count added (excluding duplicates).
        """
        if not text:
            return 0
        cleaned = strip_thinking(text)
        added = 0
        for sm in _SOURCE_BLOCK.finditer(cleaned):
            title = (sm.group("title") or "").strip().strip("{}").strip()
            block_type = (sm.group("type") or source_type).lower()
            body = sm.group("body") or ""

            url_m = _FIELD_URL.search(body)
            if not url_m:
                continue
            url = url_m.group("v").strip().strip("()<>")
            # Strip markdown brackets/links
            md_link = re.match(r"\[(.*?)\]\((https?://\S+)\)", url)
            if md_link:
                url = md_link.group(2)
            if not url.lower().startswith(("http://", "https://")):
                continue

            authors_m = _FIELD_AUTHORS.search(body)
            year_m = _FIELD_YEAR.search(body)
            venue_m = _FIELD_VENUE.search(body)
            claim_m = _FIELD_CLAIM.search(body)

            authors_raw = authors_m.group("v").strip() if authors_m else ""
            authors_list: List[str] = []
            if authors_raw:
                # Split on common delimiters; tolerant
                for chunk in re.split(r"[,;]| and ", authors_raw):
                    name = chunk.strip()
                    if name and name.lower() not in {"et al.", "et al", "n/a", "unknown"}:
                        authors_list.append(name)

            year_val: Any = year_m.group("v").strip() if year_m else "n.d."
            if isinstance(year_val, str) and year_val.isdigit():
                try:
                    year_val = int(year_val)
                except ValueError:
                    pass

            source_dict = {
                "title": title or "Untitled",
                "url": url,
                "authors": authors_list,
                "year": year_val,
                "venue": venue_m.group("v").strip() if venue_m else "",
                "type": block_type,
                "key_claim": claim_m.group("v").strip() if claim_m else "",
                "source": "researcher",
                "authority": "UNVERIFIED",  # Phase 4 may verify
            }

            before = len(registry.all())
            registry.add(source_dict)
            if len(registry.all()) > before:
                added += 1

        return added

    # ------------------------------------------------------------------
    # Internal: error helper
    # ------------------------------------------------------------------

    def _error_result(
        self,
        *,
        query: str,
        history: List[Dict[str, Any]],
        registry: SourceRegistry,
        safety_events: List[Dict[str, Any]],
        message: str,
        start: float,
        debate_rounds: int,
        revisions: int,
        status: str,
    ) -> Dict[str, Any]:
        sources_dict = registry.as_dict()
        return {
            "query": query,
            "response": message,
            "sources": sources_dict,
            "source_list_apa": [registry.format_apa(sid) for sid in sources_dict.keys()],
            "conversation_history": history,
            "safety_events": safety_events,
            "error": message,
            "metadata": {
                "num_messages": len(history),
                "num_sources": len(sources_dict),
                "agents_involved": sorted({h["agent"] for h in history}),
                "debate_rounds": debate_rounds,
                "revisions": revisions,
                "total_duration_seconds": round(time.monotonic() - start, 2),
                "status": status,
            },
        }


def demonstrate_usage():
    """Lightweight demo. Real usage is example_autogen.py / Streamlit app."""
    import yaml
    from dotenv import load_dotenv

    load_dotenv()
    with open("config.yaml", "r") as f:
        config = yaml.safe_load(f)
    orch = AutoGenOrchestrator(config)
    print(orch.visualize_workflow())
    for k, v in orch.get_agent_descriptions().items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    demonstrate_usage()
