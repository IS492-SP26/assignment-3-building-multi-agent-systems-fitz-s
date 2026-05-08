# Critic Report v2 — Deep Research Engine Audit (not the webapp)

**Date:** 2026-05-07
**Tested by:** critic agent (adversarial, peer-reviewer lens, read-only)
**Verdict on engine quality:** **TIER-3 (Glorified Summary), one tier below "Mid-Tier Aggregator"**

This audit ignores the UI (covered in v1) and attacks the system as a deep-research engine: are the reports actual synthesis? Do the agent prompts force diversity, contestation, and quality? Does the workflow earn the "deep research" label, or is it ceremony around a single LLM doing summary work?

---

## 1. Report Quality — The Actual Deliverable

### Finding 1.1 — Reports are templated rephrasing, not synthesis. **[CRITICAL — architectural]**
The 8-section Writer template is so prescriptive that the model just fills in the blanks. Across Q1 / Q5 / live-run, every report follows IDENTICAL paragraph counts ("Three key findings emerge: (1)... (2)... (3)..." in the Introduction; 3 numbered consensus points; 2-3 numbered debates; 3-4 numbered open questions). Q1's Introduction line `"Three key findings emerge: (1) modalities like real-time trust scoring..."` and Q5's Introduction line `"Three key findings emerge: (1) structured debate protocols..."` are template-isomorphic. This is what a peer reviewer would call "the model wrote three reports for itself, then rendered them with the prescribed scaffolding" — not multi-agent synthesis.

The structure is so rigid that Q5's "Active debates" section #3 invents a debate where the report itself just admitted no evidence exists: `"Is hierarchical research-manager arbitration a viable alternative... While industry discussions suggest hierarchical arbitration could improve error correction, there are no peer-reviewed studies evaluating its performance"`. A "debate" with one position and an admission of no evidence is not a debate. It's a section the writer was contractually required to fill.

**Improvement (architectural):** Make the structure conditional. If `<2 contested points` are surfaced by the Skeptic, the Active Debates section should be replaced by "Open empirical questions" or omitted entirely. The current template forces the writer to manufacture controversies.

### Finding 1.2 — Quantitative claims are hallucinated; provenance check missed all of them. **[CRITICAL — surgical fix possible at prompt level]**
I scanned every source's `key_claim` field in `outputs/sessions/Q1_normal.json` for the five percentages cited in the Q1 report body:

| Body text claim | Source cited | Appears in any source key_claim? |
|---|---|---|
| `"Sudhir et al. (2025) report a 37% reduction in alignment errors"` | [S7] | **No** |
| `"a 2024 CHI paper found that decision diffs reduced user confusion by 28%"` | [S5] | **No** |
| `"intervention budgets... reduced alignment failures by 22% in low-risk scenarios"` | [S6] | **No** |
| `"reducing human workload by 40% in customer service bots"` | [S6] | **No** |
| `"led to 15% higher errors in high-stakes domains"` | [S6] | **No** |

Five precise quantitative claims, zero of them in any source preview. The provenance verifier passes them because they each end with a `[S#]` token — the verifier checks the citation exists in the registry, not whether the source actually contains the claim. **The "Provenance verifier" Bonus innovation does not detect citation-content mismatch — only citation-ID-presence.** Same pattern in Q5: `"Zhang et al. (2025) argue that homogeneous agent models..."` — the string "Zhang" appears in zero Q5 source key_claims (only "Zhao", "Li", "Du" do). "Zhang et al. 2025" is invented.

A peer reviewer would reject this report on ground of fabricated effect sizes. The report's most committal-sounding claims are precisely the ones with the weakest provenance.

**Improvement (surgical):** Add to WRITER_PROMPT a hard rule: "Numerical effect sizes (`\d+%`, `N=\d+`, `p<0.\d+`) and Author-Year attributions must be VERBATIM substrings of the cited source's key_claim or quoted material. Do not introduce numbers or author names not present in the registry." Pair with a regex-level post-check in `output_guardrail.py` that extracts every `\d+%` and `\b[A-Z][a-z]+ et al\.` and checks each appears somewhere in `registry.as_dict()[cited_id].key_claim`.

