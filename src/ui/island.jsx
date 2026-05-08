/* Created: 2026-05-07
 * Last reused or audited: 2026-05-07 (Fix 1: aria-labelledby="eval-h" + id="eval-h" on both EvalPanel section branches. Fix 2: citedCount computed from actual [Sn] matches in response, displayed as "X of Y sources cited".)
 * Authority basis: Plan §UI Workflow / Implementation Phases 5-6 + user feedback 2026-05-07 (no fake states)
 *
 * Single Babel/JSX runtime that owns the entire dashboard. Streamlit only
 * mounts the iframe + handles URL params + serves the JSON state. ALL
 * interactive affordances are bound here:
 *   - Stepper:        click → scroll to first agent of that step
 *   - Citation [Sn]:  hover tooltip + click → expand+scroll source
 *   - Source row:     click → toggle .source__details accordion
 *   - Mode chip:      click → toggle local active state
 *   - Export menu:    button → expand 3-format dropdown with download
 *   - History item:   click → setCurrentStateId (client-side, no reload)
 *   - StatePill:      click → setCurrentStateId (client-side, no reload)
 *   - Edit query:     refusal CTA → window.parent.location ?edit=<query>
 *   - Run pipeline:   from EmptyState (idle) → window.parent.location ?run=<query>
 *   - Score judges:   from EvalPanel → ?score=1
 *
 * Bug 1 fix: Idle/Start buttons now call setCurrentStateId('idle') — no goToParent
 *            with empty params that fails to clear existing ?preload= URL.
 * Bug 2 fix: All STATE pill + history item transitions are React setState →
 *            instant re-render, zero iframe remount, zero flicker.
 */
const { useState, useMemo, useEffect, useRef } = React;

// ---------------------------------------------------------------------------
// Bootstrap: read from window.SESSIONS (multi-session) or fall back to legacy
// ---------------------------------------------------------------------------
const _SESSIONS = window.SESSIONS || {};
const _HISTORY  = window.HISTORY  || [];
const _INITIAL_STATE_ID = window.INITIAL_SESSION_ID || "idle";
const _RUN_ACTIVE = window.__RUN_ACTIVE__ === true;

// Helper: get a session by id, returning the empty payload for "idle"/null
function getSession(id) {
  if (!id || id === "idle") return null;
  // 'start' maps to the synthetic just-launched session in window.SESSIONS
  return _SESSIONS[id] || null;
}

// Legacy single-session fallback (used ONLY if window.SESSIONS not present)
const _LEGACY_STATE = (() => {
  try {
    return JSON.parse(document.getElementById("__state_payload__").textContent);
  } catch(e) { return { session: null, history: [] }; }
})();

const PIPELINE_KEYS = ["plan", "web", "acad", "counter", "debate", "write", "critic"];

/* Mode-chip tooltips */
const MODE_TOOLTIPS = {
  autogen: "Default: AutoGen multi-agent orchestration",
  cli:     "Text-only CLI front end (no GUI)",
  web:     "Current Streamlit dashboard (this view)",
  eval:    "Run benchmark suite over saved queries",
  demo:    "One-shot showcase run with cached sources",
};

/* Stage counts for the consistency badge */
const STAGE_COUNT = 4;
const STEP_COUNT  = PIPELINE_KEYS.length; // 7
const AGENT_COUNT = 9;

/* Helper: navigate the Streamlit parent frame.
 * Only used for actions that MUST go to the server: run query, score, edit.
 * State switching (StatePill, history) now uses setCurrentStateId instead.
 */
function goToParent(params) {
  window.parent.postMessage({ type: "omc_navigate", params }, "*");
  return true;
}

/* Update the browser URL bar without triggering a Streamlit reload.
 * Called after client-side state switches for URL shareability.
 */
function updateUrlSilent(stateId) {
  try {
    const url =
      stateId === "idle"           ? "/" :
      stateId === "idle_dashboard" ? "/?idle=1" :
      stateId === "debate"         ? "/?preload=Q5&phase=debate" :
      stateId === "loading"        ? "/?preload=loading" :
      // Round-3 Fix 3: live_<ts> ids load real user-run sessions
      (stateId && stateId.indexOf("live_") === 0) ? `/?preload=${stateId}` :
      `/?preload=${stateId}`;
    window.parent.postMessage({ type: "omc_pushstate", url }, "*");
  } catch(e) {}
}

/* ---------------- Icons ---------------- */
const I = {
  search:  (p) => <svg width="13" height="13" viewBox="0 0 16 16" fill="none" {...p}><circle cx="7" cy="7" r="4.5" stroke="currentColor" strokeWidth="1.4"/><path d="m11 11 3 3" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/></svg>,
  plus:    (p) => <svg width="12" height="12" viewBox="0 0 16 16" fill="none" {...p}><path d="M8 3v10M3 8h10" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/></svg>,
  cog:     (p) => <svg width="14" height="14" viewBox="0 0 16 16" fill="none" {...p}><circle cx="8" cy="8" r="2.2" stroke="currentColor" strokeWidth="1.3"/><path d="M8 1.5v1.8M8 12.7v1.8M14.5 8h-1.8M3.3 8H1.5M12.6 3.4l-1.3 1.3M4.7 11.3l-1.3 1.3M12.6 12.6l-1.3-1.3M4.7 4.7 3.4 3.4" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/></svg>,
  chevR:   (p) => <svg width="10" height="10" viewBox="0 0 16 16" fill="none" {...p}><path d="m6 4 4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>,
  chevD:   (p) => <svg width="10" height="10" viewBox="0 0 16 16" fill="none" {...p}><path d="m4 6 4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>,
  link:    (p) => <svg width="11" height="11" viewBox="0 0 16 16" fill="none" {...p}><path d="M7 9.5c.7.9 1.9 1 2.7.2L12 7.4c.9-.9.9-2.4 0-3.3-.9-.9-2.4-.9-3.3 0L7.4 5.4M9 6.5c-.7-.9-1.9-1-2.7-.2L4 8.6c-.9.9-.9 2.4 0 3.3.9.9 2.4.9 3.3 0L8.6 10.6" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/></svg>,
  download:(p) => <svg width="12" height="12" viewBox="0 0 16 16" fill="none" {...p}><path d="M8 2v8m0 0 3-3m-3 3-3-3M3 13h10" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/></svg>,
  shield:  (p) => <svg width="13" height="13" viewBox="0 0 16 16" fill="none" {...p}><path d="M8 1.5 2.5 3.5v4.7c0 3.3 2.4 5.6 5.5 6.3 3.1-.7 5.5-3 5.5-6.3V3.5L8 1.5Z" stroke="currentColor" strokeWidth="1.3"/></svg>,
  warn:    (p) => <svg width="14" height="14" viewBox="0 0 16 16" fill="none" {...p}><path d="M8 2 1.8 13h12.4L8 2Z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round"/><path d="M8 6.5v3" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/><circle cx="8" cy="11.5" r=".7" fill="currentColor"/></svg>,
  shieldX: (p) => <svg width="16" height="16" viewBox="0 0 16 16" fill="none" {...p}><path d="M8 1.5 2.5 3.5v4.7c0 3.3 2.4 5.6 5.5 6.3 3.1-.7 5.5-3 5.5-6.3V3.5L8 1.5Z" stroke="currentColor" strokeWidth="1.4"/><path d="m6 6 4 4M10 6l-4 4" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/></svg>,
  check:   (p) => <svg width="11" height="11" viewBox="0 0 16 16" fill="none" {...p}><path d="m3.5 8.5 3 3 6-7" stroke="#0d1117" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>,
  x:       (p) => <svg width="11" height="11" viewBox="0 0 16 16" fill="none" {...p}><path d="m4 4 8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/></svg>,
  scales:  (p) => <svg width="12" height="12" viewBox="0 0 16 16" fill="none" {...p}><path d="M8 2v12M3 5h10M3 5l-1.5 4h3L3 5Zm10 0-1.5 4h3L13 5Z" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"/></svg>,
  sparkle: (p) => <svg width="14" height="14" viewBox="0 0 16 16" fill="none" {...p}><path d="M8 1v4M8 11v4M1 8h4M11 8h4M3.5 3.5l2.5 2.5M10 10l2.5 2.5M3.5 12.5l2.5-2.5M10 6l2.5-2.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/></svg>,
};

/* ---------------- Citation chip + click jump ---------------- */
function jumpToSource(id) {
  const el = document.getElementById("source-" + id);
  if (!el) return;
  el.dispatchEvent(new CustomEvent("__open_source__", { bubbles: true }));
  el.classList.add("is-target");
  el.classList.add("source--target");
  setTimeout(() => {
    el.classList.remove("is-target");
    el.classList.remove("source--target");
  }, 1500);
  el.scrollIntoView({ behavior: "smooth", block: "center" });
}

function Cite({ id, railSources }) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState({ top: 0, left: 0 });
  const ref = useRef(null);
  const data = (railSources || {})[id];
  const onClick = (e) => {
    e.stopPropagation();
    e.preventDefault();
    jumpToSource(id);
  };

  const handleEnter = () => {
    if (ref.current) {
      const r = ref.current.getBoundingClientRect();
      setPos({ top: r.bottom + 6, left: Math.min(r.left, window.innerWidth - 316) });
    }
    setOpen(true);
  };

  if (!data) {
    return <span className="cite" onClick={onClick} role="button" tabIndex="0">[{id}]</span>;
  }
  return (
    <span
      ref={ref}
      className="cite"
      tabIndex="0"
      role="button"
      aria-label={"Citation " + id + ": " + data.title}
      onMouseEnter={handleEnter} onMouseLeave={() => setOpen(false)}
      onFocus={handleEnter} onBlur={() => setOpen(false)}
      onClick={onClick}
    >
      [{id}]
      {open && ReactDOM.createPortal(
        <span className="cite-tooltip" role="tooltip"
          style={{ position: "fixed", top: pos.top, left: pos.left, zIndex: 9999 }}>
          <span className="cite-tooltip__type">
            <span>{data.type}</span>
            {data.authority && <span style={{ color: "var(--fg-tertiary)" }}>· {data.authority}</span>}
          </span>
          <div className="cite-tooltip__title">{data.title}</div>
          <div className="cite-tooltip__preview">{data.preview}</div>
          <div className="cite-tooltip__url">{data.url}</div>
        </span>,
        document.body
      )}
    </span>
  );
}

