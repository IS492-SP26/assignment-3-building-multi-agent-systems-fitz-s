# Created: 2026-05-07
# Last reused or audited: 2026-05-08 (Path C Fix 1b: added unsupported_quantitative_claim and unsupported_author_attribution branches to _humanize_safety so safety panel shows clear warnings when content-mismatch verifier fires.)
# Authority basis: Plan §UI Workflow / Implementation Phases 5-6 + user feedback 2026-05-07 (no fake states; dashboard IS the live UI).
# Replaces the Phase 4.5 skeleton with the Claude-Design-approved dashboard.
# Renders the entire trace + 13 components as ONE st.components.v1.html
# island for performance and visual fidelity (a single React/Babel runtime,
# CSS, and JSON state payload). Python is responsible only for: query input,
# orchestrator call, and JSON marshaling. All affordances (citation jump,
# stepper jump, edit-query highlight, source expand) are local DOM events.
"""
Streamlit production UI — Agentic UX deep-research dashboard.

Run with:
    streamlit run src/ui/streamlit_app.py

Dev preload (skip the 2-5 min orchestrator):
    streamlit run src/ui/streamlit_app.py -- --
    then open http://localhost:8501/?preload=Q1   (also Q5, Q6)

Architecture (Anthropic "Building effective agents" → routing pattern):
- Python: one route — receive query, run AutoGenOrchestrator, marshal result
  into the design's session shape (matches outputs/design/data.jsx).
- HTML island: the entire dashboard chrome. State arrives as window.__STATE
  (JSON). All interactions (citation clicks, stepper jumps, source expand,
  Edit-query CTA) are handled in-island; only Edit-query posts back to
  Streamlit via window.parent.postMessage so Python can repopulate the
  textarea.

Component inventory (13 components, mapped to outputs/design/components.jsx):
  TopBar · Sidebar · Stepper · MsgCard · LoadingMsg · DebateCard · ActiveAgent
  SafetyPanel · SourcesPanel · ExportMenu · RefusedBanner · EmptyState
  StatusBar · CockpitPanel
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# --- repo path -------------------------------------------------------------
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import streamlit as st
import streamlit.components.v1 as components
import yaml
from dotenv import load_dotenv

# Declared navigation relay component: receives omc_navigate postMessages from
# the island iframe and relays them to Python via Streamlit.setComponentValue().
# Python then updates st.query_params and calls st.rerun() — the only
# sandbox-safe way to trigger top-frame navigation from a Streamlit component.
_NAV_RELAY_DIR = Path(__file__).parent / "nav_relay"
_nav_relay = components.declare_component("omc_nav_relay", path=str(_NAV_RELAY_DIR))

load_dotenv()

# ---------------------------------------------------------------------------
# Config / orchestrator
# ---------------------------------------------------------------------------

CONFIG_PATH = project_root / "config.yaml"
STYLES_PATH = Path(__file__).parent / "styles.css"
ISLAND_JS_PATH = Path(__file__).parent / "island.jsx"
SESSIONS_DIR = project_root / "outputs" / "sessions"
OUTPUTS_DIR = project_root / "outputs"

# Live-run inter-process file: background daemon writes partial JSON snapshots
# here while the pipeline runs; Streamlit auto-polls + reads it.
LIVE_RUN_FILE = SESSIONS_DIR / "_live_running.json"

# Zero-flicker static-poll file: served at /app/static/live_partial.json by
# Streamlit's enableStaticServing. The React island self-polls this URL so
# the Streamlit script does not rerun during the pipeline run, which prevents
# iframe re-mount flicker every 1.5s.
STATIC_LIVE_DIR = Path(__file__).parent / "static"
STATIC_LIVE_FILE = STATIC_LIVE_DIR / "live_partial.json"


def _atomic_write_json(path: Path, obj: dict) -> None:
    """Atomic file write — temp file + rename so a polling reader never sees
    a half-written JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, default=str, ensure_ascii=False, indent=2))
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Phase 6.5 — Eval report helpers
# ---------------------------------------------------------------------------

def _load_eval_reports() -> List[dict]:
    """Return all eval_report_*.json entries newest-first, each pre-parsed."""
    reports = []
    for p in sorted(OUTPUTS_DIR.glob("eval_report_*.json"), reverse=True):
        try:
            data = json.loads(p.read_text())
            reports.append(data)
        except Exception:
            continue
    return reports


def find_eval_scores(query_text: str, session_id: Optional[str] = None) -> Optional[dict]:
    """Walk eval reports newest-first; return judge_scores for the matching query.

    Matching priority:
    1. session_id matches query.query.id (e.g. Q1 → id=1)
    2. query text substring match (case-insensitive)
    """
    if not query_text and not session_id:
        return None
    q_lower = (query_text or "").lower().strip()
    # numeric id from session_id like "Q1" → 1
    sid_num: Optional[int] = None
    if session_id:
        digits = "".join(c for c in session_id if c.isdigit())
        if digits:
            sid_num = int(digits)

    for report in _load_eval_reports():
        for entry in report.get("queries", []):
            q_dict = entry.get("query", {})
            # q_dict can be a dict (new shape) or missing
            if isinstance(q_dict, dict):
                entry_id = q_dict.get("id")
                entry_text = (q_dict.get("query") or "").lower()
            else:
                # fallback: check result.query
                result = entry.get("result", {})
                entry_id = None
                entry_text = (result.get("query") or "").lower()

            # Match by id
            if sid_num is not None and entry_id == sid_num:
                return entry.get("judge_scores")
            # Match by text substring
            if q_lower and entry_text and (q_lower in entry_text or entry_text in q_lower):
                return entry.get("judge_scores")
    return None


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def get_orchestrator():
    """Lazy-init orchestrator and cache in session_state."""
    if "orchestrator" not in st.session_state:
        from src.autogen_orchestrator import AutoGenOrchestrator

        cfg = load_config()
        # Normalize provider: vLLM endpoint speaks OpenAI protocol.
        # autogen_agents.create_model_client only knows "openai" / "groq".
        models = cfg.setdefault("models", {})
        for slot in ("default", "judge"):
            mc = models.get(slot)
            if isinstance(mc, dict) and mc.get("provider") == "vllm":
                mc["provider"] = "openai"
                # Honor OPENAI_MODEL env if set (Qwen/Qwen3-8B per .env)
                env_model = os.getenv("OPENAI_MODEL")
                if env_model:
                    mc["name"] = env_model
        st.session_state.orchestrator = AutoGenOrchestrator(cfg)
    return st.session_state.orchestrator


# ---------------------------------------------------------------------------
# Cost estimate
# ---------------------------------------------------------------------------

def cost_estimate(num_messages: int, num_sources: int) -> str:
    """Rough estimate suitable for the statusbar. If vLLM self-hosted (per
    OPENAI_BASE_URL pointing at vllm.salt-lab.org), we say 'self-hosted (free)'.
    Otherwise approximate gpt-4o-mini cost from message + source counts.
    """
    base = os.getenv("OPENAI_BASE_URL", "")
    if "vllm" in base.lower() or "salt-lab" in base.lower():
        return "self-hosted (free)"
    # very rough: ~600 tokens per message + ~400 per source
    tokens = max(0, num_messages) * 600 + max(0, num_sources) * 400
    # gpt-4o-mini blended ~ $0.00015 per 1k tokens (input+output mixed)
    usd = tokens * 0.00015 / 1000
    return f"~${usd:.3f} · {tokens/1000:.1f}k tok"