### Finding 1.3 — The writer hedges in the Background and Limitations, commits in the Consensus. The polarity is upside-down. **[MAJOR — surgical]**
Hedge-word density across reports:

| Report | N sentences | Hedged | Committal |
|---|---|---|---|
| Q1_normal | 59 | 5 (8%) | 1 (2%) |
| Q5_contested | 57 | 8 (14%) | 3 (5%) |
| live (this run) | 51 | 17 (33%) | 4 (8%) |

The live-run report is 33% hedged sentences and 8% committal — a 4:1 hedge:commit ratio. But the issue isn't density — it's *placement*. Q1's "Established consensus" sentences read as flat assertions (`"Empirical studies demonstrate that real-time trust scoring... significantly mitigates"`) while the Limitations are vague (`"the reliance on self-reported industry metrics introduces potential bias"`). A peer-reviewed synthesis does the opposite: hedge the consensus claims (because synthesis across 4 sources is inherently uncertain) and commit clearly to limitations (because limitations are author-known facts about their own method). The current writer prompt explicitly instructs `"Be concise and assertive"` (OPTIMIST_PROMPT) and rewards committal language in Consensus sections, which propagates wrong-direction confidence into the final report.

**Improvement (surgical):** Replace WRITER_PROMPT's `**Established consensus**` rules with: "State each consensus claim with epistemic markers tied to source count: `Strongly supported (≥3 sources)`, `Moderately supported (2 sources)`, `Single-source claim (1 source)`. Do NOT use bare assertive language for any claim with <3 sources."

### Finding 1.4 — "Active debates" sections paraphrase a single voice rather than presenting opposing positions. **[MAJOR — architectural]**
Q1 Debate #1 reads `"Sudhir et al. (2025) argue that intervention budgets are cost-effective... However, S7 and S3 counter that real-time trust scoring... prevents cascading failures"`. The writer constructed both positions because the prompt requires it, but the underlying source pool doesn't actually contain a Sudhir-vs-S7 debate — both are LLM-generated paraphrases of overlapping themes. Q5 does better here (the "model homogeneity vs adversarial prompts" debate genuinely cites different papers with different framings, see Q5 debate #1), but this is luck-of-the-source-pool, not a structural guarantee. The Optimist agent's prompt says `"Acknowledge the counter-evidence briefly and explain why it does not undermine the core finding"` — i.e., the Optimist is instructed to dismiss counter-evidence, not engage with it. The Skeptic's prompt says to "stress-test the Optimist" but does NOT require the Skeptic to take an opposing substantive position; it just requires methodological complaints. The result is the canonical multi-agent failure mode: two agents agreeing on the topic and disagreeing only on rigor.

**Improvement (architectural):** Replace OPTIMIST_PROMPT and SKEPTIC_PROMPT with a "claim-level" debate. The Research Manager picks ONE specific empirical claim from the registered sources (e.g., "Trust scoring reduces alignment errors by ≥20%"). Optimist defends with cited evidence. Skeptic attacks with cited counter-evidence OR explicitly claims the evidence is insufficient. RM judges per-claim, not per-synthesis. This is what TauricResearch/TradingAgents actually does (BULL claims AAPL goes UP citing P/E ratios, BEAR claims AAPL goes DOWN citing inventory glut) — current Optimist/Skeptic shares no such commitment.