function makeTokenizer(railSources) {
  return function tokenize(text) {
    if (!text) return null;
    const parts = text.split(/(\[S\d+\])/g);
    return parts.map((p, i) => {
      const m = p.match(/^\[S(\d+)\]$/);
      if (m) return <Cite key={i} id={"S" + m[1]} railSources={railSources} />;
      // Return raw string so downstream renderInline can run **bold**/*italic*/`code` parsing.
      // Wrapping in <Fragment> here breaks the typeof===string check in renderInline.
      return p;
    });
  };
}

/* ---------------- Markdown helpers (shared by renderBody + FinalReport) ----
 * parseMarkdown(text): walk lines once, returning blocks[] of:
 *   {kind:"h1"|"h2"|"h3", text}
 *   {kind:"ul"|"ol", items:[]}
 *   {kind:"code", lang, text}
 *   {kind:"p", text}
 * renderInline(text, railSources): returns array of React nodes handling
 *   citation tokens [Sn], **bold**, *italic*, `inline code`.
 */
function parseMarkdown(text) {
  if (!text) return [];
  const lines = text.split("\n");
  const blocks = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    // Fenced code block ```lang ... ```
    if (line.startsWith("```")) {
      const lang = line.slice(3).trim();
      const code = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) {
        code.push(lines[i]);
        i++;
      }
      i++;  // consume closing ```
      blocks.push({ kind: "code", lang: lang, text: code.join("\n") });
      continue;
    }
    // Headings
    if (line.startsWith("### ")) { blocks.push({ kind: "h3", text: line.slice(4) }); i++; continue; }
    if (line.startsWith("## "))  { blocks.push({ kind: "h2", text: line.slice(3) }); i++; continue; }
    if (line.startsWith("# "))   { blocks.push({ kind: "h1", text: line.slice(2) }); i++; continue; }
    // Lists (consume consecutive list lines)
    if (/^\s*[-*]\s+/.test(line) || /^\s*\d+\.\s+/.test(line)) {
      const ordered = /^\s*\d+\./.test(line);
      const items = [];
      while (i < lines.length && (/^\s*[-*]\s+/.test(lines[i]) || /^\s*\d+\.\s+/.test(lines[i]))) {
        items.push(lines[i].replace(/^\s*(?:[-*]|\d+\.)\s+/, ""));
        i++;
      }
      blocks.push({ kind: ordered ? "ol" : "ul", items: items });
      continue;
    }
    // Blank line
    if (line.trim() === "") { i++; continue; }
    // Paragraph (consume until blank or block boundary)
    const para = [line];
    i++;
    while (i < lines.length && lines[i].trim() !== "" && !/^(#{1,3}\s|\s*[-*]\s|\s*\d+\.\s|```)/.test(lines[i])) {
      para.push(lines[i]);
      i++;
    }
    blocks.push({ kind: "p", text: para.join(" ") });
  }
  return blocks;
}

function renderInline(text, railSources) {
  const tokenize = makeTokenizer(railSources);
  // tokens may be array of strings + chip elements; further process strings for **/*/`
  const tokens = tokenize(text) || [];
  const out = [];
  tokens.forEach((tok, idx) => {
    if (typeof tok !== "string") {
      out.push(tok);
      return;
    }
    // Process **bold**, *italic*, `code` via single regex iteration
    const s = tok;
    const regex = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g;
    let lastEnd = 0;
    let m;
    while ((m = regex.exec(s)) !== null) {
      if (m.index > lastEnd) out.push(s.slice(lastEnd, m.index));
      const tt = m[0];
      const k = idx + "-" + m.index;
      if (tt.startsWith("**")) out.push(<strong key={k}>{tt.slice(2, -2)}</strong>);
      else if (tt.startsWith("`")) out.push(<code key={k}>{tt.slice(1, -1)}</code>);
      else if (tt.startsWith("*")) out.push(<em key={k}>{tt.slice(1, -1)}</em>);
      lastEnd = m.index + tt.length;
    }
    if (lastEnd < s.length) out.push(s.slice(lastEnd));
  });
  return out;
}

