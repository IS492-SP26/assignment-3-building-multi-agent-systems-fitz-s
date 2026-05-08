/* global React, window */
const { useState, useRef, useEffect } = React;

/* ---------------- Icons ---------------- */
const I = {
  search:  (p) => <svg width="13" height="13" viewBox="0 0 16 16" fill="none" {...p}><circle cx="7" cy="7" r="4.5" stroke="currentColor" strokeWidth="1.4"/><path d="m11 11 3 3" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/></svg>,
  plus:    (p) => <svg width="12" height="12" viewBox="0 0 16 16" fill="none" {...p}><path d="M8 3v10M3 8h10" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/></svg>,
  cog:     (p) => <svg width="14" height="14" viewBox="0 0 16 16" fill="none" {...p}><circle cx="8" cy="8" r="2.2" stroke="currentColor" strokeWidth="1.3"/><path d="M8 1.5v1.8M8 12.7v1.8M14.5 8h-1.8M3.3 8H1.5M12.6 3.4l-1.3 1.3M4.7 11.3l-1.3 1.3M12.6 12.6l-1.3-1.3M4.7 4.7 3.4 3.4" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/></svg>,
  chevR:   (p) => <svg width="10" height="10" viewBox="0 0 16 16" fill="none" {...p}><path d="m6 4 4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>,
  chevD:   (p) => <svg width="10" height="10" viewBox="0 0 16 16" fill="none" {...p}><path d="m4 6 4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>,
  link:    (p) => <svg width="11" height="11" viewBox="0 0 16 16" fill="none" {...p}><path d="M7 9.5c.7.9 1.9 1 2.7.2L12 7.4c.9-.9.9-2.4 0-3.3-.9-.9-2.4-.9-3.3 0L7.4 5.4M9 6.5c-.7-.9-1.9-1-2.7-.2L4 8.6c-.9.9-.9 2.4 0 3.3.9.9 2.4.9 3.3 0L8.6 10.6" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/></svg>,
  download:(p) => <svg width="12" height="12" viewBox="0 0 16 16" fill="none" {...p}><path d="M8 2v8m0 0 3-3m-3 3-3-3M3 13h10" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/></svg>,
  bolt:    (p) => <svg width="12" height="12" viewBox="0 0 16 16" fill="none" {...p}><path d="m9 1-6 8h4l-1 6 6-8H8l1-6Z" fill="currentColor"/></svg>,
  shield:  (p) => <svg width="13" height="13" viewBox="0 0 16 16" fill="none" {...p}><path d="M8 1.5 2.5 3.5v4.7c0 3.3 2.4 5.6 5.5 6.3 3.1-.7 5.5-3 5.5-6.3V3.5L8 1.5Z" stroke="currentColor" strokeWidth="1.3"/></svg>,
  warn:    (p) => <svg width="14" height="14" viewBox="0 0 16 16" fill="none" {...p}><path d="M8 2 1.8 13h12.4L8 2Z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round"/><path d="M8 6.5v3" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/><circle cx="8" cy="11.5" r=".7" fill="currentColor"/></svg>,
  shieldX: (p) => <svg width="16" height="16" viewBox="0 0 16 16" fill="none" {...p}><path d="M8 1.5 2.5 3.5v4.7c0 3.3 2.4 5.6 5.5 6.3 3.1-.7 5.5-3 5.5-6.3V3.5L8 1.5Z" stroke="currentColor" strokeWidth="1.4"/><path d="m6 6 4 4M10 6l-4 4" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/></svg>,
  check:   (p) => <svg width="11" height="11" viewBox="0 0 16 16" fill="none" {...p}><path d="m3.5 8.5 3 3 6-7" stroke="#0d1117" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>,
  x:       (p) => <svg width="11" height="11" viewBox="0 0 16 16" fill="none" {...p}><path d="m4 4 8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/></svg>,
  scales:  (p) => <svg width="12" height="12" viewBox="0 0 16 16" fill="none" {...p}><path d="M8 2v12M3 5h10M3 5l-1.5 4h3L3 5Zm10 0-1.5 4h3L13 5Z" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"/></svg>,
  sparkle: (p) => <svg width="14" height="14" viewBox="0 0 16 16" fill="none" {...p}><path d="M8 1v4M8 11v4M1 8h4M11 8h4M3.5 3.5l2.5 2.5M10 10l2.5 2.5M3.5 12.5l2.5-2.5M10 6l2.5-2.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/></svg>,
};