### Finding 1.5 — The Methodological Notes section is gestures, not grading. **[MAJOR — surgical]**
Q1's full methodological note: `"The source base includes peer-reviewed papers (S3, S5, S7) and industry reports (S6, S2), with S1 and S4 lacking sufficient empirical detail."` But S3 (`https://arxiv.org/html/2508.13815v1` — COCO) is an arXiv preprint, not peer-reviewed. S5 (`https://www.cise.ufl.edu/~eragan/papers/Hashky_CSUR_2026.pdf`) is a CSUR submission. S7 (`https://arxiv.org/html/2603.26221v1` — `Clawed and Dangerous`) is an arXiv preprint with a 2603-prefixed identifier (which would be 2026 and is highly suspicious — arXiv IDs encode year as YYMM, so `2603.26221` would be from March 2026, but assignment runs in 2026 May; it's plausible but unverified). The writer asserts peer-review status without checking. Methodological notes that miscategorize sources are worse than no notes — they launder credibility.

**Improvement (surgical):** WRITER_PROMPT should require Methodological notes to grade each source explicitly: `"For each cited source, state: type [peer-reviewed / preprint / industry blog / press release / unknown], year, and confidence in attribution. Do NOT call a source peer-reviewed unless its venue field matches a known venue list (CHI, CSCW, NeurIPS, ICML, JMLR, TOCHI, etc.)."` Pair with `_format_writer_input()` injecting a venue→tier table.

### What's missing to hit Elicit / Consensus / SciSpace tier
| Capability | Current system | Elicit/Consensus tier | Why it matters |
|---|---|---|---|
| Per-claim source attribution | One `[S#]` per sentence, often decorative | Each claim → list of supporting AND opposing papers with effect sizes | Lets reader audit |
| Cross-paper extraction | Not done; only "key_claim" snippet (300-char abstract excerpt) | PICO / outcome / sample-size extraction across all papers | Real synthesis |
| Disagreement matrix | Active Debates is prose paraphrase | Tabular: claim × paper × {agree, disagree, mixed, n/a} | Forces honest contestation |
| Citation-quality filter | None — Forbes Tech Council, blog posts kept alongside arXiv | Whitelist + tier (peer-reviewed > preprint > blog) | Prevents Q1's "2024 CHI paper" being a blog post |
| Quantitative aggregation | Hand-waved percentages, none verifiable | Forest plot or weighted mean of effect sizes when ≥3 papers report comparable metric | Quantitative claims are credible |
| Refusal-of-shallow-output | Always produces 8 sections, even when 4 sources exist | Returns "insufficient evidence" verdict if N_sources < threshold | Honest scope |

---

## 2. Agent Prompts (`src/agents/autogen_agents.py`)

### Finding 2.1 — Planner has no diversity constraint; 5-7 sub-questions can be 5-7 paraphrases. **[MAJOR — surgical]**
PLANNER_PROMPT (line 114-133) says: `"Generate 5–7 sub-questions that together fully cover the query. Each question should be independently searchable."` There is no enforcement of orthogonality, mode diversity (definitional vs empirical vs methodological vs adversarial), or stakeholder diversity. Q1's actual planner output produced 6 sub-questions of which 3 (#1, #2, #5) are all variations of "what modalities reduce alignment failures empirically" — substantively the same question with different prepositional framings. This means web/academic/counter agents fetch overlapping results for #1, #2, #5, inflating raw source count without inflating evidence diversity.

**Improvement (surgical):** Append to PLANNER_PROMPT: `"Sub-questions MUST cover at least 3 distinct angles: (a) definitional/conceptual, (b) empirical/quantitative, (c) methodological/critical, (d) adversarial/failure-case, (e) cross-domain transfer. Tag each sub-question with its angle in a 'angle' field. Reject your own first draft if any two sub-questions share an angle and target the same construct."`

