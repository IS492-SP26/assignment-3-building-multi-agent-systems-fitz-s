"""
Safety event coordinator.

Created: 2026-05-07
Last reused or audited: 2026-05-07
Authority basis: Plan §Guardrails. Categories: 5 (incl. ★unsourced_claims
which translates Fitz Constraint #4 to LLM output).

Aggregates input_guardrail and output_guardrail. Logs events to
logs/safety_events.log as JSON lines for UI consumption.
"""
import json
import logging
import os
from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Optional, Any

LOG_DIR = "logs"
SAFETY_LOG_FILE = "logs/safety_events.log"


@dataclass
class SafetyEvent:
    category: str           # one of the 5 categories above
    severity: str           # "info", "warning", "block"
    action: str             # "pass", "sanitize", "refuse", "revise"
    message: str            # human-readable
    evidence: dict = field(default_factory=dict)  # what triggered it
    agent_active: Optional[str] = None
    query_id: Optional[str] = None
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.utcnow().isoformat()


class SafetyManager:
    def __init__(self, config: dict):
        self.config = config.get("safety", {})
        self.enabled = self.config.get("enabled", True)
        self.events: list = []  # in-memory for current query
        self._current_query_id: Optional[str] = None
        os.makedirs(LOG_DIR, exist_ok=True)
        self._logger = logging.getLogger("safety")
        # File handler for safety_events.log (JSON lines)
        if not any(isinstance(h, logging.FileHandler) for h in self._logger.handlers):
            fh = logging.FileHandler(SAFETY_LOG_FILE)
            fh.setLevel(logging.INFO)
            self._logger.addHandler(fh)
            self._logger.setLevel(logging.INFO)

    def set_active_agent(self, agent_name: str):
        self._active_agent = agent_name

    def record(self, event: SafetyEvent):
        if event.agent_active is None:
            event.agent_active = getattr(self, "_active_agent", None)
        self.events.append(event)
        if self.config.get("log_events", True):
            self._logger.info(json.dumps(asdict(event)))

    def reset_for_query(self, query_id: str):
        self.events = []
        self._current_query_id = query_id

    def get_events(self) -> list:
        return [asdict(e) for e in self.events]

    def has_blocking_event(self) -> bool:
        return any(e.action == "refuse" for e in self.events)

    # Wiring helpers for orchestrator
    def check_input(self, query: str, input_guardrail) -> tuple:
        """Returns (passed, event). If passed=False, orchestrator should abort."""
        if not self.enabled or not input_guardrail:
            return True, None
        event = input_guardrail.validate(query)
        if event:
            event.query_id = self._current_query_id
            self.record(event)
            if event.action == "refuse":
                return False, event
        return True, event

    def check_output(self, output: str, source_registry, output_guardrail) -> tuple:
        """Returns (passed, events, sanitized_text_or_None)."""
        if not self.enabled or not output_guardrail:
            return True, [], None
        events, sanitized = output_guardrail.validate(output, source_registry)
        for e in events:
            e.query_id = self._current_query_id
            self.record(e)
        if any(e.action == "refuse" for e in events):
            return False, events, sanitized
        return True, events, sanitized