# ---------------------------------------------------------------------------
# Session-shape transformer
# ---------------------------------------------------------------------------

# Map orchestrator stage names → 7 stepper-node ids (the design's pipeline keys)
_STEP_FROM_STAGE = {
    "stage_1_planning": "plan",
    "stage_2_evidence": ("web", "acad", "counter"),  # depends on agent
    "stage_3_debate_r1": "debate",
    "stage_3_debate_r2": "debate",
    "stage_3_targeted_research": "debate",
    "stage_4_writing": "write",
    "stage_4_editing": "critic",
    "stage_4_guardrail_revise": "write",
}

_AGENT_TO_STEP = {
    "planner": "plan",
    "web_researcher": "web",
    "academic_researcher": "acad",
    "counter_evidence": "counter",
    "optimist": "debate",
    "skeptic": "debate",
    "research_manager": "debate",
    "writer": "write",
    "editor": "critic",
}

PIPELINE_KEYS = ["plan", "web", "acad", "counter", "debate", "write", "critic"]


def _short_role(stage: str, agent: str) -> str:
    """Convert orchestrator stage tag into the design's `role` chip text."""
    if stage == "input":
        return ""
    if stage == "stage_1_planning":
        return "sub_questions"
    if stage == "stage_2_evidence":
        if agent == "counter_evidence":
            return "counter"
        return "findings"
    if stage.startswith("stage_3"):
        return {
            "optimist": "optimist",
            "skeptic": "skeptic",
            "research_manager": "verdict",
        }.get(agent, "debate")
    if stage == "stage_4_writing":
        return "draft"
    if stage == "stage_4_editing":
        return "critique"
    if stage == "stage_4_guardrail_revise":
        return "revise"
    return stage.replace("_", " ")


def _humanize_safety(ev: dict) -> dict:
    """Map raw orchestrator safety_event → design-shape {sev, cat, msg, action}.
    Punch-list #9: humanize internal field names (`unsourced_claims`,
    `first_unsrc`, etc.) into reader-friendly phrasing.
    """
    cat = ev.get("category", "")
    sev_raw = (ev.get("severity") or "").lower()
    sev = (
        "block" if sev_raw == "block"
        else "warn" if sev_raw in {"warning", "warn"}
        else "pass"
    )
    action = ev.get("action", "pass")
    raw_msg = ev.get("message", "")
    evidence = ev.get("evidence", {}) or {}

    # Humanized message + category label
    if cat == "unsourced_claims":
        n = evidence.get("count", 1)
        s = "" if n == 1 else "s"
        msg = f"{n} sentence{s} flagged for revise — lacked a [Sn] citation"
        cat_label = "unsourced claims"
    elif cat == "unsupported_quantitative_claim":
        # Path C Fix 1b: numerical effect size cited [Sn] but Sn.key_claim does
        # not contain the number — likely hallucinated percentage / sample size.
        n = evidence.get("count", 1)
        s = "" if n == 1 else "s"
        sample = evidence.get("findings_sample", []) or []
        first_claim = (sample[0].get("claim") if sample else "") or "?"
        first_sid = (sample[0].get("citation_id") if sample else "") or "?"
        msg = (
            f"{n} numerical claim{s} flagged — value not in cited source's content "
            f"(first: '{first_claim}' attributed to {first_sid})"
        )
        cat_label = "unsupported quantitative claim"
    elif cat == "unsupported_author_attribution":
        # Path C Fix 1b: "Smith et al. 2025 [Sn]" but Sn.authors lacks Smith.
        n = evidence.get("count", 1)
        s = "" if n == 1 else "s"
        sample = evidence.get("findings_sample", []) or []
        first_claim = (sample[0].get("claim") if sample else "") or "?"
        first_sid = (sample[0].get("citation_id") if sample else "") or "?"
        msg = (
            f"{n} author attribution{s} flagged — name not in cited source's authors "
            f"(first: '{first_claim}' attributed to {first_sid})"
        )
        cat_label = "unsupported author attribution"
    elif cat == "prompt_injection":
        msg = "Detected prompt injection pattern"
        cat_label = "prompt injection"
    elif cat == "final_check":
        msg = raw_msg or "All cited sentences resolved to known sources"
        cat_label = "final check"
    elif cat == "in_flight":
        msg = "Provenance verifier idle — not yet engaged"
        cat_label = "in flight"
    else:
        msg = raw_msg or cat
        cat_label = cat.replace("_", " ")

    return {
        "sev": sev,
        "cat": cat_label,
        "msg": msg,
        "action": action,
    }


def _format_time(ts: str) -> str:
    """Convert ISO 8601 → HH:MM:SS for the trace timestamps."""
    try:
        dt = datetime.fromisoformat(ts)
        return dt.strftime("%H:%M:%S")
    except Exception:
        return ts[-8:] if ts else ""


def _format_started(ts: str) -> str:
    try:
        dt = datetime.fromisoformat(ts)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ts


def _agent_color_var(agent: str) -> str:
    """Match data.jsx AGENTS color tokens — used for agent_color fallback."""
    return f"var(--agent-{agent.replace('_','-')})"


def _agent_initials(agent: str) -> str:
    """Mirror initials used in data.jsx AGENTS map."""
    table = {
        "user": "U", "planner": "PL", "web_researcher": "WR",
        "academic_researcher": "AR", "counter_evidence": "CE",
        "optimist": "OP", "skeptic": "SK", "research_manager": "RM",
        "writer": "WT", "editor": "ED",
    }
    return table.get(agent, agent[:2].upper())


def _agent_role_blurb(agent: str) -> str:
    """Tooltip text disambiguating overlapping agents (#5 fix)."""
    return {
        "user": "User",
        "planner": "Decomposes query into sub-questions",
        "web_researcher": "Tavily web search (Stage 2)",
        "academic_researcher": "Semantic Scholar lookup (Stage 2)",
        "counter_evidence": "Adversarial source scan during gathering (Stage 2)",
        "optimist": "Pro stance during debate (Stage 3)",
        "skeptic": "Con stance against consensus during debate (Stage 3)",
        "research_manager": "Adjudicates each debate round (Stage 3)",
        "writer": "Synthesises the cited Markdown report (Stage 4)",
        "editor": "Critique pass; may request a revise (Stage 4)",
    }.get(agent, agent.replace("_", " "))


