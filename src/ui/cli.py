# Created: 2026-05-07
# Last reused or audited: 2026-05-07
# Authority basis: Plan §UI-CLI + Phase 7 implementation spec
"""
Polished CLI — Phase 7.
Rich-based REPL and replay mode mirroring Streamlit dashboard information density.
"""

import json
import re
import sys
import time
from pathlib import Path
from datetime import datetime

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.markdown import Markdown
from rich.text import Text
from rich.table import Table
from rich.columns import Columns
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.rule import Rule
from rich.align import Align

# ── Design tokens (must match outputs/design/styles.css) ─────────────────────
AGENT_STYLE: dict[str, str] = {
    "planner":             "#39c5cf",
    "web_researcher":      "#3fb950",
    "academic_researcher": "#bc8cff",
    "counter_evidence":    "#d29922",
    "optimist":            "#58a6ff",
    "skeptic":             "#ff7b72",
    "research_manager":    "#ffa657",
    "writer":              "#2f81f7",
    "editor":              "#f778ba",
    "user":                "#8b949e",
}
GUARDRAIL_COLOR = "#f85149"
ACCENT_BLUE = "#58a6ff"
DIM_COLOR = "#484f58"

PIPELINE_STAGES = ["plan", "web", "acad", "counter", "debate", "write", "critic"]

# Stage → agent name mapping for pipeline stepper inference
STAGE_MAP = {
    "stage_1_planning":  "plan",
    "stage_2_evidence":  None,   # disambiguated by agent
    "stage_3_debate":    "debate",
    "stage_4_writing":   "write",
    "stage_5_critique":  "critic",
}
AGENT_STAGE_MAP = {
    "web_researcher":      "web",
    "academic_researcher": "acad",
    "counter_evidence":    "counter",
    "planner":             "plan",
    "optimist":            "debate",
    "skeptic":             "debate",
    "research_manager":    "debate",
    "writer":              "write",
    "editor":              "critic",
}