/* ---------------- Top Bar ---------------- */
function TopBar({ mode, setMode }) {
  const modes = ["autogen","cli","web","eval","demo"];
  return (
    <header className="topbar">
      <div className="topbar__brand">
        <div className="topbar__logo" aria-hidden="true">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <circle cx="3" cy="3" r="1.6" fill="var(--agent-planner)"/>
            <circle cx="11" cy="3" r="1.6" fill="var(--agent-web-researcher)"/>
            <circle cx="7"  cy="7" r="1.6" fill="var(--agent-research-manager)"/>
            <circle cx="3"  cy="11" r="1.6" fill="var(--agent-skeptic)"/>
            <circle cx="11" cy="11" r="1.6" fill="var(--agent-optimist)"/>
            <path d="M3 3 7 7M11 3 7 7M3 11 7 7M11 11 7 7" stroke="var(--fg-tertiary)" strokeWidth="0.7"/>
          </svg>
        </div>
        <div className="topbar__name">Agentic UX <span>/ deep research</span></div>
      </div>

      <nav className="breadcrumb" aria-label="breadcrumb">
        <span>workspace</span>
        <I.chevR />
        <span>hci</span>
        <I.chevR />
        <b>agentic-ux</b>
      </nav>

      <div className="mode-chips" role="tablist" aria-label="Run mode">
        {modes.map((m) => (
          <button
            key={m}
            role="tab"
            aria-selected={mode === m}
            className={"mode-chip " + (mode === m ? "mode-chip--on" : "")}
            onClick={() => setMode(m)}
          >{m}</button>
        ))}
      </div>

      <div className="topbar__actions">
        <span className="kbd">⌘ K</span>
        <button className="icon-btn" title="Settings" aria-label="Settings"><I.cog /></button>
      </div>
    </header>
  );
}

/* ---------------- Sidebar ---------------- */
function Sidebar({ activeId, onPick, history }) {
  return (
    <aside className="sidebar">
      <div className="sidebar__section">
        <h3 className="sidebar__heading">Search <span className="count">⌘K</span></h3>
        <div className="search">
          <span className="search__icon"><I.search /></span>
          <input placeholder="Search queries…" />
          <span className="search__kbd kbd">/</span>
        </div>
        <button className="new-query-btn"><I.plus /> New query</button>
      </div>

      <div className="sidebar__section" style={{flex:1, overflow:"hidden", display:"flex", flexDirection:"column", padding:"10px 6px 6px"}}>
        <h3 className="sidebar__heading" style={{padding:"0 8px"}}>
          History <span className="count">{history.length}</span>
        </h3>
        <ul className="history-list" style={{listStyle:"none", padding:"4px 2px 0", margin:0}}>
          {history.map((h) => (
            <li
              key={h.id}
              className={"history-item history-item--" + h.status + (activeId===h.id ? " history-item--active" : "")}
              onClick={() => onPick(h.id)}
            >
              <span className="history-item__dot" />
              <span className="history-item__title">{h.title}</span>
              <span className="history-item__meta">{h.time}</span>
            </li>
          ))}
        </ul>
      </div>

      <div className="sidebar__group">
        <h3 className="sidebar__heading" style={{margin:"0 0 6px"}}>Session</h3>
        <div className="sidebar__row"><span>Pipeline</span><b>4 stages</b></div>
        <div className="sidebar__row"><span>Agents</span><b>9</b></div>
        <div className="sidebar__row"><span>Backend</span><b>autogen</b></div>
        <div className="sidebar__row"><span>Model</span><b>gpt-4o-mini</b></div>
      </div>
    </aside>
  );
}