### Finding 2.2 — Researcher prompts say "filter to relevant" but do not specify claim-type extraction. **[MAJOR — surgical]**
WEB_RESEARCHER_PROMPT (139-149) and ACADEMIC_RESEARCHER_PROMPT (151-165) ask for "1-3 key claim bullets extracted from the snippet" — but the registered key_claims I sampled are literal title+snippet artifacts, not claim extraction. Examples I quoted in v1 of this audit and verified again here:
- `[Q1 S6] "| Protocol | Oversight Mechanism | Main Guarantee |` — that's a markdown table cell, not a claim
- `[Q1 S9] "Article\nGoogle Scholar"` — that's literal page chrome
- `[Q1 S7] "Refer to caption\n\n### 3.2. Our Constructed Corpus"` — that's an arXiv HTML rendering artifact
- `[Q5 S8] "The system parses all 1,759 DDR XML files... drilling data spanning..."` — Q5 is about multi-agent argumentation, this is OFF-TOPIC oil/gas drilling content; the URL `arxiv.org/list/cs/new` is an arXiv "new submissions" feed which returns whatever is recent

Researchers are passing through whatever the orchestrator hands them without doing the "key claim extraction" their prompt advertises. They're acting as pass-through filters, not synthesizers.

**Improvement (surgical):** Add to researcher prompts a NEGATIVE example: `"Do NOT register sources whose key_claim contains: page chrome ('Google Scholar', 'Refer to caption', 'Article'), table cells (lines starting and ending with '|'), or content not topically aligned with the sub-question. If the snippet is unintelligible, drop the source rather than register it."` Then enforce by orchestrator-side: drop any source whose key_claim contains those markers.

### Finding 2.3 — Counter-Evidence Hunter is a keyword-stuffed re-search, not adversarial. **[MAJOR — architectural]**
The orchestrator's `_fetch_counter` (autogen_orchestrator.py:275-300) appends `" limitations criticism failure cases skeptical view"` to the original query — that's a Tavily search-term modifier, not adversarial sampling. Q1's actual counter_evidence agent output produced **ONE** finding (S8 — "Trust and AI in IT Management") despite COUNTER_EVIDENCE_PROMPT requiring `"If you have fewer than 2 usable counter-evidence findings, say so explicitly"`. The agent did not even acknowledge the floor; it just stopped after one. There's no enforcement.

A real adversarial counter-evidence agent would: invert the *thesis* of the question (not append keywords); search for retraction notices, replication failures, and meta-analyses with negative results; check whether cited papers have been criticized in subsequent literature. The current implementation is "search Google for 'X criticism'", which is shallow.

**Improvement (architectural):** Two changes. (1) Generate the counter-thesis at planning time: e.g., for Q1 ("does HITL oversight reduce failures"), generate "HITL oversight does NOT reduce failures and here is why" and use THAT as the counter-evidence query. (2) Cross-check: after Stage 2, run the consensus claims through a "find a paper that contradicts this specific claim" pass. If counter-evidence cannot find any contradicting paper for a claim, mark that claim "uncontested in our search" rather than "consensus".

### Finding 2.4 — Optimist and Skeptic ARE contrastive (Q5 evidence good), but Optimist is instructed to dismiss counter-evidence. **[MAJOR — surgical]**
I read both Q1 and Q5 R1 debate transcripts. The Skeptic does push back substantively (Q5 Skeptic: `"S2 and S5 both critique structured debate's vulnerability to adversarial inputs and consensus bias, yet the Optimist claims it is the most 'characterized' protocol. This undermines the claim of robustness."`). But OPTIMIST_PROMPT explicitly says: `"Acknowledge the counter-evidence briefly and explain why it does not undermine the core finding"` (line 193) — the Optimist is asked to defend a predetermined position, not to make the strongest defensible claim given evidence. This is the source of finding 1.4 — the Optimist's defensiveness propagates into the writer's debate paraphrasing.

**Improvement (surgical):** Replace OPTIMIST_PROMPT's directive with: `"Make the strongest claim that the evidence supports — not the strongest possible claim. If counter-evidence is substantive, weaken the claim accordingly. The Optimist's job is to defend the BEST-EVIDENCE-SUPPORTED position, not to defend an arbitrary position. If you find yourself dismissing counter-evidence, the claim should be weakened."`