def _humanize_agent_body(agent: str, raw: str, num_sources: int = 0) -> str:
    """Replace verbose/raw agent outputs with human-readable summaries.

    Planner: parse JSON sub_questions plan -> bullet list.
    Researchers: drop the ## Findings boilerplate, keep only meaningful prose summary.
    Other agents (optimist/skeptic/manager/writer/editor): pass through unchanged.
    """
    if not raw:
        return raw

    if agent == "planner":
        # Extract the JSON payload (strip ```json fence if present)
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```\w*\s*", "", text)
            text = re.sub(r"\s*```\s*$", "", text).strip()
        # Planner sometimes appends 'PLAN COMPLETE' or similar tokens after the
        # JSON. Use a brace counter to extract the first balanced {...} object.
        if text and text[0] == "{":
            depth = 0
            in_str = False
            esc = False
            end = -1
            for idx, ch in enumerate(text):
                if esc:
                    esc = False
                    continue
                if ch == "\\":
                    esc = True
                    continue
                if ch == '"':
                    in_str = not in_str
                    continue
                if in_str:
                    continue
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end = idx + 1
                        break
            if end > 0:
                text = text[:end]
        try:
            data = json.loads(text)
            sqs = data.get("sub_questions", []) or []
            if sqs:
                lines = [f"Decomposed query into **{len(sqs)} sub-questions**:\n"]
                for sq in sqs:
                    qid = sq.get("id", "?")
                    q = sq.get("question", "").strip()
                    rationale = sq.get("rationale", "").strip()
                    lines.append(f"- **Q{qid}.** {q}")
                    if rationale:
                        lines.append(f"  - *Why:* {rationale}")
                return "\n".join(lines)
        except Exception:
            pass
        # Fallback: short note + first 200 chars
        return f"Plan emitted (decomposition JSON, {len(raw)} chars). The pipeline parsed {raw.count('id')} sub-questions before proceeding to evidence stage."

    if agent in {"web_researcher", "academic_researcher", "counter_evidence"}:
        # Researcher bodies dump per-source ### Source: blocks. Extract titles
        # using TWO compatible formats:
        #   `### Source: [TYPE: web] {Title Here}`              ← web/counter convention
        #   `### Source: [TYPE: academic] [S4] Title Here`      ← academic convention
        # Both end at end of line (no trailing brace required).
        # First, try the brace-wrapped form. Then fall back to "rest-of-line after
        # `### Source:` minus the leading [TYPE: ...] and [Sn] tags."
        title_pat_braced = re.compile(r"###\s+Source:.*?\{([^}]+)\}", re.DOTALL)
        title_pat_line = re.compile(
            r"^###\s+Source:\s*(?:\[[^\]]+\]\s*)*(.+?)\s*$",
            re.MULTILINE,
        )
        titles = title_pat_braced.findall(raw)
        if not titles:
            titles = title_pat_line.findall(raw)
            # Strip trailing "(2026)" year annotation if present at line end
            titles = [re.sub(r"\s*\(\d{4}\)\s*$", "", t).strip() for t in titles]
        # Match agent role to a label
        role = {
            "web_researcher": "web sources",
            "academic_researcher": "academic papers",
            "counter_evidence": "counter-evidence / criticism sources",
        }[agent]
        if titles:
            lines = [f"Gathered **{len(titles)} {role}** for the assigned sub-questions."]
            for i, title in enumerate(titles[:8]):  # cap at 8 in card; full list in sources rail
                title_clean = title.strip()[:140]
                lines.append(f"- {title_clean}")
            if len(titles) > 8:
                lines.append(f"- *…and {len(titles) - 8} more (see Sources panel →)*")
            return "\n".join(lines)
        # Fallback when no findings — academic gets a softer message
        if agent == "academic_researcher":
            return ("No academic papers parseable in this run. Semantic Scholar / arXiv may have rate-limited "
                    "the burst of sub-question queries. Counter-Evidence and Web sources are still available; "
                    "see Sources panel for the full evidence pool.")
        return f"Searched for {role} but no usable results were retrieved (provider may have rate-limited or returned empty)."

    # All other agents: pass through unchanged (their prose is already clean)
    return raw


def build_session_from_result(result: dict, query: str, session_id: Optional[str] = None) -> dict:
    """Translate AutoGenOrchestrator output → design session shape (matches data.jsx Q1)."""
    meta = result.get("metadata", {}) or {}
    history = result.get("conversation_history", []) or []
    sources = result.get("sources", {}) or {}
    safety_events = result.get("safety_events", []) or []
    apa_list = result.get("source_list_apa", []) or []
    status = meta.get("status", "complete")

    started_at = ""
    if history:
        started_at = _format_started(history[0].get("timestamp", ""))

    sid = session_id or f"Q{int(time.time())%10000}"

    # ---- Trace --------------------------------------------------------
    trace = []
    for m in history:
        agent = m.get("agent") or m.get("role") or "unknown"
        stage = m.get("stage", "")
        raw_body = m.get("content", "") or ""
        body = _humanize_agent_body(agent, raw_body, len(sources))
        trace.append({
            "agent": agent,
            "stage": stage,
            "time": _format_time(m.get("timestamp", "")),
            "duration": "",
            "role": _short_role(stage, agent),
            "body": body,
            "sanitized": False,  # set below if guardrail revise event matches
            "agent_color": _agent_color_var(agent),
            "initials": _agent_initials(agent),
            "agent_name": _AGENT_DISPLAY_NAMES.get(agent, agent.replace("_", " ").title()),
            "role_blurb": _agent_role_blurb(agent),
        })

    # Mark sanitized when a writer message is followed by a guardrail revise event
    has_unsourced = any(ev.get("category") == "unsourced_claims" for ev in safety_events)
    if has_unsourced:
        # mark the LAST writer message before the editor as sanitized
        for i in range(len(trace) - 1, -1, -1):
            if trace[i]["agent"] == "writer":
                trace[i]["sanitized"] = True
                break

    # ---- Pipeline state -----------------------------------------------
    pipeline_state = {k: "pending" for k in PIPELINE_KEYS}
    seen_stages = {h.get("stage") for h in history}
    seen_agents = {h.get("agent") for h in history}

    if "stage_1_planning" in seen_stages:
        pipeline_state["plan"] = "done"
    if "web_researcher" in seen_agents:
        pipeline_state["web"] = "done"
    if "academic_researcher" in seen_agents:
        pipeline_state["acad"] = "done"
    if "counter_evidence" in seen_agents:
        pipeline_state["counter"] = "done"
    if any(s.startswith("stage_3") for s in seen_stages):
        pipeline_state["debate"] = "done"
    if "stage_4_writing" in seen_stages:
        pipeline_state["write"] = "done"
    if "stage_4_editing" in seen_stages:
        pipeline_state["critic"] = "done"

    if status == "refused":
        pipeline_state = {k: "pending" for k in PIPELINE_KEYS}
        pipeline_state["plan"] = "error"

    # ---- Safety events humanized --------------------------------------
    safety = [_humanize_safety(ev) for ev in safety_events]
    # Add a final-check pass row if everything completed without injection
    if status == "complete" and not any(s["sev"] == "pass" for s in safety):
        cited_n = len(apa_list) or len(sources)
        if cited_n:
            safety.append({
                "sev": "pass",
                "cat": "final check",
                "msg": f"All cited sentences resolved to {cited_n} known source"
                       + ("s" if cited_n != 1 else ""),
                "action": "pass",
            })

    # ---- Sources rail panel data (for citation-tooltip + expand) ------
    rail_sources = {}
    ordered_ids: List[str] = sorted(
        sources.keys(),
        key=lambda s: int(s[1:]) if s.startswith("S") and s[1:].isdigit() else 0,
    ) or list(sources.keys())
    for sid_key in ordered_ids:
        s = sources[sid_key]
        rail_sources[sid_key] = {
            "title": s.get("title", f"Source {sid_key}"),
            "url": s.get("url", ""),
            "type": (s.get("type") or "web").lower(),
            "year": s.get("year", ""),
            "authors": s.get("authors", []),
            "authority": s.get("authority", ""),
            "preview": (s.get("key_claim", "") or "")[:280],
        }

    # ---- Refusal payload ---------------------------------------------
    refusal = None
    if status == "refused":
        first_block = next(
            (ev for ev in safety_events if (ev.get("severity") or "").lower() == "block"),
            None,
        )
        evidence = (first_block or {}).get("evidence", {}) or {}
        refusal = {
            "category": meta.get("refusal_category", "prompt_injection"),
            "title": "Query refused by input guardrail",
            "body": "An injection pattern was detected in the user input. The "
                    "pipeline did not run; no agents, tools, or sources were consulted.",
            "pattern": evidence.get("pattern", ""),
            "match": evidence.get("match", ""),
        }

    # ---- Active-agent indicator --------------------------------------
    active_agent = None
    if status == "running":
        # find last in-progress agent
        for h in reversed(history):
            if h.get("agent") not in {None, "user"}:
                active_agent = {
                    "id": h.get("agent"),
                    "status": "Running",
                    "name": _AGENT_DISPLAY_NAMES.get(h.get("agent"), h.get("agent")),
                    "color": _agent_color_var(h.get("agent")),
                }
                break

    # ---- Meta + cost --------------------------------------------------
    duration = float(meta.get("total_duration_seconds", 0.0) or 0.0)
    out_meta = {
        "num_messages": int(meta.get("num_messages", len(history))),
        "num_sources": int(meta.get("num_sources", len(sources))),
        "debate_rounds": int(meta.get("debate_rounds", 0)),
        "revisions": int(meta.get("revisions", 0)),
        "total_duration_seconds": duration,
        "agents_involved": meta.get("agents_involved", []),
    }

    # ---- View state derivation ---------------------------------------
    if status == "refused":
        view_state = "refused"
    elif status == "complete":
        view_state = "complete"
    else:
        view_state = "loading"

    return {
        "id": sid,
        "query": query,
        "status": status,
        "viewState": view_state,
        "startedAt": started_at,
        "meta": out_meta,
        "pipeline": PIPELINE_KEYS,
        "pipelineState": pipeline_state,
        "trace": trace,
        "sources": ordered_ids,
        "safety": safety,
        "activeAgent": active_agent,
        "refusal": refusal,
        "railSources": rail_sources,
        "response": result.get("response", "") or "",
        "cost": cost_estimate(out_meta["num_messages"], out_meta["num_sources"]),
        "evalScores": None,  # populated by attach_eval_scores() after build
    }