/* ---------------- Stepper ---------------- */
const STEP_LABELS = {
  plan: "Plan", web: "Web", acad: "Academic", counter: "Counter",
  debate: "Debate", write: "Write", critic: "Critic",
};
function Stepper({ pipeline, state }) {
  return (
    <div className="stepper" role="list" aria-label="Pipeline progress">
      {pipeline.map((s, i) => {
        const st = state[s] || "pending";
        return (
          <React.Fragment key={s}>
            <div className={"stepper__node stepper__node--" + st} role="listitem" aria-label={STEP_LABELS[s] + " " + st}>
              <div className="stepper__circle">
                {st==="done" && <I.check />}
              </div>
              <span className="stepper__label">{STEP_LABELS[s]}</span>
            </div>
            {i < pipeline.length-1 && (
              <span className={"stepper__connector " + ((state[s]==="done") ? "stepper__connector--done" : "")} aria-hidden="true"/>
            )}
          </React.Fragment>
        );
      })}
    </div>
  );
}

/* ---------------- Citation chip ---------------- */
function Cite({ id }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const data = window.CITE_PREVIEWS[id];
  if (!data) return <span className="cite">[{id}]</span>;
  return (
    <span ref={ref} className="cite" tabIndex="0"
      role="button"
      aria-label={`Citation ${id}: ${data.title}`}
      onMouseEnter={()=>setOpen(true)} onMouseLeave={()=>setOpen(false)}
      onFocus={()=>setOpen(true)} onBlur={()=>setOpen(false)}
    >
      [{id}]
      {open && (
        <span className="cite-tooltip" role="tooltip">
          <span className="cite-tooltip__type">
            <span>{data.type}</span>
            {data.authority && <span style={{color:"var(--fg-tertiary)"}}>· {data.authority}</span>}
          </span>
          <div className="cite-tooltip__title">{data.title}</div>
          <div className="cite-tooltip__preview">{data.preview}</div>
          <div className="cite-tooltip__url">{data.url}</div>
        </span>
      )}
    </span>
  );
}

/* render text with [S\d] tokens replaced by Cite chips */
function renderBody(text) {
  if (!text) return null;
  // split into paragraphs by blank lines
  const blocks = text.split(/\n\n+/);
  return blocks.map((block, bi) => {
    // heading?
    if (block.startsWith("# ")) return <h3 key={bi} style={{fontFamily:"var(--font-body)", fontWeight:600, fontSize:"15px", margin:"2px 0 6px"}}>{block.slice(2)}</h3>;
    if (block.startsWith("## ")) return <h3 key={bi}>{block.slice(3)}</h3>;
    // list?
    if (/^- /m.test(block)) {
      const items = block.split(/\n- |^- /).filter(Boolean);
      return <ul key={bi}>{items.map((it,ii)=><li key={ii}>{tokenize(it)}</li>)}</ul>;
    }
    return <p key={bi}>{tokenize(block)}</p>;
  });
}
function tokenize(text) {
  // [S1], [S2] -> chip
  const parts = text.split(/(\[S\d+\])/g);
  return parts.map((p,i)=>{
    const m = p.match(/^\[S(\d+)\]$/);
    if (m) return <Cite key={i} id={"S"+m[1]}/>;
    return <React.Fragment key={i}>{p}</React.Fragment>;
  });
}

/* ---------------- Message Card ---------------- */
function MsgCard({ m }) {
  const a = window.AGENTS[m.agent] || { name:m.agent, role:"", color:"var(--fg-secondary)", initials:"?"};
  const [expanded, setExpanded] = useState(false);
  const isLong = (m.body || "").length > 280;
  const isUser = m.agent === "user";

  return (
    <article className={"msg-card " + (isUser ? "msg-card--user" : "")} aria-label={`Message from ${a.name}`}>
      <div className="msg-avatar" style={{background: a.color}} aria-hidden="true">
        {a.initials}
      </div>
      <div>
        <div className="msg-head">
          <span className="agent-chip">
            <span className="agent-chip__bar" style={{background: a.color}} />
            {a.name}
          </span>
          {m.role && <span className="msg-role">{m.role}</span>}
          {m.stage && <span className="msg-stage">· {m.stage}</span>}
          {m.sanitized && <span className="sanitized" title="Provenance verifier trimmed an unsourced sentence"><I.warn/> Sanitized</span>}
          <span className="msg-time">{m.time}</span>
          {m.duration && <span className="msg-dur">{m.duration}</span>}
        </div>
        <div className={"msg-body " + (isLong && !expanded ? "msg-body--collapsed" : "")}>
          {renderBody(m.body)}
        </div>
        {isLong && (
          <button className="msg-expand" onClick={()=>setExpanded(!expanded)}>
            {expanded ? "▴ Collapse" : "▾ Expand "+m.body.length+" chars"}
          </button>
        )}
      </div>
    </article>
  );
}