function renderBody(text, railSources) {
  if (!text) return null;
  const blocks = parseMarkdown(text);
  return blocks.map((b, idx) => {
    if (b.kind === "h1") return <h3 key={idx} style={{ fontFamily: "var(--font-body)", fontWeight: 600, fontSize: "15px", margin: "2px 0 6px" }}>{renderInline(b.text, railSources)}</h3>;
    if (b.kind === "h2") return <h3 key={idx}>{renderInline(b.text, railSources)}</h3>;
    if (b.kind === "h3") return <h3 key={idx} style={{ fontSize: "13px", textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--fg-secondary)" }}>{renderInline(b.text, railSources)}</h3>;
    if (b.kind === "ul") return <ul key={idx}>{b.items.map((it, ii) => <li key={ii}>{renderInline(it, railSources)}</li>)}</ul>;
    if (b.kind === "ol") return <ol key={idx}>{b.items.map((it, ii) => <li key={ii}>{renderInline(it, railSources)}</li>)}</ol>;
    if (b.kind === "code") return <pre key={idx}><code>{b.text}</code></pre>;
    return <p key={idx}>{renderInline(b.text, railSources)}</p>;
  });
}

/* ---------------- Final Report (rendered above trace when complete) -------- */
function FinalReport({ response, session, railSources }) {
  if (!response || !response.trim()) return null;
  const blocks = parseMarkdown(response);
  const numSources = (session && session.meta && session.meta.num_sources) || 0;
  const citedCount = (() => {
    if (!response) return 0;
    const matches = response.match(/\[S\d+\]/g) || [];
    return new Set(matches).size;
  })();
  return (
    <section className="final-report" aria-label="Final report">
      <div className="final-report__head">
        <h2 className="final-report__title">Final Report</h2>
        <span className="final-report__sub">
          synthesized by Writer + Editor · {citedCount} of {numSources} sources cited
        </span>
      </div>
      <div className="final-report__body">
        {blocks.map((b, idx) => {
          if (b.kind === "h1") return <h1 key={idx}>{renderInline(b.text, railSources)}</h1>;
          if (b.kind === "h2") return <h2 key={idx}>{renderInline(b.text, railSources)}</h2>;
          if (b.kind === "h3") return <h3 key={idx}>{renderInline(b.text, railSources)}</h3>;
          if (b.kind === "ul") return <ul key={idx}>{b.items.map((it, ii) => <li key={ii}>{renderInline(it, railSources)}</li>)}</ul>;
          if (b.kind === "ol") return <ol key={idx}>{b.items.map((it, ii) => <li key={ii}>{renderInline(it, railSources)}</li>)}</ol>;
          if (b.kind === "code") return <pre key={idx}><code>{b.text}</code></pre>;
          return <p key={idx}>{renderInline(b.text, railSources)}</p>;
        })}
      </div>
    </section>
  );
}

/* ---------------- CLI Command Modal ---------------- */
function CliCommandModal({ open, onClose }) {
  if (!open) return null;
  const cmd = `python main.py --mode autogen --query "What are the top 3 challenges in agentic UX as of 2026?"`;
  const copy = () => { try { navigator.clipboard.writeText(cmd); } catch(e){} };
  return (
    <div className="cli-modal__backdrop" onClick={onClose}>
      <div className="cli-modal" onClick={(e) => e.stopPropagation()}>
        <div className="cli-modal__head">
          <strong>Run this pipeline from the CLI</strong>
          <button className="cli-modal__close" onClick={onClose} aria-label="Close">×</button>
        </div>
        <p className="cli-modal__desc">
          Same 9-agent pipeline, no UI. Streams agent output to stdout. Useful for batch evaluation or CI.
        </p>
        <pre className="cli-modal__cmd"><code>{cmd}</code></pre>
        <div className="cli-modal__actions">
          <button className="cli-modal__btn" onClick={copy}>Copy</button>
          <button className="cli-modal__btn cli-modal__btn--secondary" onClick={onClose}>Got it</button>
        </div>
      </div>
    </div>
  );
}

/* ---------------- Top Bar — mode chips wired ---------------- */
function TopBar({ mode, setMode, onSkip }) {
  const modes = ["autogen", "cli", "web", "eval", "demo"];

  const [settingsOpen, setSettingsOpen] = useState(false);
  const [cliModalOpen, setCliModalOpen] = useState(false);
  const [theme, setTheme] = useState(() =>
    document.documentElement.getAttribute("data-theme") === "light" ? "Light" : "Dark"
  );

  useEffect(() => {
    const handler = (e) => {
      if (e.key === "Escape") { setSettingsOpen(false); setCliModalOpen(false); }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, []);

  const handleModeChip = (m) => {
    setMode(m);
    switch (m) {
      case "autogen":
      case "web":
        // No-op — this IS the autogen+web mode (the dashboard you're on).
        break;
      case "cli":
        setCliModalOpen(true);
        break;
      case "eval":
        try {
          const el = document.querySelector('[aria-labelledby="eval-h"]') || document.querySelector('.eval-panel');
          if (el) {
            el.scrollIntoView({ behavior: "smooth", block: "center" });
            el.classList.add("eval-panel--flash");
            setTimeout(() => el.classList.remove("eval-panel--flash"), 1500);
          }
        } catch (e) {}
        break;
      case "demo":
        onSkip ? onSkip("Q1") : null;
        break;
    }
  };

  const toggleTheme = () => {
    const next = theme === "Dark" ? "light" : null;
    if (next) {
      document.documentElement.setAttribute("data-theme", "light");
      setTheme("Light");
    } else {
      document.documentElement.removeAttribute("data-theme");
      setTheme("Dark");
    }
    setSettingsOpen(false);
  };

  return (
    <header className="topbar">
      <div className="topbar__brand">
        <div className="topbar__logo" aria-hidden="true">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <circle cx="3" cy="3" r="1.6" fill="var(--agent-planner)" />
            <circle cx="11" cy="3" r="1.6" fill="var(--agent-web-researcher)" />
            <circle cx="7" cy="7" r="1.6" fill="var(--agent-research-manager)" />
            <circle cx="3" cy="11" r="1.6" fill="var(--agent-skeptic)" />
            <circle cx="11" cy="11" r="1.6" fill="var(--agent-optimist)" />
            <path d="M3 3 7 7M11 3 7 7M3 11 7 7M11 11 7 7" stroke="var(--fg-tertiary)" strokeWidth="0.7" />
          </svg>
        </div>
        <div className="topbar__name">Agentic UX <span>/ deep research</span></div>
      </div>

      <nav className="breadcrumb" aria-label="breadcrumb">
        <span>workspace</span><I.chevR />
        <span>hci</span><I.chevR />
        <b>agentic-ux</b>
      </nav>

      <div className="mode-chips" role="tablist" aria-label="Run mode">
        {modes.map((m) => (
          <button
            key={m}
            role="tab"
            aria-selected={mode === m}
            data-tooltip={MODE_TOOLTIPS[m]}
            className={"mode-chip " + (mode === m ? "mode-chip--on" : "")}
            onClick={() => handleModeChip(m)}
          >{m}</button>
        ))}
      </div>

      <div className="topbar__actions" style={{ position: "relative" }}>
        {onSkip && <a className="topbar__skip" href="#" onClick={(e) => { e.preventDefault(); onSkip("idle"); }}>← Back to start</a>}
        <button
          className="icon-btn"
          title="Settings"
          aria-label="Settings"
          aria-expanded={settingsOpen}
          onClick={() => setSettingsOpen(o => !o)}
        >
          <I.cog />
        </button>
        {settingsOpen && (
          <div
            className="settings-popover"
            role="menu"
            style={{
              position: "absolute",
              top: "calc(100% + 6px)",
              right: 0,
              background: "var(--bg-elevated)",
              border: "1px solid var(--border)",
              borderRadius: "var(--radius-m)",
              boxShadow: "0 8px 24px rgba(0,0,0,0.45)",
              zIndex: 9999,
              minWidth: 180,
              overflow: "hidden",
            }}
            onMouseLeave={() => setSettingsOpen(false)}
          >
            <button role="menuitem" onClick={toggleTheme} style={{ display: "block", width: "100%", textAlign: "left", padding: "9px 14px", background: "transparent", border: 0, color: "var(--fg-primary)", fontFamily: "inherit", fontSize: "12.5px", cursor: "pointer" }}>
              Theme: {theme}
            </button>
            <a
              role="menuitem"
              href="https://github.com/IS492-SP26/assignment-3-building-multi-agent-systems-fitz-s"
              target="_blank"
              rel="noopener"
              style={{ display: "block", padding: "9px 14px", color: "var(--fg-primary)", fontSize: "12.5px", textDecoration: "none" }}
              onClick={() => setSettingsOpen(false)}
            >
              Repo / Docs
            </a>
            <button role="menuitem" onClick={() => setSettingsOpen(false)} style={{ display: "block", width: "100%", textAlign: "left", padding: "9px 14px", background: "transparent", border: 0, color: "var(--fg-tertiary)", fontFamily: "inherit", fontSize: "12.5px", cursor: "pointer" }}>
              Close
            </button>
          </div>
        )}
      </div>
      <CliCommandModal open={cliModalOpen} onClose={() => setCliModalOpen(false)} />
    </header>
  );
}

/* ---------------- Sidebar — clickable history ---------------- */
function Sidebar({ onPick, history, activeStateId }) {
  const [searchTerm, setSearchTerm] = useState("");
  const filteredHistory = searchTerm
    ? history.filter(h => h.title.toLowerCase().includes(searchTerm.toLowerCase()))
    : history;

  const handleSearch = (e) => setSearchTerm(e.target.value);

  // Map history item id → whether it matches current active state
  const isActive = (hid) => {
    if (hid === "idle" || hid === "start") return activeStateId === "idle";
    return hid === activeStateId;
  };

  return (
    <aside className="sidebar">
      <div className="sidebar__section">
        <h3 className="sidebar__heading">Search</h3>
        <div className="search">
          <span className="search__icon"><I.search /></span>
          <input
            placeholder="Search queries…"
            value={searchTerm}
            onChange={handleSearch}
            onInput={handleSearch}
          />
        </div>
        <button className="new-query-btn" onClick={() => onPick("idle_dashboard")}>
          <I.plus /> New query
        </button>
      </div>

      <div className="sidebar__section" style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column", padding: "10px 6px 6px" }}>
        <h3 className="sidebar__heading" style={{ padding: "0 8px" }}>
          History <span className="count">{history.length}</span>
        </h3>
        <ul className="history-list" style={{ listStyle: "none", padding: "4px 2px 0", margin: 0, overflowY: "auto" }}>
          {filteredHistory.map((h) => {
            // Round-3 Fix 3: separator dividers are non-clickable labels.
            if (h.id === "__separator__" || h.status === "separator") {
              return (
                <li key={h.id} className="history-separator" aria-hidden="true">
                  {h.title}
                </li>
              );
            }
            return (
              <li key={h.id}
                className={"history-item history-item--" + h.status + (h.isReal ? " history-item--real" : "") + (isActive(h.id) ? " history-item--active" : "")}
                onClick={() => onPick(h.id)}
                tabIndex="0"
                role="button"
                aria-label={"Open " + h.title}
                onKeyDown={(e) => { if (e.key === "Enter") onPick(h.id); }}
              >
                <span className="history-item__dot" />
                <span className="history-item__title">{h.title}</span>
                <span className="history-item__meta">{h.subtitle || h.time}</span>
              </li>
            );
          })}
        </ul>
      </div>

      <div className="sidebar__group">
        <h3 className="sidebar__heading" style={{ margin: "0 0 6px" }}>Session</h3>
        <div className="sidebar__row"><span>Stages</span><b>{STAGE_COUNT}</b></div>
        <div className="sidebar__row"><span>Steps</span><b>{STEP_COUNT}</b></div>
        <div className="sidebar__row"><span>Agents</span><b>{AGENT_COUNT}</b></div>
        <div className="sidebar__row"><span>Backend</span><b>autogen</b></div>
      </div>
    </aside>
  );
}

/* ---------------- Stepper (P0-4: clickable + .step class) ---------------- */
const STEP_LABELS = {
  plan: "Plan", web: "Web", acad: "Academic", counter: "Counter",
  debate: "Debate", write: "Write", critic: "Critic",
};

const STEP_TO_AGENTS = {
  plan: ["planner"],
  web: ["web_researcher"],
  acad: ["academic_researcher"],
  counter: ["counter_evidence"],
  debate: ["optimist", "skeptic", "research_manager"],
  write: ["writer"],
  critic: ["editor"],
};

function jumpToFirstAgent(stepKey) {
  const targets = STEP_TO_AGENTS[stepKey] || [];
  for (const a of targets) {
    const el = document.querySelector('[data-msg-agent="' + a + '"]') ||
               document.querySelector('[data-stage="' + stepKey + '"]');
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
  }
}

function Stepper({ pipeline, state }) {
  return (
    <div className="stepper" role="list" aria-label="Pipeline progress">
      {pipeline.map((s, i) => {
        const st = state[s] || "pending";
        return (
          <React.Fragment key={s}>
            <div
              className={"stepper__node stepper__step stepper__node--" + st + " stepper__step--" + st}
              role="listitem"
              tabIndex="0"
              data-step={s}
              aria-label={STEP_LABELS[s] + " " + st + " — click to jump"}
              onClick={() => jumpToFirstAgent(s)}
              onKeyDown={(e) => { if (e.key === "Enter") jumpToFirstAgent(s); }}
              style={{ cursor: "pointer" }}
            >
              <div className="stepper__circle">
                {st === "done" && <I.check />}
              </div>
              <span className="stepper__label">{STEP_LABELS[s]}</span>
            </div>
            {i < pipeline.length - 1 && (
              <span className={"stepper__connector " + ((state[s] === "done") ? "stepper__connector--done" : "")} aria-hidden="true" />
            )}
          </React.Fragment>
        );
      })}
    </div>
  );
}

/* ---------------- Message Card ---------------- */
function MsgCard({ m, railSources }) {
  const [expanded, setExpanded] = useState(false);
  const isLong = (m.body || "").length > 360;
  const isUser = m.agent === "user";

  const showSanitized = m.sanitized || m.has_safety_event;

  const stageMap = {
    planner: "plan", web_researcher: "web", academic_researcher: "acad",
    counter_evidence: "counter", optimist: "debate", skeptic: "debate",
    research_manager: "debate", writer: "write", editor: "critic",
  };

  return (
    <article
      data-msg-agent={m.agent}
      data-stage={stageMap[m.agent] || ""}
      className={"msg-card " + (isUser ? "msg-card--user" : "")}
      aria-label={"Message from " + (m.agent_name || m.agent)}
    >
      <div className="msg-avatar" style={{ background: m.agent_color }} aria-hidden="true">
        {m.initials}
      </div>
      <div>
        <div className="msg-head">
          <span className="agent-chip" data-role={m.role_blurb || ""}>
            <span className="agent-chip__bar" style={{ background: m.agent_color }} />
            {m.agent_name || m.agent}
          </span>
          {m.role && <span className="msg-role">{m.role}</span>}
          {m.stage && <span className="msg-stage">· {m.stage}</span>}
          {showSanitized && (
            <span className="sanitized sanitized-mark" title="Provenance verifier trimmed an unsourced sentence">
              <I.warn /> Sanitized
            </span>
          )}
          <span className="msg-time">{m.time}</span>
          {m.duration && <span className="msg-dur">{m.duration}</span>}
        </div>
        <div className={"msg-body " + (isLong && !expanded ? "msg-body--collapsed" : "")}>
          {renderBody(m.body, railSources)}
        </div>
        {isLong && (
          <button className="msg-expand" onClick={() => setExpanded(!expanded)}>
            {expanded ? "▴ Collapse" : "▾ Expand " + m.body.length + " chars"}
          </button>
        )}
      </div>
    </article>
  );
}

/* ---------------- Session Starting Animation ----------------
 * Round-3 Fix 4: Closes the dead-air gap between user clicking "Run research"
 * and the Planner emitting its first message (~30s of silence). First-time
 * users would otherwise see an empty dashboard and assume the system crashed.
 */
function StartingState() {
  const agents = [
    "planner", "web-researcher", "academic-researcher", "counter-evidence",
    "optimist", "skeptic", "research-manager", "writer", "editor"
  ];
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setTick(x => x + 1), 600);
    return () => clearInterval(t);
  }, []);

  return (
    <section className="starting-state" aria-busy="true" aria-live="polite">
      <div className="starting-state__head">
        <div className="starting-state__title">Spinning up the 9-agent pipeline</div>
        <div className="starting-state__sub">
          Planner is decomposing your query into sub-questions…
        </div>
      </div>
      <div className="starting-state__dots">
        {agents.map((a, i) => (
          <div
            key={a}
            className={"starting-dot " + (i === (tick % 9) ? "starting-dot--on" : "")}
            style={{ background: "var(--agent-" + a + ")" }}
          />
        ))}
      </div>
      <div className="starting-state__steps">
        <span className={tick > 0 ? "step done" : "step"}>● Initializing model client</span>
        <span className={tick > 1 ? "step done" : "step"}>● Loading 9 agents</span>
        <span className={tick > 2 ? "step done" : "step"}>● Wiring guardrails</span>
        <span className={tick > 3 ? "step done" : "step"}>○ Awaiting Planner response (~30s)</span>
      </div>
    </section>
  );
}

