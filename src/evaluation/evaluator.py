# Created: 2026-05-07
# Last reused or audited: 2026-05-07
# Authority basis: Phase 8 spec — batch evaluation, multi-judge triangulation, Spearman correlation
"""
SystemEvaluator — batch evaluation with multi-judge triangulation.

Usage:
    evaluator = SystemEvaluator(orchestrator, [StrictRubricJudge(client), PersonaJudge(client)], config)
    run_data = evaluator.run_batch(queries)          # sync wrapper
    evaluator.generate_report(run_data)              # writes JSON + MD to outputs/
"""

from __future__ import annotations

import asyncio
import csv
import json
import logging
import math
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any

from .judge import Judge

logger = logging.getLogger("evaluation.evaluator")


class SystemEvaluator:
    def __init__(self, orchestrator: Any, judges: list[Judge], config: dict):
        self.orchestrator = orchestrator
        self.judges = judges
        self.config = config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run_batch_async(self, queries: list[dict]) -> dict:
        """
        For each query: run orchestrator, then run each judge sequentially.
        Returns full run_data dict including aggregate.
        """
        results = []
        start_ts = datetime.now()

        for i, q in enumerate(queries, 1):
            qid = q.get("id", i)
            query_text = q.get("query", "")
            logger.info("Query %d/%d [id=%s]: %s", i, len(queries), qid, query_text[:60])

            # --- run orchestrator ---
            orch_result = {}
            try:
                orch_result = await asyncio.get_event_loop().run_in_executor(
                    None, self.orchestrator.process_query, query_text
                )
            except Exception as exc:
                logger.error("Orchestrator failed for query %s: %s", qid, exc)
                orch_result = {
                    "response": f"[Orchestrator error: {exc}]",
                    "sources": {},
                    "safety_events": [],
                    "metadata": {"status": "error"},
                }

            response_text = orch_result.get("response", "")
            sources_raw = orch_result.get("sources", {})
            # sources may be dict {S1: {...}, ...} or list
            if isinstance(sources_raw, dict):
                sources_list = list(sources_raw.values())
            else:
                sources_list = sources_raw or []
            safety_events = orch_result.get("safety_events", [])

            # --- run each judge sequentially ---
            judge_scores: dict[str, dict] = {}
            for judge in self.judges:
                try:
                    score = await judge.score_async(
                        query_text, response_text, sources_list, safety_events
                    )
                    judge_scores[judge.name] = score
                    logger.info("  Judge %s scores: %s", judge.name, score.get("scores"))
                except Exception as exc:
                    logger.error("Judge %s failed on query %s: %s", judge.name, qid, exc)
                    judge_scores[judge.name] = {
                        "name": judge.name,
                        "scores": {c: 0 for c in judge.criteria},
                        "rationale": f"Judge error: {exc}",
                        "raw": "",
                    }

            results.append({
                "query": q,
                "result": orch_result,
                "judge_scores": judge_scores,
            })

        elapsed = (datetime.now() - start_ts).total_seconds()
        run_data = {
            "queries": results,
            "meta": {
                "n_queries": len(queries),
                "n_judges": len(self.judges),
                "elapsed_seconds": round(elapsed, 1),
                "timestamp": start_ts.isoformat(),
            },
        }
        run_data["aggregate"] = self.aggregate(run_data)
        return run_data

    def run_batch(self, queries: list[dict]) -> dict:
        return asyncio.run(self.run_batch_async(queries))

    def aggregate(self, run_data: dict) -> dict:
        """
        Compute:
          - per_judge_per_criterion: {judge_name: {criterion: {mean, std, n}}}
          - inter_judge_correlation: Spearman between judges (shared aggregate scores)
          - judge_vs_human: Spearman vs human_eval.csv if present
          - per_query_summary: list[{query_id, query_text, score_strict, score_persona, status}]
        """
        queries = run_data.get("queries", [])

        # Collect per-judge per-criterion raw scores across queries
        judge_criterion_vals: dict[str, dict[str, list[float]]] = {}
        for entry in queries:
            for jname, jscore in entry.get("judge_scores", {}).items():
                if jname not in judge_criterion_vals:
                    judge_criterion_vals[jname] = {}
                for crit, val in jscore.get("scores", {}).items():
                    judge_criterion_vals[jname].setdefault(crit, []).append(float(val))

        per_judge_per_criterion: dict[str, dict[str, dict]] = {}
        for jname, crit_vals in judge_criterion_vals.items():
            per_judge_per_criterion[jname] = {}
            for crit, vals in crit_vals.items():
                n = len(vals)
                mean = statistics.mean(vals) if vals else 0.0
                std = statistics.stdev(vals) if len(vals) > 1 else 0.0
                per_judge_per_criterion[jname][crit] = {
                    "mean": round(mean, 3),
                    "std": round(std, 3),
                    "n": n,
                }

        # Inter-judge Spearman on aggregate mean score per query
        inter_judge_correlation: dict[str, Any] = {}
        judge_names = list(judge_criterion_vals.keys())
        if len(judge_names) >= 2:
            # Build per-query aggregate score vectors for each judge
            judge_agg: dict[str, list[float]] = {jn: [] for jn in judge_names}
            for entry in queries:
                for jn in judge_names:
                    scores = entry.get("judge_scores", {}).get(jn, {}).get("scores", {})
                    vals = [float(v) for v in scores.values() if v != 0]
                    judge_agg[jn].append(statistics.mean(vals) if vals else 0.0)

            for i in range(len(judge_names)):
                for j in range(i + 1, len(judge_names)):
                    jn_a, jn_b = judge_names[i], judge_names[j]
                    key = f"{jn_a}_vs_{jn_b}"
                    corr, pval = _spearman(judge_agg[jn_a], judge_agg[jn_b])
                    inter_judge_correlation[key] = {
                        "spearman_r": round(corr, 4) if corr is not None else None,
                        "p_value": round(pval, 4) if pval is not None else None,
                        "n": len(queries),
                    }

        # Human triangulation — load human_eval.csv if present
        judge_vs_human: dict[str, Any] = {}
        human_path = Path("data/human_eval.csv")
        if human_path.exists():
            judge_vs_human = _compute_human_correlation(queries, judge_names, human_path)

        # Per-query summary
        per_query_summary = []
        for entry in queries:
            q = entry.get("query", {})
            qid = q.get("id", "?")
            qtext = q.get("query", "")[:80]
            meta = entry.get("result", {}).get("metadata", {})
            status = meta.get("status", "unknown")

            score_strict = _judge_mean(entry, "strict_rubric")
            score_persona = _judge_mean(entry, "hci_grad_student")

            per_query_summary.append({
                "query_id": qid,
                "query_text": qtext,
                "score_strict": round(score_strict, 3),
                "score_persona": round(score_persona, 3),
                "status": status,
            })

        return {
            "per_judge_per_criterion": per_judge_per_criterion,
            "inter_judge_correlation": inter_judge_correlation,
            "judge_vs_human": judge_vs_human,
            "per_query_summary": per_query_summary,
        }

    def generate_report(self, run_data: dict, output_dir: str = "outputs") -> tuple[Path, Path]:
        """
        Writes:
          outputs/eval_report_{ts}.json — full data + aggregate
          outputs/eval_report_{ts}.md  — human-readable tables + interpretation
        Returns (json_path, md_path).
        """
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        json_path = out / f"eval_report_{ts}.json"
        md_path = out / f"eval_report_{ts}.md"

        # Write JSON (strip raw LLM outputs to keep size sane)
        slim = _slim_for_json(run_data)
        with open(json_path, "w") as f:
            json.dump(slim, f, indent=2, default=str)
        logger.info("Wrote %s", json_path)

        # Write Markdown
        md = _render_markdown(run_data)
        with open(md_path, "w") as f:
            f.write(md)
        logger.info("Wrote %s", md_path)

        return json_path, md_path


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _judge_mean(entry: dict, judge_name: str) -> float:
    scores = entry.get("judge_scores", {}).get(judge_name, {}).get("scores", {})
    vals = [float(v) for v in scores.values() if v != 0]
    return statistics.mean(vals) if vals else 0.0