/* ---------------- Loading message (skeleton) ---------------- */
function LoadingMsg({ agent, status }) {
  const a = window.AGENTS[agent] || { name:agent, color:"var(--fg-secondary)", initials:"?"};
  return (
    <article className="msg-card" aria-busy="true">
      <div className="msg-avatar" style={{background: a.color}}>{a.initials}</div>
      <div>
        <div className="msg-head">
          <span className="agent-chip"><span className="agent-chip__bar" style={{background: a.color}}/>{a.name}</span>
          <span className="msg-role">working</span>
        </div>
        <div className="msg-loading">
          <span>{status || "thinking"}</span>
          <span className="msg-loading__dots"><span/><span/><span/></span>
        </div>
      </div>
    </article>
  );
}

/* ---------------- Debate Card ---------------- */
function DebateCard({ active }) {
  const A = window.AGENTS;
  return (
    <section className={"debate"} aria-label="Debate round">
      <div className="debate__head">
        <div className="debate__icon"><I.scales /></div>
        <div className="debate__title">Debate <span className="round">round 1 of 2</span></div>
        <span className="msg-time">09:46:12 → 09:47:08</span>
      </div>
      <div className="debate__body">
        <div className="debate__side debate__side--optimist">
          <div className="msg-head">
            <span className="agent-chip"><span className="agent-chip__bar" style={{background:A.optimist.color}}/>Optimist</span>
            <span className="msg-dur">14s</span>
          </div>
          <div className="msg-body">
            <div className="debate__quote">
              {tokenize("Scaffolded retrieval and structured citation are sufficient to mitigate hallucination at the UX layer; multi-agent debate calibrates contested claims by 18 points [S7].")}
            </div>
          </div>
        </div>
        <div className="debate__side debate__side--skeptic">
          <div className="msg-head">
            <span className="agent-chip"><span className="agent-chip__bar" style={{background:A.skeptic.color}}/>Skeptic</span>
            <span className="msg-dur">17s</span>
          </div>
          <div className="msg-body">
            <div className="debate__quote">
              {tokenize("Empirical incidents show agents acting outside user intent; bounded autonomy is the only currently shippable mitigation [S4]. Field reports caution that production agents remain narrow [S5].")}
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
              ? <>Adjudicating: weighing scaffolded retrieval [S7] against bounded-autonomy field evidence [S4]…</>
              : tokenize("Both stances accepted as partial. Synthesis should split established consensus [S1][S2] from contested terrain [S4][S7], not collapse into a single verdict.")}
          </div>
        </div>
        <span className="debate__verdict-tag">{active ? "deliberating" : "synthesis → writer"}</span>
      </div>
    </section>
  );
}

/* ---------------- Right rail ---------------- */
function ActiveAgent({ session }) {
  if (!session.activeAgent) {
    return (
      <div className="active-agent active-agent--idle" aria-label="Active agent: none">
        <span className="active-agent__dot" />
        <span className="active-agent__name">No agent active</span>
        <span className="active-agent__status">{session.status === "complete" ? "complete" : session.status === "refused" ? "refused" : "idle"}</span>
      </div>
    );
  }
  const a = window.AGENTS[session.activeAgent.id];
  return (
    <div className="active-agent" aria-label={`Active agent: ${a.name}`}>
      <span className="active-agent__dot" style={{background: a.color}} />
      <span className="active-agent__name" style={{color: a.color}}>{a.name}</span>
      <span className="active-agent__status">{session.activeAgent.status}</span>
    </div>
  );
}