/* ---------------- Loading message (skeleton) ---------------- */
function LoadingMsg({ agent, status }) {
  const colors = {
    planner: "var(--agent-planner)",
    web_researcher: "var(--agent-web-researcher)",
    academic_researcher: "var(--agent-academic-researcher)",
    counter_evidence: "var(--agent-counter-evidence)",
    optimist: "var(--agent-optimist)",
    skeptic: "var(--agent-skeptic)",
    research_manager: "var(--agent-research-manager)",
    writer: "var(--agent-writer)",
    editor: "var(--agent-editor)",
  };
  const initials = {
    planner: "PL", web_researcher: "WR", academic_researcher: "AR",
    counter_evidence: "CE", optimist: "OP", skeptic: "SK",
    research_manager: "RM", writer: "WT", editor: "ED",
  };
  return (
    <article className="msg-card" aria-busy="true">
      <div className="msg-avatar" style={{ background: colors[agent] || "var(--fg-secondary)" }}>
        {initials[agent] || "?"}
      </div>
      <div>
        <div className="msg-head">
          <span className="agent-chip">
            <span className="agent-chip__bar" style={{ background: colors[agent] || "var(--fg-secondary)" }} />
            {agent}
          </span>
          <span className="msg-role">working</span>
        </div>
        <div className="msg-loading">
          <span>{status || "thinking"}</span>
          <span className="msg-loading__dots"><span /><span /><span /></span>
        </div>
      </div>
    </article>
  );
}

/* ---------------- Debate Card ---------------- */
function DebateCard({ active, optimistMsg, skepticMsg, verdictMsg, railSources }) {
  const tokenize = makeTokenizer(railSources);
  return (
    <section className="debate" aria-label="Debate round" data-msg-agent="optimist" data-stage="debate">
      <div className="debate__head">
        <div className="debate__icon"><I.scales /></div>
        <div className="debate__title">Debate <span className="round">round 1</span></div>
        <span className="msg-time">{(optimistMsg && optimistMsg.time) || ""}</span>
      </div>
      <div className="debate__legend">
        <span className="debate__legend-swatch" style={{ color: "var(--agent-optimist)" }}>Optimist · pro-stance</span>
        <span className="debate__legend-swatch" style={{ color: "var(--agent-skeptic)" }}>Skeptic · con-stance</span>
        <span className="debate__legend-swatch" style={{ color: "var(--agent-research-manager)" }}>Research Manager · adjudicates</span>
      </div>
      <div className="debate__body">
        <div className="debate__side debate__side--optimist">
          <div className="msg-head">
            <span className="agent-chip"><span className="agent-chip__bar" style={{ background: "var(--agent-optimist)" }} />Optimist</span>
            {optimistMsg && optimistMsg.duration && <span className="msg-dur">{optimistMsg.duration}</span>}
          </div>
          <div className="msg-body">
            <div className="debate__quote">
              {tokenize((optimistMsg && optimistMsg.body) || "Argues the strongest case for emerging consensus.")}
            </div>
          </div>
        </div>
        <div className="debate__side debate__side--skeptic">
          <div className="msg-head">
            <span className="agent-chip"><span className="agent-chip__bar" style={{ background: "var(--agent-skeptic)" }} />Skeptic</span>
            {skepticMsg && skepticMsg.duration && <span className="msg-dur">{skepticMsg.duration}</span>}
          </div>
          <div className="msg-body">
            <div className="debate__quote">
              {tokenize((skepticMsg && skepticMsg.body) || "Stress-tests the optimist's case and flags weak evidence.")}
            </div>
          </div>
        </div>
      </div>
      <div className="debate__verdict">
        <div className="debate__verdict-icon">RM</div>
        <div>
          <div className="debate__verdict-label">Research Manager · verdict</div>
          <div className="debate__verdict-text">
            {active
              ? <>Adjudicating the optimist–skeptic round…</>
              : tokenize((verdictMsg && verdictMsg.body) || "Both stances accepted as partial. Synthesis splits established consensus from contested terrain.")}
          </div>
        </div>
        <span className="debate__verdict-tag">{active ? "deliberating" : "synthesis → writer"}</span>
      </div>
    </section>
  );
}

/* ---------------- Right rail panels ---------------- */
function ActiveAgent({ session }) {
  const a = session && session.activeAgent;
  const status = session ? session.status : "idle";
  if (!a) {
    return (
      <div className="active-agent active-agent--idle" aria-label="Active agent: none">
        <span className="active-agent__dot" />
        <span className="active-agent__name">No agent active</span>
        <span className="active-agent__status">{status === "complete" ? "complete" : status === "refused" ? "refused" : "idle"}</span>
      </div>
    );
  }
  return (
    <div className="active-agent" aria-label={"Active agent: " + a.name}>
      <span className="active-agent__dot" style={{ background: a.color }} />
      <span className="active-agent__name" style={{ color: a.color }}>{a.name}</span>
      <span className="active-agent__status">{a.status}</span>
    </div>
  );
}