### Finding 2.5 — Research Manager's verdict is permissive in practice; NEEDS_MORE only fires for "more sources" not "wrong direction". **[MAJOR — architectural]**
Across my 8-session sample, **debate_rounds=2 in 8/8 sessions** (mean 2.00) — so RM issues NEEDS_MORE on round 1 every time. That looks like a thoughtful adjudicator, but reading both Q1 and Q5 RM round-1 verdicts, both reduce to "we need more sources for sub-question N" (Q1: `"sub-question 1 needs more evidence on failure modes"`; Q5: `"Sub-question 1 needs more evidence on all three protocols"`). The RM never says "the Optimist's framing is wrong, redirect" or "this evidence base is too thin to publish, refuse". The verdict criterion is `if any sub-question has <2 sources -> NEEDS_MORE`, which is a coverage check, not a synthesis check. The RM is permissive in the dimension that matters (synthesis quality) and demanding in the dimension that is easy to satisfy (more API calls).

This also explains the suspicious `revisions: mean=0.75` (6/8 sessions had 1 editor revise + 0 sessions had 0 revisions across both editor and guardrail — so revisions happen but only mechanically). The write→edit→guardrail loop is firing exactly once per run, suggesting the editor and guardrail are also both rubber-stamping after a token nudge.

**Improvement (architectural):** RESEARCH_MANAGER_PROMPT should issue a third verdict: `VERDICT: REFUSE_INSUFFICIENT_EVIDENCE` when fewer than X relevant sources exist OR when Skeptic's critique materially undermines the Optimist's core thesis without rebuttal. Currently the RM only votes APPROVED or NEEDS_MORE; neither acknowledges "the question cannot be answered with current evidence and we should say so".

### Finding 2.6 — WRITER_PROMPT's enforcement is ALL hope and no check. **[CRITICAL — half-surgical, half-architectural]**
WRITER_PROMPT (231-296) says "(CRITICAL — output guardrail will REJECT violations)" before the citation rules. But:
- The two-source rule (`"claims labeled as 'consensus' MUST have ≥2 distinct source citations"`) is never enforced by output_guardrail.py — see Q1 Consensus para 2 and 3, both of which violate this rule and pass.
- The 800-word minimum (`"Minimum 800 words. Target 1000-1400 words"`) is never checked. Q1 = 7,457 chars ≈ 1,100 words ✓; Q5 = 8,863 chars ≈ 1,400 words ✓. By coincidence these pass, but a degraded run could fall below 800 silently.
- The "single-source claims must be marked `(single source: [S\d+])`" rule appears nowhere in any output report I read.
- The "direct quotes (≤15 words) are strongly encouraged" produces zero quoted material in Q1, Q5, or live (zero `"..."` quote-marked spans appear in body text — verifiable by `grep '"[^"]*"' outputs/sessions/Q1_normal.json` returns only metadata strings).

So the writer prompt promises enforcement that doesn't exist and the writer simply ignores the rules whose enforcement is fictional.

**Improvement (mixed):** (Surgical) Add to `output_guardrail.py` a new check that splits report into Consensus paragraphs (matched by `**\d+\..*\*\*` headers under `## Established consensus`) and counts unique `[S#]` per paragraph; if <2, flag with `action="revise"`. Also count words and flag if <800. (Architectural) The general lesson: stop telling the model the guardrail enforces things the guardrail doesn't enforce — that pattern teaches the model to ignore the guardrail's actual restrictions too.

### Finding 2.7 — Editor false-negative rate is high; my probe = 100%. **[MAJOR — surgical]**
The Editor's job is to catch what the Writer missed. Q1's Editor Pass #1 said `"Missing citations in the Background and Definitions section"` — fair catch. Pass #2 said `"APPROVED"`. Pass #3 (after guardrail revise) said `"APPROVED"`. But the approved Q1 report:
- Cites `"Sudhir et al. (2025)"` and `"Zhang"` and `"a 2024 CHI paper"` and `"a 2025 NeurIPS study"` — none verifiable from registered sources (finding 1.2)
- Has 1-citation paragraphs in Established Consensus violating Writer prompt's two-source rule (finding 1.4 in v1 audit)
- Uses zero direct quotes despite WRITER_PROMPT's "strongly encouraged"
- Methodological notes mislabel arXiv preprints as peer-reviewed (finding 1.5)

