"""
Input guardrail — pre-pipeline safety check on user query.

Created: 2026-05-07
Last reused or audited: 2026-05-07
Authority basis: Plan §Guardrails categories 1-3.

Two layers:
  Layer 1: regex / keyword / length (fast, zero-cost)
  Layer 2: Qwen3-8B classifier for off-topic / nuanced harm (cached)
"""
import re
from typing import Optional
from src.guardrails.safety_manager import SafetyEvent

# Patterns
PROMPT_INJECTION_PATTERNS = [
    r"ignore (all |the |your |my )?(previous|prior|above) (instructions|directives|prompts)",
    r"disregard (all |the )?(previous|prior|above)",
    r"forget (your |the |all )?(previous|prior|earlier|above)",
    r"system:\s*",
    r"<\|im_start\|>",
    r"```system",
    r"reveal (your |the )?(system )?prompt",
    r"what (are |is )?your (system )?(prompt|instructions)",
]

HARMFUL_KEYWORDS = [
    # Unauthorized security testing
    "hack into", "bypass authentication", "exploit vulnerability", "ddos attack", "ransomware",
    # Violence
    "how to kill", "make a bomb", "weapon to harm",
    # Self-harm
    "how to commit suicide",
]

# LLM classifier prompt for off-topic check
TOPIC_CHECK_PROMPT = """You are a topic classifier. The system researches Human-Computer Interaction (HCI), specifically Agentic UX and AI-driven prototyping. Related topics include: user experience, human-AI interaction, agent design, design patterns, usability, accessibility, design tools.

Classify this query:
QUERY: "{query}"

Reply with exactly one line: "ON_TOPIC" or "OFF_TOPIC: <one phrase reason>".
Do not include <think> blocks. Do not explain. One line only."""


class InputGuardrail:
    def __init__(self, config: dict, model_client=None):
        self.config = config
        self.model_client = model_client  # for layer 2 classifier
        safety_cfg = config.get("safety", {})
        self.min_length = safety_cfg.get("min_query_length", 5)
        self.max_length = safety_cfg.get("max_query_length", 2000)

    def validate(self, query: str) -> Optional[SafetyEvent]:
        """Returns SafetyEvent if blocked/sanitized, None if pass."""
        q = query.strip()
        ql = q.lower()

        # Length
        if len(q) < self.min_length:
            return SafetyEvent(category="malformed_input", severity="warning", action="refuse",
                               message=f"Query too short (<{self.min_length} chars)",
                               evidence={"length": len(q)})
        if len(q) > self.max_length:
            return SafetyEvent(category="malformed_input", severity="warning", action="refuse",
                               message=f"Query too long (>{self.max_length} chars)",
                               evidence={"length": len(q)})

        # Layer 1a: Prompt injection
        for pat in PROMPT_INJECTION_PATTERNS:
            m = re.search(pat, ql, re.IGNORECASE)
            if m:
                return SafetyEvent(category="prompt_injection", severity="block", action="refuse",
                                   message="Detected prompt injection pattern",
                                   evidence={"pattern": pat, "match": m.group(0)[:100]})

        # Layer 1b: Harmful keywords
        for kw in HARMFUL_KEYWORDS:
            if kw in ql:
                return SafetyEvent(category="harmful_content", severity="block", action="refuse",
                                   message="Detected harmful intent keyword",
                                   evidence={"keyword": kw})

        # Layer 2: Off-topic check via LLM classifier
        if self.model_client is not None:
            try:
                import asyncio
                topic = asyncio.run(self._classify_topic_async(q))
                if topic and topic.startswith("OFF_TOPIC"):
                    return SafetyEvent(category="off_topic_queries", severity="warning", action="refuse",
                                       message="Query off-topic for HCI / Agentic UX",
                                       evidence={"classifier_response": topic[:200]})
            except Exception:
                # Don't fail-closed — off-topic is lowest-stakes
                pass

        return None  # passed all checks

    async def _classify_topic_async(self, query: str) -> Optional[str]:
        from autogen_core.models import UserMessage
        from src.agents.autogen_agents import strip_thinking
        msg = UserMessage(content=TOPIC_CHECK_PROMPT.format(query=query[:500]), source="user")
        result = await self.model_client.create([msg])
        return strip_thinking(result.content).strip().split("\n")[0]