function SafetyPanel({ events }) {
  return (
    <section className="rail__panel" aria-labelledby="safety-h">
      <div className="rail__panel-head">
        <span id="safety-h">Safety</span>
        <span className="count">{events.length} event{events.length === 1 ? "" : "s"}</span>
      </div>
      <div className="rail__panel-body">
        {events.length === 0 && (
          <div style={{ padding: "8px 12px", color: "var(--fg-tertiary)", fontSize: "12px", fontStyle: "italic" }}>
            No safety events yet.
          </div>
        )}
        {events.map((e, i) => {
          const cls = e.sev === "block" ? "safety--block" : e.sev === "warn" ? "safety--warn" : "safety--pass";
          const icon = e.sev === "block" ? "✗" : e.sev === "warn" ? "⚠" : "✓";
          return (
            <div key={i} className={"safety " + cls}>
              <div className="safety__chip">{icon}</div>
              <div>
                <div className="safety__title">{e.msg}</div>
                <div className="safety__sub">{e.cat} · action: {e.action}</div>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function SourcesPanel({ ids, railSources }) {
  // Sources start COLLAPSED — user clicks to expand a specific entry.
  // Auto-opening the first source used to inflate the rail to ~300px+ on long
  // key_claim previews, making the panel feel broken at the top of the rail.
  const [open, setOpen] = useState(null);
  const [panelCollapsed, setPanelCollapsed] = useState(false);

  useEffect(() => {
    setOpen(null);
  }, [ids && ids[0]]);

  useEffect(() => {
    function onOpen(ev) {
      const id = ev.target && ev.target.id ? ev.target.id.replace("source-", "") : null;
      if (id) setOpen(id);
    }
    document.addEventListener("__open_source__", onOpen);
    return () => document.removeEventListener("__open_source__", onOpen);
  }, []);

  return (
    <section className={"rail__panel" + (panelCollapsed ? " rail__panel--collapsed" : "")} aria-labelledby="src-h">
      <button
        type="button"
        className="rail__panel-head rail__panel-head--clickable"
        aria-expanded={!panelCollapsed}
        onClick={() => setPanelCollapsed((c) => !c)}
      >
        <span id="src-h">Sources</span>
        <span className="count">({ids.length})</span>
        <span className="rail__panel-chevron" aria-hidden="true">{panelCollapsed ? "▸" : "▾"}</span>
      </button>
      {!panelCollapsed && (
      <div className="rail__panel-body">
        {ids.length === 0 && (
          <div style={{ padding: "8px 12px", color: "var(--fg-tertiary)", fontSize: "12px", fontStyle: "italic" }}>
            No sources retrieved.
          </div>
        )}
        {ids.map((id) => {
          const s = (railSources || {})[id] || { title: "Source " + id, type: "web", url: "", preview: "" };
          const isOpen = open === id;
          return (
            <div key={id} id={"source-" + id}
                 className={"source" + (isOpen ? " source--open" : "")}
                 onClick={() => setOpen(isOpen ? null : id)}
                 tabIndex="0"
                 role="button"
                 aria-expanded={isOpen}
                 onKeyDown={(e) => { if (e.key === "Enter") setOpen(isOpen ? null : id); }}>
              <div className="source__head">
                <span className="source__id">[{id}]</span>
                <span className="source__title">{s.title}</span>
              </div>
              <div className="source__meta">
                <span className={"source__type source__type--" + s.type}>{s.type}</span>
                {s.year && <span>{s.year}</span>}
                {s.authors && s.authors.length > 0 && (
                  <span className="source__authors">{
                    (() => {
                      const list = Array.isArray(s.authors) ? s.authors : [s.authors];
                      if (list.length <= 2) return list.join(", ");
                      return `${list[0]}, ${list[1]} +${list.length - 2}`;
                    })()
                  }</span>
                )}
                {s.authority && <span className="source__authority">· {s.authority}</span>}
              </div>
              {isOpen && (
                <details open className="source__details">
                  <summary style={{ display: "none" }}>Source preview</summary>
                  {s.preview}
                  {s.url && (
                    <div style={{ marginTop: 6 }}>
                      <a href={s.url} target="_blank" rel="noopener" onClick={(e) => e.stopPropagation()}><I.link /> {s.url}</a>
                    </div>
                  )}
                </details>
              )}
            </div>
          );
        })}
      </div>
      )}
    </section>
  );
}

/* P0-6: Export menu — proper dropdown with 3 options + actual download */
function ExportMenu({ disabled, session }) {
  const [open, setOpen] = useState(false);

  const downloadJSON = () => {
    const blob = new Blob([JSON.stringify(session, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = (session.id || "session") + ".json";
    a.click();
    URL.revokeObjectURL(url);
    setOpen(false);
  };
  const downloadMarkdown = () => {
    const railSources = session.railSources || {};
    const md = (session.response || "") + "\n\n---\n\n## Sources\n" +
      (session.sources || []).map(id => {
        const s = railSources[id] || {};
        return "- [" + id + "] " + (s.title || "") + " — " + (s.url || "");
      }).join("\n");
    const blob = new Blob([md], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = (session.id || "session") + ".md";
    a.click();
    URL.revokeObjectURL(url);
    setOpen(false);
  };
  const downloadHTML = () => {
    const html = "<!doctype html><html><head><meta charset='utf-8'/><title>" +
      (session.id || "session") + "</title></head><body>" +
      "<h1>" + (session.query || "") + "</h1>" +
      "<pre style='white-space:pre-wrap;font-family:Georgia,serif'>" +
      (session.response || "").replace(/</g, "&lt;") + "</pre></body></html>";
    const blob = new Blob([html], { type: "text/html" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = (session.id || "session") + ".html";
    a.click();
    URL.revokeObjectURL(url);
    setOpen(false);
  };

  return (
    <section className="rail__panel">
      <div className="rail__panel-head"><span>Export</span></div>
      <div className="rail__panel-body">
        <div className={"export" + (open ? " export--open" : "")} data-export={open ? "open" : "closed"}>
          <button
            className="export__btn export-button"
            onClick={() => setOpen(!open)}
            disabled={disabled}
            aria-haspopup="menu"
            aria-expanded={open}
            data-export-toggle
          >
            <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}><I.download /> Export session</span>
            <I.chevD />
          </button>
          {open && (
            <div className="export__menu export-menu" role="menu">
              <button className="export__opt" role="menuitem" onClick={downloadJSON}>
                JSON · trace+sources <span className="export__opt-ext">.json</span>
              </button>
              <button className="export__opt" role="menuitem" onClick={downloadMarkdown}>
                Markdown · final report <span className="export__opt-ext">.md</span>
              </button>
              <button className="export__opt" role="menuitem" onClick={downloadHTML}>
                HTML · self-contained <span className="export__opt-ext">.html</span>
              </button>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

/* P0-5: Refused banner — Edit query CTA actually navigates */
function RefusedBanner({ refusal, session }) {
  const onEdit = () => {
    goToParent({ edit: (session && session.query) || "", preload: null, phase: null });
  };
  return (
    <div className="refused-banner" role="alert">
      <div className="refused-banner__icon"><I.shieldX /></div>
      <div>
        <h2 className="refused-banner__title">{refusal.title} <span className="cat">{refusal.category}</span></h2>
        <p className="refused-banner__body">{refusal.body}</p>
        <div className="refused-banner__pattern" title="Trigger pattern">
          pattern: /{refusal.pattern}/ &nbsp;→ matched <span style={{ color: "var(--accent-red)" }}>"{refusal.match}"</span>
        </div>
      </div>
      <button
        className="refused-banner__cta edit-query-btn"
        onClick={onEdit}
        data-edit-query
      >Edit query →</button>
    </div>
  );
}

/* ---------------- Empty state — full hero rebuild (P0-3) ---------------- */
function EmptyState({ editPrefill }) {
  const [q, setQ] = useState(editPrefill || "");
  const tips = [
    { id: "Q1", text: "What is the empirical evidence — across 2024–2026 HCI and ML literature — for and against autonomous AI agents replacing structured UI affordances in productivity software? Synthesize positions and identify where claims diverge.", tag: "Q1 · 4m 12s · complete" },
    { id: "Q5", text: "Compare the measurable effectiveness of multi-agent coordination patterns (structured debate, vote, hierarchical RM, swarm) at reducing factual hallucination in retrieval-augmented systems. Where does each pattern fail?", tag: "Q5 · contested" },
    { id: "Q6", text: "Are LLM agents replacing UIs or augmenting them?", tag: "Q6 · refused (injection)" },
  ];

  const submit = () => {
    const text = q.trim();
    if (!text) return;
    goToParent({ run: text, preload: null, edit: null });
  };
  const onKey = (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") submit();
  };

  return (
    <div className="empty empty--hero">
      <div className="empty__hero-inner">
        <div className="empty__eyebrow">
          <span className="pill">guardrails on</span>
        </div>
        <h1 className="empty__title">
          Ask one question.<br />
          Watch <em>nine agents</em> argue it out.
        </h1>
        <p className="empty__lede">
          A research run sends your query through a planner, two evidence gatherers,
          a counter-evidence pass, an optimist/skeptic debate, and a writer/critic loop —
          with every citation, safety check, and dropped claim shown to you in real time.
        </p>

        <div className="empty__form">
          <div className="empty__form-label">
            <span>YOUR RESEARCH QUESTION</span>
            <span className="empty__form-meta">3–5 minutes · ~$0.04 per run</span>
          </div>
          <textarea
            className="empty__textarea"
            placeholder="e.g. What is the empirical evidence for and against autonomous AI agents replacing UI affordances in 2026?"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={onKey}
            rows={3}
            autoFocus
          />
          <div className="empty__form-row">
            <button className="empty__cta empty__run" onClick={submit} disabled={!q.trim()}>
              Run research →
            </button>
            <span className="empty__cta-meta">⌘ ⏎ to run</span>
          </div>
        </div>

        <div className="empty__pipeline-preview">
          <div className="empty__step"><span className="empty__step-num">01</span><b>Plan</b><span>The planner decomposes your question into 3–5 sub-questions.</span><span className="empty__step-time">~20s</span></div>
          <div className="empty__step"><span className="empty__step-num">02</span><b>Gather evidence</b><span>Web (Tavily), Academic (Semantic Scholar), and Counter-Evidence agents pull sources in parallel.</span><span className="empty__step-time">~60s</span></div>
          <div className="empty__step"><span className="empty__step-num">03</span><b>Debate</b><span>Optimist &amp; Skeptic argue the contested claims; Research Manager adjudicates each round.</span><span className="empty__step-time">~70s</span></div>
          <div className="empty__step"><span className="empty__step-num">04</span><b>Write &amp; critique</b><span>Writer drafts a synthesis; Editor critiques. Provenance verifier strips unsourced claims.</span><span className="empty__step-time">~60s</span></div>
        </div>

        <div className="empty__cards">
          <div className="empty__card">
            <div className="empty__card-title">Or pick a tested example</div>
            <div className="empty__sug-list">
              {tips.map((t, i) => (
                <button key={i} className="empty__sug" onClick={() => goToParent({ preload: t.id, edit: null })}>
                  <span className="empty__sug-text">{t.text}</span>
                  <span className="empty__sug-tag">{t.tag}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function CockpitPanel() {
  return (
    <section className="rail__panel rail__panel--cockpit">
      <div className="rail__panel-head">READING THE COCKPIT</div>
      <div className="rail__panel-body cockpit-legend">
        <div className="cockpit-row"><span className="cockpit-label">STAGE</span><span>4 stages — plan, gather, debate, write. The big picture.</span></div>
        <div className="cockpit-row"><span className="cockpit-label">STEP</span><span>7 stepper nodes — a finer view of who runs when.</span></div>
        <div className="cockpit-row"><span className="cockpit-label">AGENT</span><span>9 agents — actors with brand colors. Multiple agents per stage.</span></div>
        <div className="cockpit-row"><span className="cockpit-label">[Sn]</span><span>Citation chip — hover for source preview, list lives in the right rail.</span></div>
        <div className="cockpit-row"><span className="cockpit-label">SANITIZED</span><span>Sentence stripped by the provenance verifier (had no citation).</span></div>
      </div>
    </section>
  );
}

/* ---------------- Status bar ---------------- */
function StatusBar({ session, mode }) {
  const m = (session && session.meta) || {};
  return (
    <footer className="statusbar" role="status">
      <span className="statusbar__group">
        <span className="statusbar__pulse" aria-hidden="true" />
        <b>autogen</b><span>v0.4 · gpt-4o-mini</span>
      </span>
      <span className="statusbar__bar" />
      <span className="statusbar__group">
        <span>session</span><b>{(session && session.id) || "—"}</b>
        <span>·</span>
        <span>mode</span><b>{mode}</b>
      </span>
      <span className="statusbar__bar" />
      <span className="statusbar__group">
        <span>messages</span><b>{m.num_messages || 0}</b>
        <span>·</span>
        <span>sources</span><b>{m.num_sources || 0}</b>
        <span>·</span>
        <span>debate</span><b>{m.debate_rounds || 0}</b>
        <span>·</span>
        <span>elapsed</span><b>{(m.total_duration_seconds || 0).toFixed(1)}s</b>
      </span>
      <span style={{ marginLeft: "auto", display: "inline-flex", gap: 14, alignItems: "center" }}>
        <span className="statusbar__cost">{(session && session.cost) || ""}</span>
        <span className="statusbar__bar" />
        <span><I.shield style={{ verticalAlign: "-2px", marginRight: 4 }} /> guardrails ON</span>
        <span>tavily</span>
        <span>semantic-scholar</span>
      </span>
    </footer>
  );
}

/* ---------------- Evaluation Panel ---------------- */
function ScoreDots({ score }) {
  const filled = Math.round(Math.max(1, Math.min(5, score)));
  const color = filled <= 2
    ? "var(--accent-red)"
    : filled === 3
      ? "var(--accent-yellow)"
      : "var(--accent-green)";
  const dots = Array.from({ length: 5 }, (_, i) => (
    <span key={i} style={{ color: i < filled ? color : "var(--fg-tertiary)", opacity: i < filled ? 1 : 0.3 }}>●</span>
  ));
  return <span className="eval-criterion__dots">{dots}</span>;
}

function EvalJudge({ label, icon, scores, rationale }) {
  const [expanded, setExpanded] = useState(false);
  const total = Object.values(scores).reduce((a, b) => a + b, 0) / Math.max(1, Object.keys(scores).length);
  return (
    <div className="eval-judge">
      <div className="eval-judge__head">{icon} {label}</div>
      {Object.entries(scores).map(([crit, val]) => (
        <div key={crit} className="eval-criterion">
          <span className="eval-criterion__label">{crit.replace(/_/g, " ")}</span>
          <ScoreDots score={val} />
          <span className="eval-criterion__score">{val}/5</span>
        </div>
      ))}
      <div className="eval-judge__total">
        <span>total</span>
        <span>{total.toFixed(1)}/5</span>
      </div>
      {rationale && (
        <div
          className={"eval-rationale" + (expanded ? " is-expanded" : "")}
          onClick={() => setExpanded(!expanded)}
          title={expanded ? "Collapse" : "Expand rationale"}
        >
          ▸ "{rationale}"
        </div>
      )}
    </div>
  );
}

function EvalPanel({ session, collapsed: collapsedInit }) {
  const [collapsed, setCollapsed] = useState(!!collapsedInit);
  const scores = session && session.evalScores;
  const canScore = session && session.status === "complete" && session.response;
  const triggerScore = () => goToParent({ score: "1" });
  const headHandler = () => setCollapsed(!collapsed);
  const clearResult = () => {
    try { window.parent.postMessage({ type: "omc_clear_result" }, "*"); } catch(e) {}
    try { window.top.location.href = "?clear=1"; } catch(e) {}
  };

  if (!scores) {
    return (
      <section className={"rail__panel" + (collapsed ? " rail__panel--collapsed" : "")} aria-labelledby="eval-h">
        <div className="rail__panel-head" onClick={headHandler} style={{ cursor: "pointer" }}>
          <span id="eval-h">Evaluation</span>
          <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
            {session && (
              <button
                onClick={(e) => { e.stopPropagation(); clearResult(); }}
                title="Clear result"
                style={{
                  background: "transparent", border: "1px solid var(--border)",
                  borderRadius: "4px", color: "var(--fg-tertiary)", padding: "1px 7px",
                  fontSize: "10px", cursor: "pointer", fontFamily: "var(--font-ui)",
                }}
              >× Clear</button>
            )}
            <span style={{ fontSize: "11px" }}>{collapsed ? "▸" : "▾"}</span>
          </span>
        </div>
        {!collapsed && (
          <div className="rail__panel-body">
            <div className="eval-empty">
              No evaluation yet
              {canScore && (
                <div style={{ marginTop: "10px" }}>
                  <button
                    onClick={triggerScore}
                    style={{
                      background: "#2f81f7", color: "#fff", border: 0,
                      borderRadius: "6px", padding: "6px 14px",
                      fontFamily: "var(--font-ui)", fontSize: "12px",
                      fontWeight: 500, cursor: "pointer"
                    }}
                  >
                    Score with judges (~30s)
                  </button>
                </div>
              )}
              {!canScore && <div className="eval-empty__hint">Run a query first</div>}
            </div>
          </div>
        )}
      </section>
    );
  }
  const strict = scores.strict_rubric || {};
  const hci = scores.hci_grad_student || {};
  const judgeCount = [strict, hci].filter(j => j.scores).length;
  return (
    <section className={"rail__panel" + (collapsed ? " rail__panel--collapsed" : "")} aria-labelledby="eval-h">
      <div className="rail__panel-head" onClick={headHandler} style={{ cursor: "pointer" }}>
        <span id="eval-h">Evaluation</span>
        <span className="count">{judgeCount} judge{judgeCount !== 1 ? "s" : ""} {collapsed ? "▸" : "▾"}</span>
      </div>
      {!collapsed && (
        <div className="rail__panel-body">
          {strict.scores && (
            <EvalJudge
              label="Strict Rubric"
              icon="⚖"
              scores={strict.scores}
              rationale={strict.rationale || ""}
            />
          )}
          {hci.scores && (
            <EvalJudge
              label="HCI Grad Student"
              icon="🎓"
              scores={hci.scores}
              rationale={hci.rationale || ""}
            />
          )}
        </div>
      )}
    </section>
  );
}

/* ---------------- No-data placeholder — shown when a STATE pill has no real run yet ---------------- */
const STATE_NAMES = {
  loading: "Loading",
  debate: "Debate Active",
  Q6: "Refused",
  live: "Complete",
};

function NoDataState({ stateId, onGoStart }) {
  const label = STATE_NAMES[stateId] || stateId;
  return (
    <div style={{
      display: "flex", flexDirection: "column", alignItems: "center",
      justifyContent: "center", height: "360px", gap: "14px",
      color: "var(--fg-tertiary)", fontFamily: "var(--font-ui)",
    }}>
      <span style={{ fontSize: "36px", opacity: 0.18 }}>◌</span>
      <p style={{ margin: 0, fontSize: "14px", textAlign: "center", maxWidth: 340 }}>
        No data for <b style={{ color: "var(--fg-secondary)" }}>{label}</b> yet.
      </p>
      <p style={{ margin: 0, fontSize: "12px", textAlign: "center", maxWidth: 340, lineHeight: 1.5 }}>
        This state populates only when you run a real query that reaches this stage.
      </p>
      <button
        onClick={() => onGoStart("idle")}
        style={{
          marginTop: 4, background: "var(--bg-elevated)", border: "1px solid var(--border)",
          borderRadius: "var(--radius-m)", color: "var(--fg-primary)", padding: "7px 16px",
          fontFamily: "var(--font-ui)", fontSize: "12.5px", cursor: "pointer",
        }}
      >
        ← Run research on Start
      </button>
    </div>
  );
}

/* StatePill removed 2026-05-07: it duplicated the dashboard's own status
 * indicators ('● running' / '● complete' / '● refused' / Stepper) and added
 * noise once the live runtime took over. Mount points were also removed
 * from EntryPage, idle_dashboard layout, and the main App return. The CSS
 * '.state-pill' rules in styles.css are now unused but harmless. */

/* ---------------- Entry Page (idle/Start state) — standalone 2-col layout ---------------- */
function EntryPage({ onStateChange }) {
  const [query, setQuery] = useState("");
  const [running, setRunning] = useState(false);

  const EXAMPLES = [
    { text: "What is the empirical evidence — across 2024–2026 HCI and ML literature — for and against autonomous AI agents replacing structured UI affordances in productivity software? Synthesize positions and identify where claims diverge.", tag: "~5 min · complete pipeline" },
    { text: "Compare the measurable effectiveness of multi-agent coordination patterns (structured debate, vote, hierarchical RM, swarm) at reducing factual hallucination in retrieval-augmented systems. Where does each pattern fail?", tag: "~5 min · debate-heavy" },
    { text: "What human-in-the-loop oversight patterns from 2024–2026 deployed agent systems have rigorous empirical support, and which are speculative? Cross-reference enterprise incident reports against academic claims.", tag: "~5 min · evidence-heavy" },
  ];

  // Trigger a real backend run.
  // srcdoc iframes cannot write window.top.location.href (sandbox blocks it).
  // Strategy: post {type:'omc_run', query} to window.parent — the top Streamlit
  // frame has a listener injected via st.markdown that catches this message and
  // performs window.location.href = '?run=<query>' in the top frame.
  const handleRun = () => {
    const q = query.trim();
    if (!q || running) return;
    setRunning(true);
    const target = "?run=" + encodeURIComponent(q);
    // Try top-frame URL navigation in priority order. srcdoc iframes inherit
    // parent origin so window.top.location.href write is usually allowed.
    let navigated = false;
    try { window.top.location.href = target; navigated = true; } catch (e) {}
    if (!navigated) {
      try { window.parent.location.href = target; navigated = true; } catch (e) {}
    }
    // Fallback: postMessage to top-frame listener (nav_relay declared component).
    try { window.parent.postMessage({ type: "omc_run", query: q }, "*"); } catch (e) {}
    if (!navigated) {
      // Last resort: navigate self iframe (less ideal, may still work).
      setTimeout(() => { try { window.location.href = target; } catch (e) {} }, 200);
    }
  };

  // Cmd+Enter / Ctrl+Enter shortcut
  useEffect(() => {
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") handleRun();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [query, running]);

  return (
    <div className="entry-page">
      {/* Simplified topbar — logo + skip only */}
      <header className="entry-topbar">
        <div className="topbar__brand">
          <div className="topbar__logo" aria-hidden="true">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <circle cx="3"  cy="3"  r="1.6" fill="var(--agent-planner)" />
              <circle cx="11" cy="3"  r="1.6" fill="var(--agent-web-researcher)" />
              <circle cx="7"  cy="7"  r="1.6" fill="var(--agent-research-manager)" />
              <circle cx="3"  cy="11" r="1.6" fill="var(--agent-skeptic)" />
              <circle cx="11" cy="11" r="1.6" fill="var(--agent-optimist)" />
              <path d="M3 3 7 7M11 3 7 7M3 11 7 7M11 11 7 7" stroke="var(--fg-tertiary)" strokeWidth="0.7" />
            </svg>
          </div>
          <div className="topbar__name">Agentic UX <span>/ deep research</span></div>
        </div>
        <div className="entry-topbar__actions">
          <button
            className="entry-theme-toggle"
            title="Toggle theme"
            aria-label="Toggle theme"
            onClick={() => {
              const isLight = document.documentElement.getAttribute("data-theme") === "light";
              if (isLight) document.documentElement.removeAttribute("data-theme");
              else document.documentElement.setAttribute("data-theme", "light");
            }}
          >
            <span className="entry-theme-toggle__icon" aria-hidden="true">◐</span>
            <span className="entry-theme-toggle__label">theme</span>
          </button>
          <a className="topbar__skip" href="#" onClick={(e) => { e.preventDefault(); onStateChange("idle_dashboard"); }}>
            Skip to dashboard →
          </a>
        </div>
      </header>

      {/* 2-column main */}
      <main className="entry-main">
        {/* Left: hero + subtitle + pipeline steps */}
        <div className="entry-left">
          <div className="entry-eyebrow">
            <span>v0.4 · autogen · gpt-4o-mini</span>
            <span className="pill pill--green">guardrails on</span>
          </div>
          <h1 className="entry-hero">
            Ask one question.<br/>
            Watch <em>nine agents</em> argue it out.
          </h1>
          <p className="entry-subtitle">
            A research run sends your query through a planner, two evidence gatherers, a counter-evidence
            pass, an optimist/skeptic debate, and a writer/critic loop — with every citation, safety
            check, and dropped claim shown to you in real time.
          </p>
          <div className="entry-pipeline">
            {[
              { num: "01", title: "Plan",            desc: "The planner decomposes your question into 3–5 sub-questions.", time: "~20s" },
              { num: "02", title: "Gather evidence", desc: "Web (Tavily), Academic (Semantic Scholar), and Counter-Evidence agents pull sources in parallel.", time: "~60s" },
              { num: "03", title: "Debate",          desc: "Optimist & Skeptic argue the contested claims; Research Manager adjudicates each round.", time: "~70s" },
              { num: "04", title: "Write & critique",desc: "Writer drafts a synthesis; Editor critiques. Provenance verifier strips unsourced claims.", time: "~60s" },
            ].map((s) => (
              <div key={s.num} className="entry-step">
                <span className="step-num">{s.num}</span>
                <div className="step-body">
                  <b>{s.title}</b>
                  <p>{s.desc}</p>
                </div>
                <span className="step-time">{s.time}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Right: form card + cockpit legend */}
        <div className="entry-right">
          <div className="entry-form-card">
            <div className="entry-form-head">
              <span>YOUR RESEARCH QUESTION</span>
              <span className="entry-form-meta">3-5 minutes · ~$0.04 per run</span>
            </div>
            <textarea
              className="entry-textarea"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              disabled={running}
              placeholder="e.g. What is the empirical evidence for and against autonomous AI agents replacing UI affordances in 2026?"
            />
            <div className="entry-form-footer">
              <button
                className={"entry-run-btn" + (running ? " entry-run-btn--running" : "")}
                disabled={!query.trim() || running}
                onClick={handleRun}
              >
                {running ? "Running…" : "Run research →"}
              </button>
              <span className="entry-kbd">⌘ ↵ to run</span>
            </div>

            <div className="entry-examples">
              <div className="entry-examples-label">OR START WITH AN EXAMPLE QUERY</div>
              {EXAMPLES.map((ex) => (
                <button key={ex.tag} className="entry-example" onClick={() => {
                  setQuery(ex.text);
                  // Trigger run after state update settles
                  setTimeout(() => {
                    const q = ex.text.trim();
                    if (!q) return;
                    let navigated = false;
                    try { window.top.location.href = "?run=" + encodeURIComponent(q); navigated = true; } catch(e) {}
                    if (!navigated) { try { window.parent.location.href = "?run=" + encodeURIComponent(q); navigated = true; } catch(e) {} }
                    try { window.parent.postMessage({ type: "omc_run", query: q }, "*"); } catch(e) {}
                  }, 50);
                }}>
                  <span>{ex.text}</span>
                  <span className="entry-example-tag">{ex.tag}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="entry-cockpit">
            <div className="entry-cockpit-head">
              <span>✦</span>
              <span>READING THE COCKPIT</span>
            </div>
            <div className="entry-cockpit-body">
              <div className="cockpit-row"><span className="cockpit-label">STAGE</span><span>4 stages — plan, gather, debate, write. The big picture.</span></div>
              <div className="cockpit-row"><span className="cockpit-label">STEP</span><span>7 stepper nodes — a finer view of who runs when.</span></div>
              <div className="cockpit-row"><span className="cockpit-label">AGENT</span><span>9 agents — actors with brand colors. Multiple agents per stage.</span></div>
              <div className="cockpit-row"><span className="cockpit-label">[Sn]</span><span>Citation chip — hover for source preview, list lives in the right rail.</span></div>
              <div className="cockpit-row"><span className="cockpit-label">SANITIZED</span><span>Sentence stripped by the provenance verifier (had no citation).</span></div>
            </div>
          </div>
        </div>
      </main>

      {/* Simplified statusbar */}
      <footer className="entry-statusbar">
        <span>backend <b>autogen v0.4</b></span>
        <span>tools <b>tavily</b> · <b>semantic-scholar</b></span>
        <span>guardrails <b>input</b> · <b>output</b> · <b>provenance</b></span>
        <span style={{ marginLeft: "auto" }}>⌘ ↵ to run</span>
      </footer>

    </div>
  );
}

/* ---------------- App — client-side state machine ---------------- */
function App() {
  // Core state: which session is displayed (client-side, no Streamlit rerun)
  const [currentStateId, setCurrentStateId] = useState(_INITIAL_STATE_ID || "idle");
  const [mode, setMode] = useState("autogen");

  // Live-partial polling: while a run is active, the iframe self-polls the
  // statically-served live_partial.json so Streamlit does NOT rerun. This
  // eliminates the 1.5s flicker the st_autorefresh-based design caused.
  const [livePartial, setLivePartial] = useState(null);
  const isLiveRun = _RUN_ACTIVE === true && (currentStateId === "live" || _INITIAL_STATE_ID === "live");

  useEffect(() => {
    if (!isLiveRun) return;
    let cancelled = false;
    const pickFetcher = () => {
      try {
        if (window.parent && typeof window.parent.fetch === "function") {
          return { fn: window.parent.fetch.bind(window.parent), origin: window.parent.location.origin };
        }
      } catch (e) { /* cross-origin, fall through */ }
      return { fn: window.fetch.bind(window), origin: "" };
    };
    const poll = async () => {
      if (cancelled) return;
      try {
        const { fn, origin } = pickFetcher();
        const url = origin + "/app/static/live_partial.json?t=" + Date.now();
        const r = await fn(url, { cache: "no-store" });
        if (!r.ok) throw new Error("fetch " + r.status);
        const data = await r.json();
        if (cancelled) return;
        setLivePartial(data);
        const status = data && data.raw_status;
        if (status === "complete" || status === "error") {
          cancelled = true;
          // Trigger Streamlit-side finalization. Top-frame URL change so the
          // streamlit script reruns ONCE (acceptable single flicker at end).
          try {
            if (window.top && window.top.location) {
              window.top.location.href = window.top.location.pathname + "?finalize=1";
              return;
            }
          } catch (e) { /* sandbox blocked — fall through to postMessage */ }
          try { window.parent.postMessage({ type: "omc_navigate", params: { finalize: "1" } }, "*"); } catch (e) {}
          return;
        }
      } catch (e) {
        // Network/parse errors are non-fatal; keep polling.
        console.warn("[live-poll]", e && e.message);
      }
      if (!cancelled) setTimeout(poll, 2500);
    };
    poll();
    return () => { cancelled = true; };
  }, [isLiveRun]);

  // Resolve the current session object: prefer the freshly-polled partial
  // when running; otherwise fall back to window.SESSIONS by current id.
  const partialSession = (livePartial && livePartial.session) || null;
  const session = (isLiveRun && partialSession) ? partialSession : getSession(currentStateId);

  // Derived values from current session
  const view        = session ? (session.viewState || "idle") : "idle";
  const railSources = (session && session.railSources) || {};
  const evalScores  = session && session.evalScores;
  const editPrefill = (!session && _LEGACY_STATE && _LEGACY_STATE.session && _LEGACY_STATE.session.editPrefill) || "";

  // State change handler: switch client-side + update URL bar silently
  const handleStateChange = (newStateId) => {
    setCurrentStateId(newStateId);
    updateUrlSilent(newStateId);
  };

  // Client-side switch — all sessions are pre-loaded into window.SESSIONS by
  // streamlit_app.py's _build_all_sessions(). No Streamlit roundtrip or
  // iframe re-mount needed → no flicker.
  const onPickHistory = (hid) => {
    if (!hid) return;
    if (hid === "__separator__" || hid === "__separator2__") return;
    if (hid === "idle" || hid === "start") {
      handleStateChange("idle");
      return;
    }
    // Q1/Q5/Q6/live_* are all in window.SESSIONS already.
    handleStateChange(hid);
  };

  // Group debate messages so they can render as a single DebateCard
  const trace = (session && session.trace) || [];
  const optimistMsg = trace.find(m => m.agent === "optimist");
  const skepticMsg  = trace.find(m => m.agent === "skeptic");
  const verdictMsg  = trace.find(m => m.agent === "research_manager");

  // Render trace; collapse the optimist+skeptic+RM chunk into one DebateCard.
  // Build in chronological order, then reverse so newest renders at top.
  const renderedTrace = [];
  let debateInjected = false;
  trace.forEach((m, i) => {
    if (["optimist", "skeptic", "research_manager"].includes(m.agent)) {
      if (!debateInjected) {
        renderedTrace.push(
          <DebateCard key={"debate-" + i}
            active={view === "loading" || view === "debate"}
            optimistMsg={optimistMsg}
            skepticMsg={skepticMsg}
            verdictMsg={verdictMsg}
            railSources={railSources}
          />
        );
        debateInjected = true;
      }
      return;
    }
    renderedTrace.push(<MsgCard key={i} m={m} railSources={railSources} />);
  });

  // In debate phase but trace has fewer than the optimist message → active DebateCard
  if (view === "debate" && !debateInjected) {
    renderedTrace.push(
      <DebateCard key="debate-active" active={true}
        optimistMsg={optimistMsg} skepticMsg={skepticMsg} verdictMsg={verdictMsg}
        railSources={railSources} />
    );
  }

  // Reverse so the most-recently-completed agent renders at the top of the
  // trace stream. Planner ends up at the bottom; each new agent appears above
  // the previous one. (User feedback 2026-05-07: 'planner should be at bottom'.)
  renderedTrace.reverse();

  const isEntryView = currentStateId === "idle";
  const isIdleDashboard = currentStateId === "idle_dashboard";

  if (isEntryView) {
    return <EntryPage onStateChange={handleStateChange} />;
  }

  // idle_dashboard: full chrome (sidebar + rail + topbar) but main area shows awaiting placeholder
  if (isIdleDashboard) {
    return (
      <div className="app">
        <TopBar mode={mode} setMode={setMode} onSkip={handleStateChange} />
        <Sidebar history={_HISTORY} onPick={onPickHistory} activeStateId={currentStateId} />
        <main className="main">
          <header className="query-header">
            <div className="query-header__top">
              <span className="query-header__id">—</span>
              <span>·</span>
              <span className="query-header__status" style={{ color: "var(--fg-tertiary)" }}>● no active research</span>
            </div>
            <h1 style={{ color: "var(--fg-tertiary)", fontWeight: 400, fontSize: "17px", margin: "6px 0 4px" }}>No active research</h1>
            <div className="query-header__meta" />
            <Stepper pipeline={PIPELINE_KEYS} state={{plan:"pending",web:"pending",acad:"pending",counter:"pending",debate:"pending",write:"pending",critic:"pending"}} />
          </header>
          <div className="awaiting-card">
            <div className="awaiting-card__icon" aria-hidden="true">◌</div>
            <h2 className="awaiting-card__title">Awaiting query</h2>
            <p className="awaiting-card__desc">
              No active research. Start a new query, or pick a past run from the sidebar.
            </p>
            <div className="awaiting-card__actions">
              <button
                className="start-new-query-btn start-new-query-btn--primary"
                onClick={() => handleStateChange("idle")}
              >
                Start a new query
                <span className="start-new-query-btn__arrow" aria-hidden="true">→</span>
              </button>
            </div>
          </div>
        </main>
        <aside className="rail">
          <ActiveAgent session={null} />
          <SafetyPanel events={[]} />
          <EvalPanel session={null} collapsed={false} />
          <SourcesPanel ids={[]} railSources={{}} />
          <ExportMenu disabled={true} session={{}} />
        </aside>
        <StatusBar session={null} mode={mode} />
      </div>
    );
  }

  return (
    <div className="app">
      <TopBar mode={mode} setMode={setMode} onSkip={handleStateChange} />
      <Sidebar
        history={_HISTORY}
        onPick={onPickHistory}
        activeStateId={currentStateId}
      />

      <main className="main">
        {/* Idle view: show EmptyState only when truly in idle state (session is null AND stateId is idle) */}
        {!session && currentStateId !== "idle_dashboard" && currentStateId === "idle" && (
          <EmptyState editPrefill={editPrefill} />
        )}

        {/* No-data placeholder: state is selected but no real run has produced data for it */}
        {!session && currentStateId !== "idle" && currentStateId !== "idle_dashboard" && (
          <NoDataState stateId={currentStateId} onGoStart={handleStateChange} />
        )}

        {session && (
          <>
            <header className="query-header">
              <div className="query-header__top">
                <span className="query-header__id">{session.id}</span>
                <span>·</span>
                <span>{session.startedAt}</span>
                <span>·</span>
                <span className={"query-header__status query-header__status--" +
                  (view === "refused" ? "refused" : view === "complete" ? "complete" : "running")}>
                  {view === "refused" ? "● refused" :
                    view === "complete" ? "● complete" :
                      view === "debate" ? "● debate active" :
                        "● running"}
                </span>
                <span style={{ marginLeft: "auto" }}>
                  <span className="consistency-badge">
                    <span><b>{STAGE_COUNT}</b> stages</span>
                    <span>→</span>
                    <span><b>{STEP_COUNT}</b> steps</span>
                    <span>→</span>
                    <span><b>{AGENT_COUNT}</b> agents</span>
                  </span>
                </span>
              </div>
              <h1>{session.query}</h1>
              <div className="query-header__meta">
                <span><b>{session.meta.num_messages}</b>messages</span>
                <span><b>{session.meta.num_sources}</b>sources</span>
                <span><b>{session.meta.debate_rounds}</b>debate rounds</span>
                <span><b>{session.meta.revisions}</b>revisions</span>
                <span><b>{(session.meta.total_duration_seconds || 0).toFixed(1)}s</b>elapsed</span>
              </div>
              {view !== "refused" && (
                <Stepper pipeline={session.pipeline || PIPELINE_KEYS} state={session.pipelineState || {}} />
              )}
            </header>

            {view === "refused" && session.refusal && (
              <RefusedBanner refusal={session.refusal} session={session} />
            )}

            {view === "complete" && session.response && (
              <FinalReport response={session.response} session={session} railSources={railSources} />
            )}

            {/* Round-3 Fix 4: bridge the dead-air gap before the first agent message */}
            {session.status === "running" && (!session.trace || session.trace.length === 0) && (
              <StartingState />
            )}

            <div className="trace">
              {(view === "loading" || view === "debate") && session.activeAgent && (
                <LoadingMsg agent={session.activeAgent.id} status={session.activeAgent.status || "thinking"} />
              )}
              {renderedTrace}
            </div>
          </>
        )}
      </main>

      <aside className="rail">
        {view === "idle" ? (
          <CockpitPanel />
        ) : (
          <>
            <ActiveAgent session={session} />
            <SafetyPanel events={(session && session.safety) || []} />
            <EvalPanel session={session} collapsed={false} />
            <SourcesPanel ids={(session && session.sources) || []} railSources={railSources} />
            <ExportMenu disabled={view !== "complete"} session={session || {}} />
          </>
        )}
      </aside>

      <StatusBar session={session} mode={mode} />
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
