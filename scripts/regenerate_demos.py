# Created: 2026-05-07
# Last reused or audited: 2026-05-07
# Authority basis: user feedback 2026-05-07 — refresh Q1/Q5/Q6 demo sessions to
#   2026-grade queries; eliminate stale Googleable content.
#
# Usage (run from repo root, takes ~5-10 min):
#   .venv/bin/python scripts/regenerate_demos.py
#
# DO NOT run this automatically from CI — it consumes LLM API budget and writes
# to outputs/sessions/, overwriting the graded demo files. Trigger manually after
# verifying the new queries in data/example_queries.json.
"""Regenerate Q1/Q5/Q6 demo session files by running the canonical 2026-grade
queries through the live orchestrator. Saves results to outputs/sessions/ as
Q1_normal.json, Q5_contested.json, Q6_injection.json.

Run once after queries are updated in data/example_queries.json."""
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import os
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")
SESSIONS = ROOT / "outputs" / "sessions"
SESSIONS.mkdir(parents=True, exist_ok=True)

with open(ROOT / "config.yaml") as f:
    config = yaml.safe_load(f)

# Normalize provider: vLLM endpoint speaks OpenAI protocol but
# autogen_agents.create_model_client only knows "openai"/"groq".
# Same patch as src/ui/streamlit_app.py:get_orchestrator() applies.
models = config.setdefault("models", {})
for slot in ("default", "judge"):
    mc = models.get(slot)
    if isinstance(mc, dict) and mc.get("provider") == "vllm":
        mc["provider"] = "openai"
        env_model = os.getenv("OPENAI_MODEL")
        if env_model:
            mc["name"] = env_model

queries = json.loads((ROOT / "data" / "example_queries.json").read_text())
demo_map = {1: "Q1_normal.json", 5: "Q5_contested.json", 6: "Q6_injection.json"}


async def run_one(qid: int, qtext: str, fname: str) -> None:
    from src.autogen_orchestrator import AutoGenOrchestrator

    print(f"[{qid}] starting: {qtext[:70]}...", flush=True)
    orch = AutoGenOrchestrator(config)
    t0 = time.time()
    result = await orch.process_query_async(qtext)
    dur = time.time() - t0
    num_msgs = (result.get("metadata") or {}).get("num_messages", 0)
    print(f"[{qid}] done in {dur:.1f}s — {num_msgs} msgs", flush=True)
    out = SESSIONS / fname
    out.write_text(
        json.dumps(
            {"query": qtext, "result": result},
            default=str,
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"[{qid}] saved {out}", flush=True)


async def main() -> None:
    tasks = []
    for q in queries:
        qid = q.get("id")
        if qid in demo_map:
            tasks.append(run_one(qid, q.get("query", ""), demo_map[qid]))
    await asyncio.gather(*tasks)
    print("All demo sessions regenerated.", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