# ── Session files (short aliases for --replay) ────────────────────────────────
SESSION_ALIASES = {
    "Q1": "outputs/sessions/Q1_normal.json",
    "Q5": "outputs/sessions/Q5_contested.json",
    "Q6": "outputs/sessions/Q6_injection.json",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _agent_color(name: str) -> str:
    for k, c in AGENT_STYLE.items():
        if k in name.lower():
            return c
    return "#8b949e"


def _highlight_citations(text: str) -> str:
    """Replace [S\\d+] with rich-styled markup."""
    return re.sub(r"\[(S\d+)\]", r"[bold #bc8cff][\1][/bold #bc8cff]", text)


def _truncate(text: str, max_chars: int = 600) -> str:
    text = text.strip()
    if len(text) > max_chars:
        return text[:max_chars] + "\n[dim]… (truncated)[/dim]"
    return text


def _fmt_timestamp(ts: str) -> str:
    try:
        dt = datetime.fromisoformat(ts)
        return dt.strftime("%H:%M:%S")
    except Exception:
        return ts[:8] if ts else ""


def _derive_pipeline_state(history: list[dict]) -> dict:
    """Return dict: stage -> 'done'|'active'|'pending'. Last seen = active."""
    done: set[str] = set()
    for msg in history:
        agent = msg.get("agent", "")
        stage_key = msg.get("stage", "")
        mapped = STAGE_MAP.get(stage_key) or AGENT_STAGE_MAP.get(agent)
        if mapped:
            done.add(mapped)
    # build ordered result
    result = {}
    found_first_pending = False
    for s in PIPELINE_STAGES:
        if s in done:
            result[s] = "done"
        elif not found_first_pending:
            result[s] = "active"
            found_first_pending = True
        else:
            result[s] = "pending"
    return result


# ── Renderables ───────────────────────────────────────────────────────────────

def render_message(msg: dict) -> Panel:
    """Render one conversation_history entry as a rich Panel."""
    name = msg.get("agent", msg.get("role", "?"))
    color = _agent_color(name)
    stage = msg.get("stage") or msg.get("role") or ""
    ts = _fmt_timestamp(msg.get("timestamp", ""))
    body = msg.get("content", "")
    body = _truncate(body, 600)
    body = _highlight_citations(body)

    label = f"[{color}]●[/{color}] [{color} bold]{name.replace('_', ' ').title()}[/{color} bold]"
    meta = f"[dim]{stage}[/dim]  [dim]{ts}[/dim]"
    title = f"{label}  {meta}"

    is_guardrail = "guardrail" in name.lower() or "refused" in stage.lower()
    border = GUARDRAIL_COLOR if is_guardrail else DIM_COLOR

    return Panel(
        Markdown(body),
        title=title,
        border_style=border,
        expand=True,
    )


def render_status_panel(state: dict, sources_count: int, safety_events: list) -> Panel:
    """Right-column status panel."""
    # Active agent
    last_agent = state.get("last_agent", "—")
    last_color = _agent_color(last_agent)
    active_line = Text()
    active_line.append("● ", style=last_color)
    active_line.append(last_agent.replace("_", " ").title(), style=f"bold {last_color}")
    active_line.append(f"  {state.get('last_action', '')}", style="dim")

    # Pipeline stepper
    pipe_state = state.get("pipeline", {})
    dots = Text()
    dot_styles = {"done": "#3fb950", "active": ACCENT_BLUE, "pending": DIM_COLOR}
    symbols = {"done": "●", "active": "◐", "pending": "○"}
    for i, s in enumerate(PIPELINE_STAGES):
        st = pipe_state.get(s, "pending")
        dots.append(symbols[st], style=dot_styles[st])
        if i < len(PIPELINE_STAGES) - 1:
            dots.append(" ")

    # Safety panel
    safety_color = GUARDRAIL_COLOR if any(not e.get("passed", True) or e.get("severity") == "block" for e in safety_events) else "#3fb950"
    safety_line = Text()
    safety_line.append(f"Safety: ", style="bold")
    safety_line.append(f"{len(safety_events)} event(s)", style=safety_color)
    if safety_events:
        last_ev = safety_events[-1]
        msg = last_ev.get("message", "")[:40]
        safety_line.append(f"\n  {msg}", style="dim")

    body = Text()
    body.append("Active Agent\n", style="dim bold")
    body.append_text(active_line)
    body.append("\n\n")
    body.append("Pipeline\n", style="dim bold")
    body.append_text(dots)
    body.append(f"\n{' '.join(PIPELINE_STAGES)}", style="dim")
    body.append("\n\n")
    body.append_text(safety_line)
    body.append("\n\n")
    body.append(f"Sources: {sources_count}", style="bold")

    return Panel(body, title="[bold]Status[/bold]", border_style=DIM_COLOR, expand=True)


def render_history_panel(session_history: list[str], active_idx: int) -> Panel:
    """Left-column past queries panel."""
    t = Text()
    for i, q in enumerate(session_history):
        if i == active_idx:
            t.append("▎ ", style=ACCENT_BLUE)
            t.append(q[:30] + ("…" if len(q) > 30 else "") + "\n", style=f"bold {ACCENT_BLUE}")
        else:
            t.append("  ", style="dim")
            t.append(q[:30] + ("…" if len(q) > 30 else "") + "\n", style="dim")
    if not session_history:
        t.append("(no queries yet)", style="dim")
    return Panel(t, title="[bold]History[/bold]", border_style=DIM_COLOR, expand=True)


def render_banner(console: Console) -> None:
    console.print()
    console.print(Rule(style=ACCENT_BLUE))
    console.print(Align.center(
        Text("Multi-Agent Deep Research", style=f"bold {ACCENT_BLUE}")
    ))
    console.print(Align.center(
        Text("HCI-Focused Pipeline  ·  9 Agents  ·  Safety-First", style="dim")
    ))
    console.print(Align.center(
        Text("Phase 7 — Rich CLI  v1.0", style="dim")
    ))
    console.print(Rule(style=ACCENT_BLUE))
    console.print()


def render_final_answer(result: dict, query: str, console: Console) -> None:
    """Print final answer panel, sources, and safety summary."""
    meta = result.get("metadata", {})
    response = result.get("response", "")
    sources = result.get("sources", {})
    safety_events = result.get("safety_events", [])

    status = meta.get("status", "complete")

    # Refused banner
    if status == "refused":
        cat = meta.get("refusal_category", "")
        refused_text = Text()
        refused_text.append("REFUSED", style=f"bold {GUARDRAIL_COLOR}")
        if cat:
            refused_text.append(f" — {cat}", style=GUARDRAIL_COLOR)
        for ev in safety_events:
            refused_text.append(f"\n  {ev.get('message', '')}", style=f"dim {GUARDRAIL_COLOR}")
        console.print(Panel(refused_text, title="[bold red]Safety Block[/bold red]",
                            border_style=GUARDRAIL_COLOR))
        return

    # Final answer
    if response:
        console.print(Panel(
            Markdown(_highlight_citations(response)),
            title=f"[bold {ACCENT_BLUE}]Final Answer[/bold {ACCENT_BLUE}]",
            border_style=ACCENT_BLUE,
        ))

    # Sources footer
    src_list = list(sources.values()) if isinstance(sources, dict) else (sources or [])
    if src_list:
        src_table = Table(show_header=True, header_style="bold dim", box=None, padding=(0, 1))
        src_table.add_column("#", style="dim", width=3)
        src_table.add_column("Source", style="#3fb950")
        src_table.add_column("URL", style="dim")
        for i, s in enumerate(src_list[:12], 1):
            if isinstance(s, dict):
                title_val = s.get("title", "") or s.get("name", "")
                url_val = s.get("url", "")
            else:
                title_val = str(s)
                url_val = ""
            src_table.add_row(str(i), title_val[:60], url_val[:60])
        console.print(Panel(src_table, title=f"[bold]Sources ({len(src_list)})[/bold]",
                            border_style=DIM_COLOR))

    # Safety summary
    if safety_events:
        ev_text = Text()
        for ev in safety_events:
            passed = ev.get("passed", True)
            sev = ev.get("severity", "")
            icon = "✓" if (passed and sev != "block") else "✗"
            color = "#3fb950" if icon == "✓" else GUARDRAIL_COLOR
            ev_text.append(f"  {icon} ", style=color)
            ev_text.append(f"{ev.get('category', '')}  {ev.get('message', '')[:70]}\n",
                           style="dim")
        console.print(Panel(ev_text, title=f"[bold]Safety Events ({len(safety_events)})[/bold]",
                            border_style=DIM_COLOR))

    # Stats footer
    console.print(Rule(style=DIM_COLOR))
    console.print(
        f"  [dim]status=[/dim]{status}  "
        f"[dim]sources=[/dim]{len(src_list)}  "
        f"[dim]safety_events=[/dim]{len(safety_events)}  "
        f"[dim]duration=[/dim]{meta.get('total_duration_seconds', '?')}s"
    )
    console.print()


# ── Replay mode ───────────────────────────────────────────────────────────────

def _load_session(replay_arg: str) -> tuple[str, dict]:
    """Load session JSON. Accept alias (Q1/Q5/Q6) or file path."""
    path_str = SESSION_ALIASES.get(replay_arg, replay_arg)
    path = Path(path_str)
    if not path.is_absolute():
        path = project_root / path
    if not path.exists():
        raise FileNotFoundError(f"Session file not found: {path}")
    with open(path) as f:
        data = json.load(f)
    query = data.get("query", "")
    result = data.get("result", data)
    return query, result


def replay(replay_arg: str, no_live: bool = False, delay: float = 0.3) -> None:
    """Animate a pre-recorded session JSON."""
    console = Console(force_terminal=not no_live)

    try:
        query, result = _load_session(replay_arg)
    except FileNotFoundError as e:
        console.print(f"[red]Error: {e}[/red]")
        return

    render_banner(console)
    console.print(f"[dim]Replaying:[/dim] [bold {ACCENT_BLUE}]{replay_arg}[/bold {ACCENT_BLUE}]")
    console.print(f"[dim]Query:[/dim] {query}\n")

    history = result.get("conversation_history", [])
    safety_events = result.get("safety_events", [])
    sources = result.get("sources", {})
    src_count = len(sources) if isinstance(sources, dict) else len(sources or [])

    if no_live:
        # Plain stdout mode — line-by-line, no Live widget
        for msg in history:
            console.print(render_message(msg))
            time.sleep(delay)
    else:
        # Live animated mode
        rendered: list[Panel] = []
        pipe_state = {}

        with Live(console=console, refresh_per_second=4, screen=False) as live:
            for msg in history:
                rendered.append(render_message(msg))
                pipe_state = _derive_pipeline_state(history[:history.index(msg) + 1])
                status_state = {
                    "last_agent": msg.get("agent", "?"),
                    "last_action": msg.get("stage", ""),
                    "pipeline": pipe_state,
                }
                # Stack rendered messages + status
                group_renderables = list(rendered)
                group_renderables.append(
                    render_status_panel(status_state, src_count, safety_events)
                )
                from rich.console import Group
                live.update(Group(*group_renderables))
                time.sleep(delay)

    render_final_answer(result, query, console)


# ── Interactive REPL ──────────────────────────────────────────────────────────

def _run_with_spinner(orch, query: str, console: Console) -> dict:
    """Run orchestrator with a progress spinner. Returns result dict."""
    import threading

    result_holder: dict = {}
    exc_holder: list = []

    def _worker():
        try:
            result_holder["result"] = orch.process_query(query)
        except Exception as e:
            exc_holder.append(e)

    t = threading.Thread(target=_worker, daemon=True)

    stage_messages = [
        ("plan",   "[dim]Planning research strategy…[/dim]"),
        ("web",    "[dim]Gathering web evidence…[/dim]"),
        ("acad",   "[dim]Searching academic sources…[/dim]"),
        ("debate", "[dim]Running debate round…[/dim]"),
        ("write",  "[dim]Drafting answer…[/dim]"),
        ("critic", "[dim]Editing and polishing…[/dim]"),
    ]

    with Progress(
        SpinnerColumn(style=ACCENT_BLUE),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Starting pipeline…", total=None)
        t.start()

        stage_idx = 0
        while t.is_alive():
            if stage_idx < len(stage_messages):
                _, label = stage_messages[stage_idx]
                progress.update(task, description=label)
                t.join(timeout=8.0)
                stage_idx += 1
            else:
                t.join(timeout=2.0)

    if exc_holder:
        raise exc_holder[0]
    return result_holder.get("result", {})


def interactive_repl(no_live: bool = False) -> None:
    """Full REPL loop."""
    console = Console(force_terminal=not no_live)

    import yaml
    from dotenv import load_dotenv
    load_dotenv()

    with open(project_root / "config.yaml") as f:
        config = yaml.safe_load(f)

    from src.autogen_orchestrator import AutoGenOrchestrator
    orch = AutoGenOrchestrator(config)

    render_banner(console)
    console.print("Type your query and press Enter. Use backslash (\\) at line-end for multi-line.")
    console.print("Type [bold]quit[/bold] or [bold]exit[/bold], or press Ctrl-C to exit.\n")

    session_history: list[str] = []

    while True:
        try:
            # Prompt
            prompt_text = Text()
            prompt_text.append("? ", style=f"bold {ACCENT_BLUE}")
            prompt_text.append("Query > ", style="bold")
            console.print(prompt_text, end="")
            lines = []
            while True:
                line = input()
                if line.endswith("\\"):
                    lines.append(line[:-1])
                    console.print("  ", end="")
                else:
                    lines.append(line)
                    break
            query = " ".join(lines).strip()

        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Session ended.[/dim]")
            sys.exit(0)

        if not query:
            continue
        if query.lower() in ("quit", "exit"):
            console.print("[dim]Session ended.[/dim]")
            sys.exit(0)

        session_history.append(query)
        active_idx = len(session_history) - 1

        # Run pipeline
        console.print()
        try:
            result = _run_with_spinner(orch, query, console)
        except KeyboardInterrupt:
            console.print("[dim]Interrupted.[/dim]")
            continue
        except Exception as e:
            console.print(f"[red]Pipeline error: {e}[/red]")
            continue

        # Replay-animate the returned trace
        history = result.get("conversation_history", [])
        safety_events = result.get("safety_events", [])
        sources = result.get("sources", {})
        src_count = len(sources) if isinstance(sources, dict) else len(sources or [])

        if no_live or not sys.stdout.isatty():
            for msg in history:
                console.print(render_message(msg))
        else:
            rendered: list[Panel] = []
            with Live(console=console, refresh_per_second=4, screen=False) as live:
                for msg in history:
                    rendered.append(render_message(msg))
                    pipe_state = _derive_pipeline_state(history[:history.index(msg) + 1])
                    status_state = {
                        "last_agent": msg.get("agent", "?"),
                        "last_action": msg.get("stage", ""),
                        "pipeline": pipe_state,
                    }
                    from rich.console import Group
                    live.update(Group(*rendered, render_status_panel(
                        status_state, src_count, safety_events
                    )))
                    time.sleep(0.2)

        render_final_answer(result, query, console)
        console.print(Rule(style=DIM_COLOR))
        console.print()


# ── Public entry point ────────────────────────────────────────────────────────

def main(replay_arg: str | None = None, no_live: bool = False) -> None:
    if replay_arg:
        replay(replay_arg, no_live=no_live)
    else:
        interactive_repl(no_live=no_live)


class CLI:
    """Thin wrapper for compatibility with src/ui/__init__.py."""

    def __init__(self, config: dict | None = None):
        self.config = config

    def run(self, replay_arg: str | None = None, no_live: bool = False):
        main(replay_arg=replay_arg, no_live=no_live)


if __name__ == "__main__":
    main()