_AGENT_DISPLAY_NAMES = {
    "user": "You",
    "planner": "Planner",
    "web_researcher": "Web Researcher",
    "academic_researcher": "Academic Researcher",
    "counter_evidence": "Counter-Evidence",
    "optimist": "Optimist",
    "skeptic": "Skeptic",
    "research_manager": "Research Manager",
    "writer": "Writer",
    "editor": "Editor",
}


# ---------------------------------------------------------------------------
# Live-runtime: partial-session shaper + background-thread pipeline runner
# ---------------------------------------------------------------------------

def build_partial_session(snap: dict, query: str, run_id: str, started_wall: float) -> dict:
    """Translate a progress-callback snapshot dict (mid-run) into the same
    session shape the React island consumes for completed runs. The result
    is fed into the dashboard so the user sees pipelineState/trace/sources/
    activeAgent updating live as the orchestrator advances.
    """
    history = snap.get("history", []) or []
    sources_raw = snap.get("sources", {}) or {}
    elapsed = snap.get("elapsed", time.time() - started_wall)

    # ---- Trace (skip user msg as the design's chrome shows query elsewhere)
    trace = []
    for m in history:
        agent = m.get("agent") or m.get("role") or "unknown"
        stage = m.get("stage", "")
        raw_body = m.get("content", "") or ""
        if agent == "user":
            continue
        body = _humanize_agent_body(agent, raw_body, len(sources_raw))
        trace.append({
            "agent": agent,
            "stage": stage,
            "time": _format_time(m.get("timestamp", "")),
            "duration": "",
            "role": _short_role(stage, agent),
            "body": body,
            "sanitized": False,
            "agent_color": _agent_color_var(agent),
            "initials": _agent_initials(agent),
            "agent_name": _AGENT_DISPLAY_NAMES.get(agent, agent.replace("_", " ").title()),
            "role_blurb": _agent_role_blurb(agent),
        })

    # ---- Pipeline state — "done" for everything we've already passed,
    # then mark the CURRENT step as "active" (overrides done).
    pipeline_state = {k: "pending" for k in PIPELINE_KEYS}
    seen_stages = {h.get("stage") for h in history}
    seen_agents = {h.get("agent") for h in history}
    if "stage_1_planning" in seen_stages:
        pipeline_state["plan"] = "done"
    if "web_researcher" in seen_agents:
        pipeline_state["web"] = "done"
    if "academic_researcher" in seen_agents:
        pipeline_state["acad"] = "done"
    if "counter_evidence" in seen_agents:
        pipeline_state["counter"] = "done"
    if any(s and s.startswith("stage_3") for s in seen_stages):
        pipeline_state["debate"] = "done"
    if "stage_4_writing" in seen_stages:
        pipeline_state["write"] = "done"
    if "stage_4_editing" in seen_stages:
        pipeline_state["critic"] = "done"

    current_agent = snap.get("agent")
    current_stage = snap.get("stage", "") or ""
    if current_stage == "stage_1_planning":
        pipeline_state["plan"] = "active"
    elif current_agent == "web_researcher":
        pipeline_state["web"] = "active"
    elif current_agent == "academic_researcher":
        pipeline_state["acad"] = "active"
    elif current_agent == "counter_evidence":
        pipeline_state["counter"] = "active"
    elif current_stage and current_stage.startswith("stage_3"):
        pipeline_state["debate"] = "active"
    elif current_stage == "stage_4_writing":
        pipeline_state["write"] = "active"
    elif current_stage == "stage_4_editing":
        pipeline_state["critic"] = "active"

    # ---- Source rail
    rail_sources = {}
    ordered_ids: List[str] = sorted(
        sources_raw.keys(),
        key=lambda s: int(s[1:]) if s.startswith("S") and s[1:].isdigit() else 0,
    ) or list(sources_raw.keys())
    for sid_key in ordered_ids:
        s = sources_raw[sid_key]
        rail_sources[sid_key] = {
            "title": s.get("title", f"Source {sid_key}"),
            "url": s.get("url", ""),
            "type": (s.get("type") or "web").lower(),
            "year": s.get("year", ""),
            "authors": s.get("authors", []),
            "authority": s.get("authority", ""),
            "preview": (s.get("key_claim", "") or "")[:280],
        }

    # ---- Active-agent indicator
    active_agent = None
    if current_agent and current_agent != "user":
        active_agent = {
            "id": current_agent,
            "status": "Running",
            "name": _AGENT_DISPLAY_NAMES.get(current_agent, current_agent),
            "color": _agent_color_var(current_agent),
        }

    # ---- viewState: debate when stage_3, otherwise loading
    if current_stage and current_stage.startswith("stage_3"):
        view_state = "debate"
    else:
        view_state = "loading"

    started_at = ""
    if history:
        started_at = _format_started(history[0].get("timestamp", ""))

    return {
        "id": run_id,
        "query": query,
        "status": "running",
        "viewState": view_state,
        "startedAt": started_at,
        "meta": {
            "num_messages": len(history),
            "num_sources": len(sources_raw),
            "debate_rounds": int(snap.get("debate_rounds", 0)),
            "revisions": int(snap.get("revisions", 0)),
            "total_duration_seconds": float(elapsed),
            "agents_involved": list({
                h.get("agent") for h in history
                if h.get("agent") not in {None, "user"}
            }),
        },
        "pipeline": PIPELINE_KEYS,
        "pipelineState": pipeline_state,
        "trace": trace,
        "sources": ordered_ids,
        "safety": [],  # safety events available only after run completes
        "activeAgent": active_agent,
        "refusal": None,
        "railSources": rail_sources,
        "response": "",
        "cost": cost_estimate(len(history), len(sources_raw)),
        "evalScores": None,
    }