The Editor is checking the cosmetic surface (`"every factual claim carries at least one [S#] citation"`) — which is structurally easy because the writer puts `[S#]` at the end of every sentence — and missing the substantive defects. EDITOR_PROMPT (298-315) doesn't list "verify claims against source key_claims" or "verify Author-Year attributions exist in source.authors" because the editor doesn't have machine-checkable access to that data — it's another LLM in the same context window relying on its own attention.

**Improvement (surgical):** Add to EDITOR_PROMPT a list of 5-6 specific things to check that the writer prompt promises but the guardrail doesn't enforce. Specifically: `"Verify every numerical effect size (\d+%) in the draft appears in at least one cited source's key_claim. Verify every Author-Year attribution (e.g., 'Smith et al. (2025)') has the named author appearing in registry[cited_id].authors. Verify every paragraph under '## Established consensus' has ≥2 distinct [S#] citations. Verify the report is ≥800 words. List any violations explicitly in the REVISE message."`

---

## 3. Workload Depth — Does It Earn "Deep Research"?

### Finding 3.1 — 90 sources is fictional; mean is 9.1, range [4, 13]. **[CRITICAL — challenges the "deep research" framing]**
Across the 8-session sample (Q1, Q5, 6 live runs), `num_sources` distribution: `[10, 9, 13, 8, 11, 12, 4, 6]`, mean = 9.1, max = 13. The "90 sources gathered per run sounds impressive" hypothesis is wrong — by an order of magnitude. The orchestrator's per_q values (`web=6, acad=8, counter=4`) × ~5 sub-questions × 3 fetch types theoretically = 90 raw results, but Tavily/Semantic Scholar return fewer (often 0 from S2), the dedup-by-URL in SourceRegistry collapses overlapping results, and many results lack URLs and get dropped. So the actual evidence base per report is **roughly 10 sources**, often 4. A deep-research engine claim built on ~10 sources is closer to a structured Google search.

The live run I observed in v1 had 21 registered sources but the writer cited only 4 of them (S2, S3, S4, S10) due to top-10 truncation in `_format_writer_input()` plus writer choosing only a subset. Effective evidence base for that synthesis: 4 sources.

**Improvement (surgical for the per_q values; architectural for the depth claim):** Either commit to actually deep — bump per_q to (10, 12, 8) and add a second-pass query rewrite for sub-questions returning <3 sources — or honestly downgrade the framing from "deep research" to "fast literature triage". An academic-engine-grade artifact built on 10 sources is a literature scan, not a synthesis.

### Finding 3.2 — Debate rounds always = 2; revisions mostly = 1; loops are rubber-stamps. **[CRITICAL — architectural]**
| Counter | Range | Interpretation |
|---|---|---|
| `debate_rounds` | 2 in 8/8 sessions | RM never APPROVES on round 1 — but also never EXTENDS beyond 2 because the orchestrator caps at 2 (autogen_orchestrator.py:402 `for debate_iter in range(2)`). The "decision" is determined by the cap, not the evidence. |
| `revisions` | 0 in 2/8, 1 in 6/8 | Editor + guardrail each fire once when they fire, then APPROVE. No session triggered ≥2 revisions. |
| `total_duration` | mean 313s | 5 minutes per query, mostly waiting on Qwen latency, not iterating. |

This means the "iterative refinement" claim in the technical_report.md abstract is more like "one ceremonial round of revision then ship". A genuinely iterative system would show variance: some queries triggering 1 revision, some 3, some 0. The flat distribution shows the agents are all playing their script roles, not responding to actual quality signal.

**Improvement (architectural):** Make debate iterations dynamic. RM's verdict criterion should compare round-N synthesis to round-(N-1) — if marginal information added by round N is below threshold, terminate; otherwise continue up to a higher cap (e.g., 4). This is what `evaluator-optimizer` pattern from Anthropic's "Building effective agents" actually means.

### Finding 3.3 — Source domain diversity is shallow. **[MAJOR — surgical]**
Q1's 10 sources span 6 domains: `arxiv.org` (×2), `emergentmind.com` (×2), and one each from `rsisinternational.org`, `systima.ai`, `cise.ufl.edu`, `openreview.net`. Q5's 9 sources: `arxiv.org` (×3), `emergentmind.com` (×3), and one each from `huggingface.co`, `themoonlight.io`, `congress.aesop-planning.eu`. **Two of the top three domains are blog/SEO content sites** (`emergentmind.com` is an AI-content-summary aggregator, `themoonlight.io` is a "moonlit" literature-review-summary site). The "academic" researcher fetched arXiv preprints which is fine; the "web" and "counter" researchers are pulling from low-tier aggregators that themselves summarize papers — i.e., the system is doing 4th-hand synthesis (Qwen summarizes a blog summary of a paper summary).

**Improvement (surgical):** Add to `web_search_structured()` a domain-tier filter: `tier_1 = {arxiv.org, openreview.net, *.edu, ieeexplore.ieee.org, dl.acm.org}`; `tier_2 = {forbes.com, techcrunch.com, ...}`; `tier_3 = {emergentmind.com, themoonlight.io, ...}`. Sort results to prefer tier_1, drop tier_3 unless count <3. Currently any URL is treated equally.

### Finding 3.4 — Counter-Evidence agent only contributed 1 source for Q1 — ignored its own ≥2 floor. **[MAJOR — surgical]**
COUNTER_EVIDENCE_PROMPT (line 167-181): `"If you have fewer than 2 usable counter-evidence findings, say so explicitly."` Q1's counter_evidence agent output (verified): produced **one** finding (S8) and ended with `RESEARCH COMPLETE` without acknowledging the floor. So 1/9 agents (11%) silently ignored an explicit prompt instruction. There is zero verification that this happened. This is the structural-vs-architectural split: the prompt asked, the model declined, and there's no checker.

If 1/9 agents per run silently violates instructions, after 9 runs the expected violation count is ~1 per run — and these accumulate downstream because subsequent agents trust their inputs.

**Improvement (surgical):** Orchestrator-side check after Stage 2 — if counter_evidence output contains <2 `### Source:` blocks AND does NOT contain the phrase "fewer than 2 usable", re-prompt with the violation explicitly stated. `_extract_sources_from_research_output()` already counts blocks; trivial to add this check.

### Finding 3.5 — Comparison to TauricResearch/TradingAgents (the cited inspiration). **[CRITICAL — architectural]**
The technical report claims `"the Stage 3 structure directly mirrors the TauricResearch/TradingAgents bull/bear debate"`. In TradingAgents, BULL takes a position (`AAPL goes UP`) citing specific evidence (P/E ratio, supplier growth, iPhone unit sales). BEAR takes the OPPOSITE position (`AAPL goes DOWN`) citing different specific evidence (China revenue contraction, services growth slowdown). Risk Manager weighs the trade.

In our system, OPTIMIST_PROMPT says `"build the strongest case for an emerging consensus answer"`. SKEPTIC_PROMPT says `"identify under-cited claims and surface contradictions"`. **Neither agent commits to a specific stance on a specific claim.** Optimist says "the evidence supports HITL oversight reducing failures, modulo domain specifics". Skeptic says "but the evidence is weak in several spots". They're not in opposition; they're in an editor/author relationship. A faithful mirror of TradingAgents would have OPTIMIST claim `"the evidence supports HITL reducing alignment failures by ≥X%"` and SKEPTIC claim `"the evidence supports HITL having NO measurable effect on alignment failures"` — same evidence, opposite conclusions, RM picks. The current design is bull/editor, not bull/bear.

**Improvement (architectural):** Restructure Stage 3 to require Optimist and Skeptic to STAKE OPPOSING POSITIONS on a specific claim selected by the Research Manager from the Stage-2 evidence. This is the structural change that would make the multi-agent ceremony earn its name.

---

## What This System Is Currently 1-Tier-Below

**Current tier: TIER-3 (Glorified Summary).** The system is a structured prompt-chain that produces a templated 8-section report from ~10 web/academic snippets, with one round of cosmetic revision. The multi-agent scaffolding is real (9 agents, 4 stages, parallel asyncio.gather, debate loop, editor loop, guardrail loop) but the agents are all playing scripted roles rather than substantively disagreeing or extracting orthogonal evidence. The output is academically-structured, citation-decorated text whose specific quantitative claims are hallucinated and whose "active debates" are paraphrases of one voice.

**One tier up: TIER-2 (Mid-Tier Aggregator)** — comparable to AI literature-review tools like Elicit (semanticscholar.org-backed extraction), Consensus.app (per-paper claim extraction), SciSpace (source-quality tiering). What separates ours from theirs: (1) those systems do per-paper *extraction* (PICO, outcome, sample size) rather than per-paper *snippet display*; (2) those systems show a disagreement matrix rather than prose paraphrase of debates; (3) those systems refuse to synthesize when N_papers is below threshold rather than always producing 8 sections; (4) those systems have hand-curated source-quality tiers (peer-reviewed-only mode); (5) those systems verify quantitative claims against the source PDF rather than allowing free hallucination of effect sizes.

**Two tiers up: TIER-1 (Research-Grade Synthesis)** — comparable to systems like Galactica's (deprecated but illustrative) abstract-driven generation, or domain-specific tools like Research Rabbit + manual verification. To reach this tier requires: (1) PDF retrieval and full-text claim extraction (not snippets); (2) genuine adversarial agents staking opposite positions on specific claims; (3) provenance verification at the claim level (every numerical claim traceable to a verbatim substring in source full-text); (4) refusal to synthesize when evidence pool is below N=20 quality-tier-1 sources; (5) human-in-the-loop validation on the 5 most-cited claims before publication.

The IS492 Assignment 3 deliverable does not need to hit TIER-1 for academic credit — TIER-3 with honest framing would be perfectly defensible as "we built a multi-agent literature scanner with structured output, here are its limitations". The current framing ("academic-engine-grade", "Provenance verifier as a structural antibody", "multi-judge triangulation") aspires to TIER-1 while delivering TIER-3, which is the credibility gap a peer reviewer would penalize.

---

## Top 5 highest-leverage fixes (ordered by tier-impact / effort ratio)

1. **Add quantitative-claim and Author-Year provenance check to `output_guardrail.py`.** Surgical (~30 lines). Single highest-impact fix because it makes finding 1.2 (hallucinated 37%, 28%, 22%) impossible. After this, the system stops looking like a confident liar.
2. **Make the report structure conditional on evidence depth.** Surgical (~20 lines in WRITER_PROMPT + post-check). If <2 contested points: drop "Active debates". If <3 consensus claims with ≥2 sources: drop "Established consensus" and emit "Tentative findings". Stops the system from manufacturing controversies.
3. **Force OPTIMIST and SKEPTIC to stake opposing positions on a RM-selected claim.** Architectural (~50-line prompt rewrite). This is the change that turns ceremony into actual debate — fixes findings 1.4, 2.4, 3.5 simultaneously.
4. **Add domain-tier filter and prefer tier-1 sources.** Surgical (~20 lines in `web_search.py`). Stops emergentmind.com being 20% of the evidence base.
5. **Replace `revisions += 1` with a marginal-information criterion in the debate loop.** Architectural (~30 lines in orchestrator). Lets some queries terminate after 1 round and others run to 4. Variance in iteration count is the signal that the loop is doing real work.