def _spearman(x: list[float], y: list[float]) -> tuple[float | None, float | None]:
    """Compute Spearman correlation using scipy if available, else return None."""
    if len(x) < 2 or len(x) != len(y):
        return None, None
    try:
        from scipy.stats import spearmanr
        result = spearmanr(x, y)
        return float(result.statistic), float(result.pvalue)
    except Exception as exc:
        logger.warning("Spearman computation failed: %s", exc)
        return None, None


def _compute_human_correlation(
    queries: list[dict], judge_names: list[str], human_path: Path
) -> dict:
    """
    Load human_eval.csv, correlate human scores with judge aggregate scores.
    Gracefully returns NaN fields if human data is sparse or missing.
    """
    # Load human scores keyed by (query_id, criterion)
    human_by_qid: dict[int | str, list[float]] = {}
    try:
        with open(human_path, newline="") as f:
            reader = csv.DictReader(
                (line for line in f if not line.startswith("#"))
            )
            for row in reader:
                qid_raw = (row.get("query_id") or "").strip()
                score_raw = (row.get("human_score") or "").strip()
                if not qid_raw or not score_raw:
                    continue
                try:
                    qid = int(qid_raw)
                    score = float(score_raw)
                    human_by_qid.setdefault(qid, []).append(score)
                except ValueError:
                    continue
    except Exception as exc:
        logger.warning("Could not read human_eval.csv: %s", exc)
        return {"error": str(exc)}

    if not human_by_qid:
        return {"note": "human_eval.csv present but no numeric scores found (stub data)"}

    # Build paired vectors
    human_agg_per_query: list[float] = []
    judge_agg_per_query: dict[str, list[float]] = {jn: [] for jn in judge_names}

    for entry in queries:
        q = entry.get("query", {})
        qid = q.get("id")
        if qid not in human_by_qid:
            continue
        h_mean = statistics.mean(human_by_qid[qid])
        human_agg_per_query.append(h_mean)
        for jn in judge_names:
            judge_agg_per_query[jn].append(_judge_mean(entry, jn))

    results = {}
    for jn in judge_names:
        jvals = judge_agg_per_query[jn]
        corr, pval = _spearman(human_agg_per_query, jvals)
        results[jn] = {
            "spearman_r": round(corr, 4) if corr is not None else None,
            "p_value": round(pval, 4) if pval is not None else None,
            "n_paired": len(human_agg_per_query),
        }
    return results