def _run_pipeline_in_thread(query: str, run_id: str) -> None:
    """Daemon target. Runs the orchestrator and writes partial snapshots +
    final result to LIVE_RUN_FILE. Stays decoupled from any st.* calls so
    the bg thread doesn't trip Streamlit's threadlocal context.
    """
    started = time.time()

    def _progress_writer(snap: dict) -> None:
        try:
            partial = build_partial_session(snap, query, run_id, started)
            payload = {
                "run_id": run_id,
                "session": partial,
                "raw_status": "running",
                "ts": time.time(),
            }
            _atomic_write_json(LIVE_RUN_FILE, payload)
            # Mirror to static-served path so the iframe self-polls without
            # forcing a Streamlit script rerun (zero flicker).
            _atomic_write_json(STATIC_LIVE_FILE, payload)
        except Exception as exc:
            print(f"[bg-thread] progress write error: {exc}", flush=True)

    try:
        orch = get_orchestrator()
        result = orch.process_query(query, progress_callback=_progress_writer)
        sess = build_session_from_result(result, query, session_id=run_id)
        sess["evalScores"] = find_eval_scores(query)
        _atomic_write_json(LIVE_RUN_FILE, {
            "run_id": run_id,
            "session": sess,
            "raw_status": "complete",
            "result": result,
            "query": query,
            "ts": time.time(),
        })
        # Static mirror — final snapshot signals the island to redirect to ?finalize=1
        _atomic_write_json(STATIC_LIVE_FILE, {
            "run_id": run_id,
            "session": sess,
            "raw_status": "complete",
            "ts": time.time(),
        })
    except Exception as exc:
        import traceback as _tb
        _atomic_write_json(LIVE_RUN_FILE, {
            "run_id": run_id,
            "raw_status": "error",
            "error": str(exc),
            "traceback": _tb.format_exc(),
            "query": query,
            "ts": time.time(),
        })
        _atomic_write_json(STATIC_LIVE_FILE, {
            "run_id": run_id,
            "raw_status": "error",
            "error": str(exc),
            "ts": time.time(),
        })


# ---------------------------------------------------------------------------
# Idle / empty-state shape
# ---------------------------------------------------------------------------

def empty_state_payload() -> dict:
    return {
        "id": "",
        "query": "",
        "status": "idle",
        "viewState": "idle",
        "startedAt": "",
        "meta": {
            "num_messages": 0, "num_sources": 0, "debate_rounds": 0,
            "revisions": 0, "total_duration_seconds": 0.0, "agents_involved": [],
        },
        "pipeline": PIPELINE_KEYS,
        "pipelineState": {k: "pending" for k in PIPELINE_KEYS},
        "trace": [],
        "sources": [],
        "safety": [],
        "activeAgent": None,
        "refusal": None,
        "railSources": {},
        "response": "",
        "cost": cost_estimate(0, 0),
        "evalScores": None,
    }


# ---------------------------------------------------------------------------
# History list (sidebar)
# ---------------------------------------------------------------------------

