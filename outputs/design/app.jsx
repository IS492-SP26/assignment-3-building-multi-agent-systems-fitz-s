/* global React, ReactDOM, window */
const { useState, useMemo } = React;

function App() {
  // viewState: start | idle | loading | debate | refused | complete
  const [viewState, setViewState] = useState("start");
  const [mode, setMode] = useState("autogen");

  // pick the underlying session JSON to drive the panel from
  const session = useMemo(() => {
    if (viewState === "refused") return window.SESSIONS.Q6;
    if (viewState === "loading" || viewState === "debate") return window.SESSIONS.Q5;
    return window.SESSIONS.Q1;
  }, [viewState]);

  const activeId =
    viewState === "refused" ? "Q6" :
    viewState === "loading" || viewState === "debate" ? "Q5" :
    viewState === "idle" || viewState === "start" ? null : "Q1";

  return (
    <div className="app">
      {viewState === "start" && (
        <window.StartPage
          onStart={()=>setViewState("loading")}
          onSkip={()=>setViewState("complete")}
        />
      )}
      <window.TopBar mode={mode} setMode={setMode} />
      <window.Sidebar
        activeId={activeId}
        history={window.HISTORY}
        onPick={() => {}}
      />

      <main className="main">
        {viewState === "idle" && <window.EmptyState />}

        {viewState !== "idle" && (
          <>
            <header className="query-header">
              <div className="query-header__top">
                <span className="query-header__id">{session.id}</span>
                <span>·</span>
                <span>{session.startedAt}</span>
                <span>·</span>
                <span className={"query-header__status query-header__status--" +
                  (viewState === "refused" ? "refused" :
                   viewState === "complete" ? "complete" :
                   "running")}>
                  {viewState === "refused" ? "● refused" :
                   viewState === "complete" ? "● complete" :
                   "● running"}
                </span>
              </div>
              <h1>{session.query}</h1>
              <div className="query-header__meta">
                <span><b>{session.meta.num_messages}</b>messages</span>
                <span><b>{session.meta.num_sources}</b>sources</span>
                <span><b>{session.meta.debate_rounds}</b>debate rounds</span>
                <span><b>{session.meta.revisions}</b>revisions</span>
                <span><b>{session.meta.total_duration_seconds.toFixed(1)}s</b>elapsed</span>
              </div>
              {viewState !== "refused" && (
                <window.Stepper
                  pipeline={session.pipeline}
                  state={
                    viewState === "loading"
                      ? { plan:"done", web:"done", acad:"active", counter:"pending", debate:"pending", write:"pending", critic:"pending" }
                      : viewState === "debate"
                      ? { plan:"done", web:"done", acad:"done", counter:"done", debate:"active", write:"pending", critic:"pending" }
                      : session.pipelineState
                  }
                />
              )}
            </header>

            {viewState === "refused" && session.refusal && (
              <window.RefusedBanner refusal={session.refusal} />
            )}

            <div className="trace">
              {/* Render trace messages — but for non-complete views, truncate / inject loading */}
              {(viewState === "complete") &&
                session.trace.map((m, i) => {
                  if (m.agent === "_debate_round_1") {
                    return <window.DebateCard key={i} active={false} />;
                  }
                  return <window.MsgCard key={i} m={m} />;
                })
              }

              {viewState === "loading" &&
                session.trace.slice(0, 4).map((m, i) => (
                  m.agent === "_debate_round_1_active"
                    ? null
                    : <window.MsgCard key={i} m={m} />
                ))
              }
              {viewState === "loading" && (
                <window.LoadingMsg agent="academic_researcher" status="querying semantic-scholar · 4 results" />
              )}

              {viewState === "debate" &&
                session.trace.slice(0, 5).map((m, i) => (
                  m.agent === "_debate_round_1_active"
                    ? null
                    : <window.MsgCard key={i} m={m} />
                ))
              }
              {viewState === "debate" && (
                <window.DebateCard active={true} />
              )}

              {viewState === "refused" && (
                <window.MsgCard m={session.trace[0]} />
              )}
            </div>
          </>
        )}
      </main>

      <aside className="rail">
        <window.ActiveAgent
          session={
            viewState === "loading"
              ? { ...session, activeAgent: { id: "academic_researcher", status: "Querying" } }
              : viewState === "debate"
              ? { ...session, activeAgent: { id: "research_manager", status: "Adjudicating" } }
              : viewState === "complete"
              ? { ...session, activeAgent: null, status: "complete" }
              : session
          }
        />
        {viewState === "idle" && <window.LegendPanel />}
        <window.SafetyPanel events={session.safety} />
        <window.SourcesPanel ids={session.sources} />
        <window.ExportMenu disabled={viewState !== "complete"} />
      </aside>

      <window.StatusBar session={session} mode={mode} />

      {/* State toggle bar */}
      <div className="state-bar" role="tablist" aria-label="Demo states">
        <span className="state-bar__label">STATE</span>
        {[
          ["start","Start"],
          ["idle","Idle"],
          ["loading","Loading"],
          ["debate","Debate Active"],
          ["refused","Refused"],
          ["complete","Complete"],
        ].map(([k, label]) => (
          <button
            key={k}
            role="tab"
            aria-selected={viewState===k}
            className={"state-bar__btn " + (viewState===k ? "state-bar__btn--on" : "")}
            onClick={()=>setViewState(k)}
          >{label}</button>
        ))}
      </div>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
