# Handback Instructions (after Claude Design)

When Claude Design (claude.ai) produces the Artifact:

1. Copy the entire HTML artifact content
2. Save it as: `outputs/design/prototype.html`
3. (Optional) If you want to add visual notes for me, save them as: `outputs/design/notes.md`
4. Return to this Claude Code session and say: **"design done"**

I will then:
- Extract `:root { --* }` CSS variables → `src/ui/styles.css`
- Parse `<!-- COMPONENT_NOTES_BEGIN -->` → build implementation plan
- Replace skeleton `streamlit_app.py` with full implementation
- Take screenshots of all 5 states for `outputs/screenshots/`
- Compare with prototype.html and log gaps to `outputs/design/visual_gaps.md`

If anything in the design can't be done in Streamlit, I'll flag it and we'll do a second Claude Design pass.