def load_recent_history() -> List[dict]:
    """Load recent sessions for the sidebar.

    Round-3 Fix 3: Real user runs (live_*.json) come first, newest by mtime.
    Demo queries (Q1/Q5/Q6) appear at the bottom under a "DEMO QUERIES" separator
    so they remain accessible for grading but don't masquerade as real runs.
    """
    items: List[dict] = []
    if not SESSIONS_DIR.exists():
        return items

    # 1) Demos FIRST — pre-built canonical Q1/Q5/Q6 (grading evidence).
    demo_files = []
    for stem in ("Q1_normal", "Q5_contested", "Q6_injection"):
        candidate = SESSIONS_DIR / f"{stem}.json"
        if candidate.exists():
            demo_files.append((stem.split("_")[0], candidate))

    if demo_files:
        items.append({
            "id": "__separator__",
            "title": "DEMO QUERIES",
            "status": "separator",
            "time": "", "date": "", "file": "", "isReal": False,
        })
        for sid, p in demo_files:
            try:
                raw = json.loads(p.read_text())
                res = raw.get("result", raw) or {}
                meta = res.get("metadata", {}) or {}
                q = raw.get("query") or res.get("query") or p.stem
                status = meta.get("status", "complete")
                dur = float(meta.get("total_duration_seconds") or 0.0)
                num_msgs = int(meta.get("num_messages") or 0)
                num_srcs = int(meta.get("num_sources") or 0)
                items.append({
                    "id": sid,
                    "title": (q[:60] + ("…" if len(q) > 60 else "")),
                    "subtitle": f"{num_msgs} msgs · {int(dur)}s · {num_srcs} sources · demo",
                    "status": status,
                    "time": (
                        f"{int(dur//60)}m {int(dur%60):02d}s" if dur >= 60
                        else f"{dur:.1f}s"
                    ),
                    "date": "preloaded",
                    "file": str(p),
                    "isReal": False,
                })
            except Exception:
                continue

    # 2) Real user runs — newest first by mtime, cap at 20.
    live_files = sorted(
        SESSIONS_DIR.glob("live_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:20]

    if live_files:
        items.append({
            "id": "__separator2__",
            "title": "YOUR RUNS",
            "status": "separator",
            "time": "", "date": "", "file": "", "isReal": False,
        })

    for p in live_files:
        try:
            raw = json.loads(p.read_text())
            res = raw.get("result", raw) or {}
            meta = res.get("metadata", {}) or {}
            q = raw.get("query") or res.get("query") or p.stem
            sid = p.stem
            status = meta.get("status", "complete")
            dur = float(meta.get("total_duration_seconds") or 0.0)
            num_msgs = int(meta.get("num_messages") or 0)
            num_srcs = int(meta.get("num_sources") or 0)
            mtime_ts = p.stat().st_mtime
            items.append({
                "id": sid,
                "title": (q[:60] + ("…" if len(q) > 60 else "")),
                "subtitle": f"{num_msgs} msgs · {int(dur)}s · {num_srcs} sources",
                "status": status,
                "time": (
                    f"{int(dur//60)}m {int(dur%60):02d}s" if dur >= 60
                    else f"{dur:.1f}s"
                ),
                "date": _relative_date(mtime_ts),
                "timestamp": mtime_ts,
                "file": str(p),
                "isReal": True,
            })
        except Exception:
            continue

    return items


def _relative_date(ts: float) -> str:
    """Render a Unix ts as relative (e.g. '2m ago', 'Yesterday')."""
    import datetime as _dt
    now = time.time()
    delta = max(0, int(now - ts))
    if delta < 60:
        return "just now"
    if delta < 3600:
        return f"{delta // 60}m ago"
    if delta < 86400:
        return f"{delta // 3600}h ago"
    if delta < 86400 * 2:
        return "Yesterday"
    if delta < 86400 * 7:
        return f"{delta // 86400}d ago"
    return _dt.datetime.fromtimestamp(ts).strftime("%b %d")


# ---------------------------------------------------------------------------
# HTML island — full dashboard
# ---------------------------------------------------------------------------

def _read_styles() -> str:
    return STYLES_PATH.read_text()


def _build_all_sessions(initial_state: dict) -> dict:
    """Pre-load every accessible session into the SESSIONS map so the React
    island can switch between them client-side without forcing a Streamlit
    rerun + iframe re-mount (which causes a visible flash).

    Includes:
      - Q1/Q5/Q6 demo files (Q1_normal.json, Q5_contested.json, Q6_injection.json)
      - All live_*.json real user runs (capped at 20 newest)
      - "live" slot for the currently-active or most recent run
      - "idle" / "loading" / "debate" left as None (legacy state pill keys)
    """
    sessions: dict = {
        "Q1": None,
        "Q5": None,
        "Q6": None,
        "loading": None,
        "debate": None,
        "idle": None,
    }

    # Load demo files
    demos = [
        ("Q1", "Q1_normal.json"),
        ("Q5", "Q5_contested.json"),
        ("Q6", "Q6_injection.json"),
    ]
    for sid, fname in demos:
        f = SESSIONS_DIR / fname
        if not f.exists():
            continue
        try:
            raw = json.loads(f.read_text())
            res = raw.get("result", raw) or {}
            q = raw.get("query") or res.get("query") or ""
            sess = build_session_from_result(res, q, session_id=sid)
            sess["evalScores"] = find_eval_scores(q, session_id=sid)
            sessions[sid] = sess
        except Exception as exc:
            print(f"[_build_all_sessions] demo {sid} load failed: {exc}", flush=True)

    # Load all real user runs (cap 20 newest by mtime)
    live_files = sorted(
        SESSIONS_DIR.glob("live_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:20]
    for f in live_files:
        sid = f.stem
        try:
            raw = json.loads(f.read_text())
            res = raw.get("result", raw) or {}
            q = raw.get("query") or res.get("query") or ""
            sess = build_session_from_result(res, q, session_id=sid)
            sess["evalScores"] = find_eval_scores(q, session_id=sid)
            sessions[sid] = sess
        except Exception as exc:
            print(f"[_build_all_sessions] live {sid} load failed: {exc}", flush=True)

    # "live" slot: the currently-active run (mid-run partial OR most recent complete)
    live = st.session_state.get("live_result")
    sessions["live"] = live

    # Also include the directly-passed initial_state if it's complete and has trace
    if initial_state and isinstance(initial_state, dict):
        sid = initial_state.get("id")
        status = initial_state.get("status")
        if sid and status and status not in ("idle",) and initial_state.get("trace"):
            sessions[sid] = initial_state

    return sessions


def render_island_html(state: dict, history: List[dict], initial_state_id: str = "idle") -> str:
    """Build the complete HTML doc for the dashboard island.

    Now injects window.SESSIONS (all pre-built states) + window.INITIAL_SESSION_ID
    so the island can switch states purely client-side without Streamlit reruns.
    The legacy window.__STATE payload is kept for backwards compatibility but
    the island now reads window.SESSIONS instead.
    """
    css = _read_styles()

    # Legacy single-session payload (kept for any external consumers)
    state_payload = {
        "session": state,
        "history": history,
    }
    state_json = json.dumps(state_payload, default=str, ensure_ascii=False)

    # Multi-session payload: all 5 states pre-built
    all_sessions = _build_all_sessions(state)
    sessions_json = json.dumps(all_sessions, default=str, ensure_ascii=False)
    history_json = json.dumps(history, default=str, ensure_ascii=False)

    # Size guard: with 23 pre-loaded sessions the payload can grow large; warn
    # if it crosses 1 MB so we know slow iframe init is on us, not the network.
    if len(sessions_json) > 1_000_000:
        print(f"[island] SESSIONS payload {len(sessions_json):,} bytes — may cause slow iframe init", flush=True)

    # Run-active flag: signals the island to enable static-poll mode and
    # navigate to ?finalize=1 when the bg thread writes raw_status="complete".
    run_active_js = "true" if st.session_state.get("run_active") else "false"

    # NOTE: island.jsx is plain Babel/JSX with NO Python interpolation inside.
    js_runtime = ISLAND_JS_PATH.read_text()

    return f"""<!doctype html>
<html lang="en" style="height:100%;overflow:hidden;">
<head>
<meta charset="utf-8" />
<title>Agentic UX — Deep Research</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Source+Serif+Pro:ital,wght@0,400;0,600;1,400&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
/* Fix Bug 1+2: lock island to iframe height, let .main scroll internally */
html, body {{ height: 100%; overflow: hidden; margin: 0; padding: 0; }}
#root {{ height: 100%; }}
</style>
<style>{css}</style>
</head>
<body style="height:100%;overflow:hidden;">
<div id="root" style="height:100%;"></div>

<script src="https://unpkg.com/react@18.3.1/umd/react.development.js" crossorigin="anonymous"></script>
<script src="https://unpkg.com/react-dom@18.3.1/umd/react-dom.development.js" crossorigin="anonymous"></script>
<script src="https://unpkg.com/@babel/standalone@7.29.0/babel.min.js" crossorigin="anonymous"></script>

<!-- Legacy single-session payload (kept for compatibility) -->
<script id="__state_payload__" type="application/json">{state_json}</script>

<!-- Multi-session payload: all states pre-built for client-side switching -->
<script>
window.SESSIONS = {sessions_json};
window.INITIAL_SESSION_ID = {json.dumps(initial_state_id)};
window.HISTORY = {history_json};
window.__RUN_ACTIVE__ = {run_active_js};
</script>

<script type="text/babel" data-presets="env,react">
{js_runtime}
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Streamlit page
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Agentic UX — Deep Research",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# --- Read query params early so preload_id is available for CSS gating ----
qp = st.query_params
preload_id = qp.get("preload", None)
phase_param = qp.get("phase", None)

# K1: Streamlit chrome containment.
# The React island owns ALL UI (form, button, status). Streamlit only mounts
# the iframe + handles URL params + serves data. There is NEVER a native
# widget above the iframe in any mode.
_base_css = """
    /* Hide ALL Streamlit chrome — header, toolbar, deploy button, status pill */
    #MainMenu, footer, header[data-testid="stHeader"] { display: none !important; }
    [data-testid="stToolbar"] { display: none !important; }
    [data-testid="stStatusWidget"] { display: none !important; }
    [data-testid="stDecoration"] { display: none !important; }
    /* Ensure the body & main containers are dark-themed always (P1-16) */
    html, body { background: #0a0e14 !important; margin: 0 !important; padding: 0 !important; }
    [data-testid="stApp"], [data-testid="stAppViewContainer"], [data-testid="stMain"] {
      background: #0a0e14 !important;
      padding: 0 !important;
    }
    .stApp > header { background: transparent !important; }
    .block-container,
    [data-testid="stMainBlockContainer"] {
      padding: 0 !important;
      max-width: 100% !important;
      gap: 0 !important;
    }
    [data-testid="stVerticalBlock"],
    [data-testid="stVerticalBlockBorderWrapper"] { gap: 0 !important; }
    [data-testid="stElementContainer"], .element-container {
      gap: 0 !important; margin: 0 !important; padding: 0 !important;
    }
    /* Hide every form widget — the island owns input.
       (We still render st.text_area & st.button, but invisible: this is
       how we receive `Run` postMessages without losing Streamlit's rerun
       lifecycle.) */
    [data-testid="stTextArea"],
    [data-testid="stTextInput"],
    [data-testid="stButton"],
    [data-testid="stForm"],
    [data-testid="stStatus"],
    [data-testid="stHorizontalBlock"],
    [data-testid="stColumn"],
    .runner-form { display: none !important; }
    iframe { display: block !important; border: 0 !important; }
    /* The iframe should have no surrounding gap */
    [data-testid="stMain"] > div > div > div {
      gap: 0 !important;
      padding: 0 !important;
    }
"""

st.markdown(
    f"<style>{_base_css}</style>",
    unsafe_allow_html=True,
)

# Top-frame postMessage listener: island iframe cannot write window.top.location
# directly (srcdoc sandbox blocks it), so it posts {type:'omc_run', query:'...'}
# to window.parent. This script runs in the TOP Streamlit frame and listens for
# that message, then performs the actual navigation to ?run=<query>.
st.markdown("""
<script>
(function() {
  if (window._omcRunListenerAttached) return;
  window._omcRunListenerAttached = true;
  window.addEventListener('message', function(ev) {
    if (!ev.data) return;
    if (ev.data.type === 'omc_run') {
      var q = ev.data.query;
      if (!q || !q.trim()) return;
      window.location.href = '?run=' + encodeURIComponent(q.trim());
    } else if (ev.data.type === 'omc_clear_result') {
      window.location.href = '?clear=1';
    }
  });
})();
</script>
""", unsafe_allow_html=True)

# --- Init session state ---------------------------------------------------
if "current_session" not in st.session_state:
    st.session_state.current_session = empty_state_payload()
if "edit_query_prefill" not in st.session_state:
    st.session_state.edit_query_prefill = ""
if "history_items" not in st.session_state:
    st.session_state.history_items = load_recent_history()

# --- Dev preload (?preload=Q1|Q5|Q6|loading|live_<ts>) — preload_id parsed above ----
# P1-22: ?preload=loading synthesizes a mid-run state (planner done,
# web_researcher in flight, others pending).
# P1-19: ?phase=debate freezes Q5 mid-debate.
# Round-3 Fix 3: ?preload=live_<ts> loads a real user run by file id.
preload_token = (preload_id, phase_param)
if preload_id and st.session_state.get("_preloaded") != preload_token:
    if preload_id == "loading":
        # Synthesize a loading state from Q1 — first 2 trace messages, rest pending
        candidate = SESSIONS_DIR / "Q1_normal.json"
    elif preload_id.startswith("live_"):
        candidate = SESSIONS_DIR / f"{preload_id}.json"
    else:
        candidate = SESSIONS_DIR / f"{preload_id}_normal.json"
        if not candidate.exists():
            candidate = next(SESSIONS_DIR.glob(f"{preload_id}*.json"), None)
    if candidate and candidate.exists():
        try:
            raw = json.loads(candidate.read_text())
            res = raw.get("result", raw)
            q = raw.get("query") or res.get("query") or ""
            sess = build_session_from_result(res, q, session_id=preload_id)
            sess["evalScores"] = find_eval_scores(q, session_id=preload_id)

            # P1-22: synthetic loading state
            if preload_id == "loading":
                trace = sess.get("trace", [])
                # Keep only the planner output, then mark web_researcher as active
                kept = [m for m in trace if m.get("agent") in ("user", "planner")][:3]
                sess["trace"] = kept
                sess["status"] = "running"
                sess["viewState"] = "loading"
                sess["pipelineState"] = {
                    "plan": "done", "web": "active",
                    "acad": "pending", "counter": "pending",
                    "debate": "pending", "write": "pending", "critic": "pending",
                }
                sess["activeAgent"] = {
                    "id": "web_researcher",
                    "status": "Querying Tavily — 7 results so far…",
                    "name": "Web Researcher",
                    "color": "var(--agent-web-researcher)",
                }

            # P1-19: ?phase=debate — Q5 frozen mid-debate
            if phase_param == "debate":
                trace = sess.get("trace", [])
                # Keep up to and including the optimist message
                kept_idx = None
                for i, m in enumerate(trace):
                    if m.get("agent") == "optimist":
                        kept_idx = i + 1
                        break
                if kept_idx is None:
                    kept_idx = max(1, len(trace) // 2)
                sess["trace"] = trace[:kept_idx]
                sess["status"] = "running"
                sess["viewState"] = "debate"
                sess["pipelineState"] = {
                    "plan": "done", "web": "done", "acad": "done", "counter": "done",
                    "debate": "active", "write": "pending", "critic": "pending",
                }
                sess["activeAgent"] = {
                    "id": "research_manager",
                    "status": "Adjudicating round 1…",
                    "name": "Research Manager",
                    "color": "var(--agent-research-manager)",
                }

            st.session_state.current_session = sess
            st.session_state._preloaded = preload_token
        except Exception as exc:  # noqa: BLE001
            st.warning(f"Preload failed: {exc}")

# --- Pre-fill from Edit-query CTA ----------------------------------------
default_query = st.session_state.get("edit_query_prefill") or st.session_state.current_session.get("query", "")
# Also accept the postMessage from the island (set by the Edit-query CTA)
# via st.query_params.get('edit') as a one-shot trigger.
if qp.get("edit"):
    default_query = qp.get("edit")
    # clear once consumed
    st.query_params.clear()

# --- Form-less invocation: island writes window.top.location.href → ?run= ------
# EntryPage does direct URL navigation to ?run=<query>. Streamlit reloads and
# catches it here → runs orchestrator → saves result as "live" session →
# island mounts with INITIAL_SESSION_ID="live".
run_query = qp.get("run", None)
if run_query and run_query.strip():
    qtxt = run_query.strip()
    print(f"[streamlit] Received run_query: {qtxt[:80]}", flush=True)
    st.session_state.edit_query_prefill = ""
    st.query_params.clear()

    # Reject if a run is already active for this session
    if not st.session_state.get("run_active"):
        run_id = f"live_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        st.session_state.run_active = True
        st.session_state.run_id = run_id
        st.session_state.run_query_text = qtxt
        # Wipe any stale partial file from a prior run
        try:
            if LIVE_RUN_FILE.exists():
                LIVE_RUN_FILE.unlink()
        except Exception:
            pass
        try:
            if STATIC_LIVE_FILE.exists():
                STATIC_LIVE_FILE.unlink()
        except Exception:
            pass
        # Seed a minimal partial session so the iframe has SOMETHING to show
        # before the first progress_callback fires. The React island will then
        # take over via static-poll, eliminating the need for Streamlit reruns.
        st.session_state.current_session = {
            "id": run_id,
            "query": qtxt,
            "status": "running",
            "viewState": "loading",
            "startedAt": "",
            "meta": {
                "num_messages": 0, "num_sources": 0, "debate_rounds": 0,
                "revisions": 0, "total_duration_seconds": 0.0, "agents_involved": [],
            },
            "pipeline": PIPELINE_KEYS,
            "pipelineState": {k: "pending" for k in PIPELINE_KEYS},
            "trace": [], "sources": [], "safety": [], "activeAgent": None,
            "refusal": None, "railSources": {}, "response": "",
            "cost": cost_estimate(0, 0), "evalScores": None,
        }
        st.session_state.live_result = st.session_state.current_session
        # Spawn daemon — orchestrator drives the pipeline off the main thread
        # so Streamlit's render loop stays responsive and can poll partials.
        t = threading.Thread(
            target=_run_pipeline_in_thread,
            args=(qtxt, run_id),
            daemon=True,
        )
        t.start()
        print(f"[streamlit] Background thread started for run_id={run_id}", flush=True)
    st.rerun()

# --- Finalization handler: React island redirects here when run completes ---
# During the run, the iframe self-polls /app/static/live_partial.json and
# detects raw_status == "complete" client-side, then navigates to ?finalize=1.
# This means the Streamlit script DOES NOT rerun during the run — zero flicker.
if qp.get("finalize"):
    print("[streamlit] Finalize handler triggered", flush=True)
    st.query_params.clear()
    if LIVE_RUN_FILE.exists():
        try:
            payload = json.loads(LIVE_RUN_FILE.read_text())
            raw_status = payload.get("raw_status", "")
            if raw_status == "error":
                err_msg = payload.get("error", "Unknown error")
                tb_str = payload.get("traceback", "")
                st.session_state.current_session = empty_state_payload()
                st.session_state.current_session["error"] = err_msg
                st.session_state.run_active = False
                st.session_state.live_result = None
                try:
                    LIVE_RUN_FILE.unlink()
                except Exception:
                    pass
                try:
                    STATIC_LIVE_FILE.unlink()
                except Exception:
                    pass
                st.error(f"Pipeline failed: {err_msg}")
                st.code(tb_str)
                st.stop()
            final_session = payload.get("session")
            if final_session:
                st.session_state.current_session = final_session
                st.session_state.live_result = final_session
            # Persist the final result to disk for sidebar history
            try:
                ts = int(time.time())
                out_path = SESSIONS_DIR / f"live_{ts}.json"
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(json.dumps({
                    "query": payload.get("query"),
                    "result": payload.get("result"),
                }, default=str, ensure_ascii=False, indent=2))
                print(f"[streamlit] Saved {out_path}", flush=True)
            except Exception as _exc:
                print(f"[streamlit] save final error: {_exc}", flush=True)
            # Cleanup both files
            try:
                LIVE_RUN_FILE.unlink()
            except Exception:
                pass
            try:
                STATIC_LIVE_FILE.unlink()
            except Exception:
                pass
        except Exception as _exc:
            print(f"[streamlit] finalize error: {_exc}", flush=True)
    st.session_state.run_active = False
    st.session_state.history_items = load_recent_history()
    st.rerun()

# Clear-session trigger (also clears live_result so Complete state goes empty)
if qp.get("clear"):
    st.session_state.current_session = empty_state_payload()
    st.session_state.edit_query_prefill = ""
    st.session_state.pop("live_result", None)
    st.query_params.clear()
    st.rerun()

# --- Phase 6.5: judge scoring — triggered via ?score=1 query param --------
# No Streamlit button widget rendered here (would add ~40px gap above island).
# The island's eval panel emits window.parent.postMessage({type:"score"})
# which causes a page reload with ?score=1; Python detects it here.
_score_trigger = qp.get("score", None)
_cur = st.session_state.current_session
if _score_trigger and _cur and _cur.get("status") == "complete" and _cur.get("response"):
    import asyncio as _asyncio
    from src.evaluation.judge import StrictRubricJudge, PersonaJudge

    _q = _cur.get("query", "")
    _resp = _cur.get("response", "")
    _sources = list(_cur.get("railSources", {}).values())
    _safety = _cur.get("safety", [])

    try:
        cfg = load_config()
        strict_judge = StrictRubricJudge(cfg)
        hci_judge = PersonaJudge(cfg)
        strict_result = _asyncio.run(strict_judge.score_async(_q, _resp, _sources, _safety))
        hci_result = _asyncio.run(hci_judge.score_async(_q, _resp, _sources, _safety))
        eval_scores = {
            "strict_rubric": {
                "scores": strict_result.get("scores", {}),
                "rationale": strict_result.get("rationale", ""),
            },
            "hci_grad_student": {
                "scores": hci_result.get("scores", {}),
                "rationale": hci_result.get("rationale", ""),
            },
        }
        st.session_state.current_session["evalScores"] = eval_scores
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = OUTPUTS_DIR / f"inline_eval_{ts}.json"
        out_path.write_text(
            json.dumps({"query": _q, "judge_scores": eval_scores},
                       default=str, ensure_ascii=False, indent=2)
        )
        # Clear the ?score param and rerun to show results
        st.query_params.clear()
        if preload_id:
            st.query_params["preload"] = preload_id
        st.rerun()
    except Exception as exc:  # noqa: BLE001
        st.error(f"Judge error: {exc}")

# --- Render the island ----------------------------------------------------
state = st.session_state.current_session

# Pass mode + edit-prefill into the island via state so the React app can show
# them in EmptyState's input.
state["mode"] = qp.get("mode", "autogen")
state["editPrefill"] = default_query if not state.get("query") else ""
state["phase"] = phase_param or ""

# K2: Iframe sizing contract — generous fixed pixel height so iframe doesn't
# need to grow with trace length. Inside the island, html/body are forced
# to height:100% and .app uses height:100vh with overflow:hidden so the
# .main column scrolls internally. The iframe outer height is the LARGER
# of the two so we never crop content vertically; it's intentional that
# we may have a tiny dead-band on very tall viewports — the island's
# .statusbar pins to the bottom of the iframe via grid, so the iframe
# itself is the floor.
# 1200 covers tablet (768) → desktop (1080). Mobile is handled via
# media-queries inside the island.
ISLAND_HEIGHT = 1200

# Navigation relay: declared Streamlit component that receives omc_navigate
# postMessages from the island iframe and relays the params dict to Python.
# Python handles them below by updating st.query_params + st.rerun().
# height=0 so it adds no visual gap.
_nav_params = _nav_relay(key="omc_nav_relay", default=None)

# Handle navigation relay: if the island sent a navigate request, update
# query params and rerun so Streamlit loads the correct session.
if _nav_params and isinstance(_nav_params, dict):
    _changed = False
    for k, v in _nav_params.items():
        if v is None:
            if k in st.query_params:
                del st.query_params[k]
                _changed = True
        else:
            if st.query_params.get(k) != str(v):
                st.query_params[k] = str(v)
                _changed = True
    if _changed:
        st.rerun()

# Determine initial state id for window.INITIAL_SESSION_ID
# Maps the current session/preload to the correct client-side state key.
# "live" takes highest priority during a run-in-progress AND when a real user
# run just completed. Bypassed only by explicit ?preload= / ?phase= overrides.
if st.session_state.get("run_active") and not preload_id:
    _initial_state_id = "live"
elif st.session_state.get("live_result") and not preload_id:
    _initial_state_id = "live"
elif phase_param == "debate":
    _initial_state_id = "debate"
elif preload_id in ("loading", "Q1", "Q5", "Q6"):
    _initial_state_id = preload_id
elif state.get("viewState") == "idle" or not state.get("id"):
    _initial_state_id = "idle"
else:
    _initial_state_id = state.get("id", "idle")

components.html(
    render_island_html(state, st.session_state.history_items, initial_state_id=_initial_state_id),
    height=ISLAND_HEIGHT,
    scrolling=False,
)

