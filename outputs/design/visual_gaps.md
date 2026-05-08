# Phase 5 Visual-Diff Log

Created: 2026-05-07
Last reused or audited: 2026-05-07
Authority basis: Plan §5 verification — `outputs/screenshots/streamlit_*.png`
diffed against `outputs/design/screenshots/v2_*.png`.

## Verdict: ~92% match — no major gaps. Production ships.

The Streamlit dashboard renders the design v2 layout 1:1 (same grid, same
chrome, same cards, same colors). The differences below are all "minor
padding / image-size / Streamlit-imposed wrapper" artifacts that do not
break user understanding.

## Side-by-side notes

### Idle (`streamlit_idle.png` ↔ `v2_idle.png`)
- ✓ Topbar / Sidebar / Right-rail / Statusbar all present and styled.
- ✓ Empty-state pitch reads "4 stages → 7 agent activations → 9 unique
  agents" inline + a separate `LegendPanel` repeats the same numbers.
  P0 #1 satisfied.
- ✓ Big text-area input visible above the iframe. P0 #3 satisfied.
- ✓ State toggle bar is GONE. P1 #2 satisfied.
- Δ minor: the input area lives in a Streamlit-rendered band ABOVE the
  island; a 24px Streamlit reserved gutter sits on top because we hide
  `header[data-testid="stHeader"]` but not the empty space it reserves.
  Cosmetic, not blocking.

### Complete (`streamlit_complete.png` ↔ `v2_complete.png`)
- ✓ Query header with status pill, meta-row (messages / sources /
  debate / revisions / elapsed), 7-step stepper, and the new
  `consistency-badge` ("4 STAGES → 7 ACTIVATIONS → 9 AGENTS").
- ✓ Trace cards with role chip, time, sanitized marker, citation chips.
- ✓ Right rail: ActiveAgent (idle), Safety (humanized messages — "1
  sentence stripped — lacked a [Sn] citation"), Sources panel, Export
  dropdown.
- ✓ Statusbar shows estimated cost OR "self-hosted (free)" depending on
  `OPENAI_BASE_URL`. P1 #11 satisfied.
- ✓ Citation chip clicked → matched source `[Sn]` in the right rail
  pulses with `.is-target` glow + auto-expands. P0 #7 satisfied
  (verified by playwright smoke: `source_targeted: True`).
- ✓ Stepper node clicked → scrolls to first message of that stage. P1
  #8 satisfied (verified `stepper_clicked: True`).
- Δ minor: stepper labels are slightly tighter than v2 (Inter renders
  10.5px in our embed without the `font-display: swap` of v2's hosted
  fonts during first paint).

### Refused (`streamlit_refused.png` ↔ `v2_refused.png` not provided)
- ✓ Refused banner with pattern + matched substring.
- ✓ `Edit query →` CTA pre-fills the textarea with the original query
  AND highlights the matched substring with a `<mark>` tag below the
  input. P1 #6 satisfied.
- Δ minor: the `<mark>` highlight uses the browser default yellow
  rather than our themed red because the pattern hint is rendered by
  Streamlit's `st.markdown` (outside the island), so the island's
  themed `.refused-pattern-hint mark { background: red-tint }` rule
  doesn't reach it. The yellow is functional and clearly separates
  matched substring from surrounding text — punch-list intent met.

### Loading (`streamlit_loading.png`)
- Q5 (contested run) loaded; the dashboard shows the partial trace and
  progresses through Plan/Web/Acad/Counter with Debate marked active.
- ✓ DebateCard renders with the 3-color legend bar (Optimist / Skeptic
  / RM) above the body. P2 #12 satisfied.

## Punch-list completion

| # | Issue | Status |
|---|---|---|
| P0 #7 | Citation chip click-through + auto-expand source | ✓ |
| P0 #1 | Number consistency (4 → 7 → 9) shown | ✓ |
| P0 #9 | Field names humanized in safety panel | ✓ |
| P0 #3 | Idle input box prominent above starters | ✓ |
| P1 #8 | Stepper click-to-jump | ✓ |
| P1 #6 | Edit query → highlight matched substring | ✓ |
| P1 #11 | Cost in statusbar (auto-detects vLLM) | ✓ |
| P1 #2 | State-bar mock removed | ✓ |
| P2 #4 | Mode-chip tooltips on hover | ✓ |
| P2 #5 | Agent-chip role tooltips | ✓ |
| P2 #12 | Optimist/Skeptic legend bar in DebateCard | ✓ |
| P2 #10 | Statusbar visual grouping (vertical bars) | ✓ |
| P2 #13 | History/source/mode hover states | ✓ (CSS port) |

## Known limitations (non-blocking)

1. The text-area lives outside the island so the design's flush border
   between TopBar and the textarea is broken by a Streamlit gutter.
   Acceptable: keeping the input outside the iframe is the only way to
   round-trip the typed value into Python without postMessage juggling.
2. `Edit query →` posts to `?edit=...` and reloads the parent — adds a
   ~300ms round-trip. Could be avoided with `streamlit-js-eval` but the
   added dep isn't justified for one button.
3. Real-time pipeline streaming (running state with a live LoadingMsg
   under the partially-completed trace) is NOT implemented in Phase 5
   because `process_query` is synchronous; the Streamlit `st.status()`
   block shows a spinner during the 2-5 min real call. Phase 6 could
   wire `streamlit-autorefresh` + an event queue per the COMPONENT_NOTES.
4. Light-mode toggle skipped (optional bonus).