def _slim_for_json(run_data: dict) -> dict:
    """Return run_data with raw LLM outputs removed to keep file size reasonable."""
    import copy
    slim = copy.deepcopy(run_data)
    for entry in slim.get("queries", []):
        for jscore in entry.get("judge_scores", {}).values():
            jscore.pop("raw", None)
    return slim


def _render_markdown(run_data: dict) -> str:
    agg = run_data.get("aggregate", {})
    meta = run_data.get("meta", {})
    queries = run_data.get("queries", [])

    ts = meta.get("timestamp", datetime.now().isoformat())
    n_q = meta.get("n_queries", len(queries))
    elapsed = meta.get("elapsed_seconds", "?")

    lines = [
        "# Evaluation Report — Multi-Judge Triangulation",
        "",
        f"**Generated:** {ts}  ",
        f"**Queries evaluated:** {n_q}  ",
        f"**Elapsed:** {elapsed}s  ",
        f"**Judges:** {', '.join(j.name for j in []) or _judge_names_from_data(queries)}",
        "",
        "---",
        "",
        "## Per-Judge Per-Criterion Scores",
        "",
    ]

    pjpc = agg.get("per_judge_per_criterion", {})
    for jname, crits in pjpc.items():
        lines.append(f"### Judge: `{jname}`")
        lines.append("")
        lines.append("| Criterion | Mean | Std | N |")
        lines.append("|-----------|------|-----|---|")
        for crit, stats in crits.items():
            lines.append(
                f"| {crit} | {stats['mean']:.2f} | {stats['std']:.2f} | {stats['n']} |"
            )
        lines.append("")

    # Inter-judge correlation
    lines += [
        "## Inter-Judge Correlation (Spearman)",
        "",
        "| Pair | Spearman r | p-value | N |",
        "|------|-----------|---------|---|",
    ]
    for pair, corr_data in agg.get("inter_judge_correlation", {}).items():
        r = corr_data.get("spearman_r")
        p = corr_data.get("p_value")
        n = corr_data.get("n", "?")
        r_str = f"{r:.4f}" if r is not None else "N/A"
        p_str = f"{p:.4f}" if p is not None else "N/A"
        lines.append(f"| {pair} | {r_str} | {p_str} | {n} |")
    lines.append("")

    # Human triangulation
    jvh = agg.get("judge_vs_human", {})
    if jvh and "error" not in jvh and "note" not in jvh:
        lines += [
            "## Judge vs Human Triangulation (Spearman)",
            "",
            "| Judge | Spearman r | p-value | N paired |",
            "|-------|-----------|---------|----------|",
        ]
        for jn, corr_data in jvh.items():
            r = corr_data.get("spearman_r")
            p = corr_data.get("p_value")
            n = corr_data.get("n_paired", "?")
            r_str = f"{r:.4f}" if r is not None else "N/A"
            p_str = f"{p:.4f}" if p is not None else "N/A"
            lines.append(f"| {jn} | {r_str} | {p_str} | {n} |")
        lines.append("")
    elif "note" in jvh:
        lines += [f"> **Human triangulation:** {jvh['note']}", ""]
    elif "error" in jvh:
        lines += [f"> **Human triangulation error:** {jvh['error']}", ""]

    # Per-query summary
    lines += [
        "## Per-Query Summary",
        "",
        "| ID | Query | Score (strict) | Score (persona) | Status |",
        "|----|-------|---------------|----------------|--------|",
    ]
    for row in agg.get("per_query_summary", []):
        qid = row.get("query_id", "?")
        qtext = row.get("query_text", "")[:60].replace("|", "/")
        ss = row.get("score_strict", 0)
        sp = row.get("score_persona", 0)
        status = row.get("status", "?")
        lines.append(f"| {qid} | {qtext} | {ss:.2f} | {sp:.2f} | {status} |")
    lines.append("")

    # Detailed per-query rationales
    lines += ["## Detailed Rationales", ""]
    for entry in queries:
        q = entry.get("query", {})
        qid = q.get("id", "?")
        qtext = q.get("query", "")
        lines += [f"### Query {qid}: {qtext[:80]}", ""]
        for jname, jscore in entry.get("judge_scores", {}).items():
            scores_str = ", ".join(
                f"{k}={v}" for k, v in jscore.get("scores", {}).items()
            )
            rationale = jscore.get("rationale", "")
            lines += [
                f"**{jname}** — scores: {scores_str}",
                f"> {rationale}",
                "",
            ]

    # Interpretation notes
    lines += [
        "---",
        "",
        "## Interpretation Notes",
        "",
        "- Scores are on a 1–5 integer scale; 3 is the default for missing/unparseable criteria.",
        "- `strict_rubric` emphasises academic rigour and source quality.",
        "- `hci_grad_student` emphasises practical utility for literature review.",
        "- High inter-judge Spearman r (>0.7) indicates strong agreement; low r suggests judges diverge in their evaluation lens.",
        "- Human triangulation requires real scores in `data/human_eval.csv`; stub data is illustrative only.",
        "",
    ]

    return "\n".join(lines)


def _judge_names_from_data(queries: list[dict]) -> str:
    names: set[str] = set()
    for entry in queries:
        names.update(entry.get("judge_scores", {}).keys())
    return ", ".join(sorted(names)) if names else "none"
