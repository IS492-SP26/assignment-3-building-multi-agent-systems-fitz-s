"""
Main Entry Point
Can be used to run the system or evaluation.

Usage:
  python main.py --mode cli           # Run CLI interface
  python main.py --mode web           # Run web interface
  python main.py --mode evaluate      # Run evaluation
  python main.py --mode demo          # End-to-end demo: Q1 + export JSON + MD
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path


def run_cli(replay: str | None = None, no_live: bool = False):
    """Run CLI interface."""
    from src.ui.cli import main as cli_main
    cli_main(replay_arg=replay, no_live=no_live)


def run_web():
    """Run web interface."""
    import subprocess
    print("Starting Streamlit web interface...")
    subprocess.run(["streamlit", "run", "src/ui/streamlit_app.py"])


async def run_evaluation(limit: int | None = None):
    """Run batch evaluation with multi-judge triangulation."""
    import yaml
    from dotenv import load_dotenv
    from src.autogen_orchestrator import AutoGenOrchestrator
    from src.evaluation.judge import StrictRubricJudge, PersonaJudge
    from src.evaluation.evaluator import SystemEvaluator

    load_dotenv()

    with open("config.yaml", "r") as f:
        config = yaml.safe_load(f)

    # Override model provider to use vLLM endpoint
    config.setdefault("models", {}).setdefault("default", {})
    config["models"]["default"]["provider"] = "openai"
    config["models"]["default"]["name"] = "Qwen/Qwen3-8B"

    queries = json.loads(Path("data/example_queries.json").read_text())
    if limit:
        queries = queries[:limit]

    print(f"Running batch evaluation on {len(queries)} queries...")
    print(f"Judges: StrictRubricJudge, PersonaJudge (Qwen/Qwen3-8B)")
    print("=" * 70)

    orchestrator = AutoGenOrchestrator(config)
    judges = [StrictRubricJudge(config), PersonaJudge(config)]
    evaluator = SystemEvaluator(orchestrator, judges, config)

    run_data = await evaluator.run_batch_async(queries)
    json_path, md_path = evaluator.generate_report(run_data)

    agg = run_data.get("aggregate", {})
    pjpc = agg.get("per_judge_per_criterion", {})

    print("\n=== Per-judge per-criterion means ===")
    for jname, crits in pjpc.items():
        print(f"\n  [{jname}]")
        for crit, stats in crits.items():
            print(f"    {crit}: mean={stats['mean']:.2f}  std={stats['std']:.2f}")

    print("\n=== Inter-judge correlation ===")
    for pair, data in agg.get("inter_judge_correlation", {}).items():
        r = data.get("spearman_r")
        p = data.get("p_value")
        print(f"  {pair}: r={r}  p={p}  n={data.get('n')}")

    print("\n=== Per-query summary ===")
    for row in agg.get("per_query_summary", []):
        print(
            f"  Q{row['query_id']} | strict={row['score_strict']:.2f} "
            f"| persona={row['score_persona']:.2f} | {row['status']}"
        )

    elapsed = run_data.get("meta", {}).get("elapsed_seconds", "?")
    print(f"\nTotal time: {elapsed}s")
    print(f"Reports written:\n  {json_path}\n  {md_path}")


def run_autogen():
    """Run AutoGen example."""
    import subprocess
    print("Running AutoGen example...")
    subprocess.run([sys.executable, "example_autogen.py"])


def run_demo():
    """End-to-end demo: run Q1, print summary, export JSON + MD."""
    import yaml
    from dotenv import load_dotenv
    from src.autogen_orchestrator import AutoGenOrchestrator

    load_dotenv()
    with open("config.yaml") as f:
        config = yaml.safe_load(f)

    query = "What are the key open challenges in agentic UX as of 2025?"
    print(f"\n[DEMO] Query: {query}\n")

    orch = AutoGenOrchestrator(config)
    result = orch.process_query(query)

    meta = result.get("metadata", {})
    sources = result.get("sources", {})
    src_count = len(sources) if isinstance(sources, dict) else len(sources or [])
    events = result.get("safety_events", [])
    response = result.get("response", "")

    print(f"[DEMO] status={meta.get('status')} sources={src_count} safety_events={len(events)}")
    print(f"\n--- Final Answer (first 600 chars) ---\n{response[:600]}\n")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path("outputs")
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / f"demo_session_{ts}.json"
    with open(json_path, "w") as f:
        json.dump({"query": query, "result": result}, f, indent=2, default=str)

    md_path = out_dir / f"demo_answer_{ts}.md"
    md_content = f"# Demo Answer\n\n**Query:** {query}\n\n**Status:** {meta.get('status')}\n\n**Sources:** {src_count}\n\n## Final Answer\n\n{response}\n"
    with open(md_path, "w") as f:
        f.write(md_content)

    print(f"[DEMO] Exported:\n  {json_path}\n  {md_path}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Multi-Agent Research Assistant"
    )
    parser.add_argument(
        "--mode",
        choices=["cli", "web", "evaluate", "autogen", "demo"],
        default="autogen",
        help="Mode to run: cli, web, evaluate, autogen (default), or demo"
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to configuration file"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of queries for evaluate mode (useful for smoke tests)"
    )
    parser.add_argument(
        "--replay",
        default=None,
        metavar="Q1|Q5|Q6|PATH",
        help="Replay a saved session JSON (Q1/Q5/Q6 alias or file path). CLI mode only."
    )
    parser.add_argument(
        "--no-live",
        action="store_true",
        default=False,
        help="Disable Live widget — plain stdout output (CI-friendly). CLI mode only."
    )
    args = parser.parse_args()

    if args.mode == "cli":
        run_cli(replay=args.replay, no_live=args.no_live)
    elif args.mode == "web":
        run_web()
    elif args.mode == "evaluate":
        asyncio.run(run_evaluation(limit=args.limit))
    elif args.mode == "autogen":
        run_autogen()
    elif args.mode == "demo":
        run_demo()


if __name__ == "__main__":
    main()