function SafetyPanel({ events }) {
  return (
    <section className="rail__panel" aria-labelledby="safety-h">
      <div className="rail__panel-head">
        <span id="safety-h">Safety</span>
        <span className="count">{events.length} event{events.length===1?"":"s"}</span>
      </div>
      <div className="rail__panel-body">
        {events.map((e, i) => {
          const cls = e.sev === "block" ? "safety--block" : e.sev === "warn" ? "safety--warn" : "safety--pass";
          const icon = e.sev === "block" ? "✗" : e.sev === "warn" ? "⚠" : "✓";
          return (
            <div key={i} className={"safety " + cls}>
              <div className="safety__chip">{icon}</div>
              <div>
                <div className="safety__title">{e.msg}</div>
                <div className="safety__sub">{e.cat} · action: {e.action}</div>
                <a className="safety__link" href="#log">View raw event log →</a>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function SourcesPanel({ ids }) {
  const [open, setOpen] = useState(ids[0] || null);
  return (
    <section className="rail__panel" aria-labelledby="src-h">
      <div className="rail__panel-head">
        <span id="src-h">Sources</span>
        <span className="count">({ids.length})</span>
      </div>
      <div className="rail__panel-body">
        {ids.length === 0 && (
          <div style={{padding:"8px 12px", color:"var(--fg-tertiary)", fontSize:"12px", fontStyle:"italic"}}>
            No sources retrieved.
          </div>
        )}
        {ids.map((id) => {
          const s = window.CITE_PREVIEWS[id] || { title:`Source ${id}`, type:"web", url:"" };
          const isOpen = open === id;
          return (
            <div key={id} className="source" onClick={()=>setOpen(isOpen ? null : id)}>
              <div className="source__head">
                <span className="source__id">[{id}]</span>
                <span className="source__title">{s.title}</span>
              </div>
              <div className="source__meta">
                <span className={"source__type source__type--"+s.type}>{s.type}</span>
                {s.year && <span>{s.year}</span>}
                {s.authors && s.authors.length>0 && <span>{s.authors.join(", ")}</span>}
                {s.authority && <span className="source__authority">· {s.authority}</span>}
              </div>
              {isOpen && (
                <div className="source__details">
                  {s.preview}
                  <div style={{marginTop:6}}>
                    <a href={s.url}><I.link/> {s.url}</a>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}

function ExportMenu({ disabled }) {
  const [open, setOpen] = useState(false);
  return (
    <section className="rail__panel">
      <div className="rail__panel-head">
        <span>Export</span>
      </div>
      <div className="rail__panel-body">
        <div className="export">
          <button className="export__btn" onClick={()=>setOpen(!open)} disabled={disabled} aria-haspopup="menu" aria-expanded={open}>
            <span style={{display:"inline-flex", alignItems:"center", gap:8}}><I.download/> Export session</span>
            <I.chevD />
          </button>
          {open && (
            <div className="export__menu" role="menu">
              <button className="export__opt" role="menuitem">JSON · trace+sources <span className="export__opt-ext">.json</span></button>
              <button className="export__opt" role="menuitem">Markdown · final report <span className="export__opt-ext">.md</span></button>
              <button className="export__opt" role="menuitem">HTML · self-contained <span className="export__opt-ext">.html</span></button>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

/* ---------------- Refused banner ---------------- */
function RefusedBanner({ refusal }) {
  return (
    <div className="refused-banner" role="alert">
      <div className="refused-banner__icon"><I.shieldX /></div>
      <div>
        <h2 className="refused-banner__title">{refusal.title} <span className="cat">{refusal.category}</span></h2>
        <p className="refused-banner__body">{refusal.body}</p>
        <div className="refused-banner__pattern" title="Trigger pattern">
          pattern: /{refusal.pattern}/ &nbsp;→ matched <span style={{color:"var(--accent-red)"}}>"{refusal.match}"</span>
        </div>
      </div>
      <button className="refused-banner__cta">Edit query →</button>
    </div>
  );
}

/* ---------------- Empty state ---------------- */
function EmptyState({ onPick }) {
  const tips = [
    "What are the key open challenges in agentic UX as of 2025?",
    "Are LLM agents replacing UIs or augmenting them?",
    "How does multi-agent debate calibrate factual claims?",
  ];
  return (
    <div className="empty">
      <div className="empty__inner">
        <div className="empty__art" aria-hidden="true">
          <svg width="64" height="64" viewBox="0 0 64 64" fill="none">
            <circle cx="14" cy="14" r="4" fill="var(--agent-planner)" opacity="0.7"/>
            <circle cx="50" cy="14" r="4" fill="var(--agent-web-researcher)" opacity="0.7"/>
            <circle cx="32" cy="32" r="5" fill="var(--agent-research-manager)"/>
            <circle cx="14" cy="50" r="4" fill="var(--agent-skeptic)" opacity="0.7"/>
            <circle cx="50" cy="50" r="4" fill="var(--agent-optimist)" opacity="0.7"/>
            <path d="M14 14 32 32M50 14 32 32M14 50 32 32M50 50 32 32" stroke="var(--border)" strokeWidth="1.2" strokeDasharray="2 3"/>
          </svg>
        </div>
        <h2>Start a deep research run</h2>
        <p>Type a question or pick one below. The pipeline runs 8 agents across 4 stages — planning, evidence gathering, debate, and synthesis — with a provenance guardrail.</p>
        <div className="empty__suggestions">
          {tips.map((t, i) => (
            <button key={i} className="empty__sug" onClick={() => onPick && onPick(i===0?"Q1":i===1?"Q5":"Q1")}>
              <span>{t}</span>
              <span>↵ run</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ---------------- Status bar ---------------- */
function StatusBar({ session, mode }) {
  return (
    <footer className="statusbar" role="status">
      <span className="statusbar__pulse" aria-hidden="true" />
      <b>autogen</b><span>v0.4 · gpt-4o-mini</span>
      <span className="statusbar__sep" />
      <span>session</span><b>{session.id}</b>
      <span className="statusbar__sep" />
      <span>mode</span><b>{mode}</b>
      <span className="statusbar__sep" />
      <span>messages</span><b>{session.meta.num_messages}</b>
      <span className="statusbar__sep" />
      <span>sources</span><b>{session.meta.num_sources}</b>
      <span className="statusbar__sep" />
      <span>debate-rounds</span><b>{session.meta.debate_rounds}</b>
      <span className="statusbar__sep" />
      <span>elapsed</span><b>{session.meta.total_duration_seconds.toFixed(1)}s</b>
      <span style={{marginLeft:"auto", display:"inline-flex", gap:14, alignItems:"center"}}>
        <span className="statusbar__cost">~$0.04 · 12.4k tok</span>
        <span className="statusbar__sep" />
        <span><I.shield style={{verticalAlign:"-2px", marginRight:4}}/> guardrails ON</span>
        <span>tavily</span>
        <span>semantic-scholar</span>
      </span>
    </footer>
  );
}

/* expose */
Object.assign(window, { TopBar, Sidebar, Stepper, MsgCard, LoadingMsg, DebateCard, ActiveAgent, SafetyPanel, SourcesPanel, ExportMenu, RefusedBanner, EmptyState, StatusBar, StartPage, LegendPanel });

/* ---------------- Start Page ---------------- */
function StartPage({ onStart, onSkip }) {
  const [q, setQ] = useState("");
  const tips = [
    "What are the key open challenges in agentic UX as of 2025?",
    "Are LLM agents replacing UIs or augmenting them?",
    "How does multi-agent debate calibrate factual claims?",
  ];
  return (
    <div className="start" role="dialog" aria-label="Welcome">
      <div className="start__nav">
        <div className="start__brand">
          <div className="topbar__logo" aria-hidden="true">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <circle cx="3" cy="3" r="1.6" fill="var(--agent-planner)"/>
              <circle cx="11" cy="3" r="1.6" fill="var(--agent-web-researcher)"/>
              <circle cx="7" cy="7" r="1.6" fill="var(--agent-research-manager)"/>
              <circle cx="3" cy="11" r="1.6" fill="var(--agent-skeptic)"/>
              <circle cx="11" cy="11" r="1.6" fill="var(--agent-optimist)"/>
            </svg>
          </div>
          <span>Agentic UX <span style={{color:"var(--fg-tertiary)", fontWeight:400, marginLeft:6}}>/ deep research</span></span>
        </div>
        <button className="start__skip" onClick={onSkip}>Skip to dashboard →</button>
      </div>

      <div className="start__main">
        <div className="start__hero">
          <div className="start__eyebrow">
            <span>v0.4 · autogen · gpt-4o-mini</span>
            <span className="pill">guardrails on</span>
          </div>
          <h1>Ask one question.<br/>Watch <em>nine agents</em> argue it out.</h1>
          <p className="start__lede">
            A research run sends your query through a planner, two evidence gatherers, a counter-evidence pass, an optimist/skeptic debate, and a writer/critic loop — with every citation, safety check, and dropped claim shown to you in real time.
          </p>

          <div className="start__how">
            <div className="start__how-item">
              <span className="start__how-num">01</span>
              <div className="start__how-title">Plan
                <small>The planner decomposes your question into 3–5 sub-questions.</small>
              </div>
              <span className="start__how-tag">~20s</span>
            </div>
            <div className="start__how-item">
              <span className="start__how-num">02</span>
              <div className="start__how-title">Gather evidence
                <small>Web (Tavily), Academic (Semantic Scholar), and Counter-Evidence agents pull sources in parallel.</small>
              </div>
              <span className="start__how-tag">~60s</span>
            </div>
            <div className="start__how-item">
              <span className="start__how-num">03</span>
              <div className="start__how-title">Debate
                <small>Optimist & Skeptic argue the contested claims; Research Manager adjudicates each round.</small>
              </div>
              <span className="start__how-tag">~70s</span>
            </div>
            <div className="start__how-item">
              <span className="start__how-num">04</span>
              <div className="start__how-title">Write & critique
                <small>Writer drafts a synthesis; Editor critiques. Provenance verifier strips unsourced claims.</small>
              </div>
              <span className="start__how-tag">~60s</span>
            </div>
          </div>
        </div>

        <div>
          <div className="start__form">
            <div className="start__form-label">
              <span>Your research question</span>
              <span className="start__cta-meta">3–5 minutes · ~$0.04 per run</span>
            </div>
            <textarea className="start__textarea" placeholder="e.g. What are the key open challenges in agentic UX as of 2025?"
              value={q} onChange={(e)=>setQ(e.target.value)} rows={3}
            />
            <div className="start__form-row">
              <button className="start__cta" onClick={()=>onStart(q || tips[0])}>
                Run research <I.chevR />
              </button>
              <span className="start__cta-meta">⌘ ⏎ to run</span>
            </div>

            <div className="start__suggestions">
              <div className="start__sug-title">Or pick a tested example</div>
              {tips.map((t,i)=>(
                <button key={i} className="start__sug" onClick={()=>onStart(t)}>
                  <span>{t}</span>
                  <span className="start__sug-tag">{i===0?"Q1 · 4m 12s":i===1?"Q5 · contested":"Q3"}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="start__legend">
            <div className="start__legend-title">
              <I.sparkle/> Reading the cockpit
            </div>
            <div className="start__legend-row"><b>Stage</b><span><em>4 stages</em> — plan, gather, debate, write. The big picture.</span></div>
            <div className="start__legend-row"><b>Step</b><span><em>7 stepper nodes</em> — a finer view of who runs when.</span></div>
            <div className="start__legend-row"><b>Agent</b><span><em>9 agents</em> — actors with brand colors. Multiple agents per stage.</span></div>
            <div className="start__legend-row"><b>[Sn]</b><span>Citation chip — hover for source preview, list lives in the right rail.</span></div>
            <div className="start__legend-row"><b>Sanitized</b><span>Sentence stripped by the provenance verifier (had no citation).</span></div>
          </div>
        </div>
      </div>

      <div className="start__foot">
        <span><b>backend</b> autogen v0.4</span>
        <span><b>tools</b> tavily · semantic-scholar</span>
        <span><b>guardrails</b> input · output · provenance</span>
        <span style={{marginLeft:"auto"}}><b>↵</b> press enter to run</span>
      </div>
    </div>
  );
}

/* ---------------- Legend Panel (cockpit right rail, idle only) ---------------- */
function LegendPanel() {
  return (
    <section className="rail__panel">
      <div className="rail__panel-head">
        <span>Reading this dashboard</span>
      </div>
      <div className="legend-panel">
        <p><b>Stage</b> <span className="legend-mono">×4</span> · <b>Step</b> <span className="legend-mono">×7</span> · <b>Agent</b> <span className="legend-mono">×9</span></p>
        <p>The pipeline runs through <b>4 stages</b> — plan, gather, debate, write. The header stepper shows the same flow at <b>step</b> granularity (7 nodes). Each step is run by one of <b>9 agents</b>, color-coded throughout.</p>
        <p style={{marginTop:8}}><b>Counter-Evidence</b> looks for adversarial sources during gathering. <b>Skeptic</b> argues against the consensus during the debate stage. They run at different times.</p>
      </div>
    </section>
  );
}
