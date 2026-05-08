"""
Output guardrail — post-Writer safety + ★ Provenance verifier.

Created: 2026-05-07
Last reused or audited: 2026-05-08 (Path C Fix 1: added _check_quantitative_claims —
verifies numerical effect sizes (\\d+%) and Author-Year attributions appear in cited
source's key_claim/authors. Previous verifier only checked [Sn] presence, not content.)
Authority basis: Plan §Guardrails category 4-5; critic_report_v2 finding 1.2.

PROVENANCE VERIFIER (★ bonus innovation):
Translates Fitz Constraint #4 ("data provenance > code correctness") from
Zeus's data layer to the LLM agent boundary. In Zeus, every datum carries
`source` and `authority`; data without authority does not enter the
computation chain. We apply the same principle to LLM output: every factual
claim must trace to a source registered by the researcher agents. Claims
without provenance are NOT permitted into the final answer, even if the LLM
"knows" them — the agent boundary is exactly where semantic context (citation
chain) is lost in normal RAG systems.

CITATION-CONTENT MATCH (Path C, 2026-05-08):
Surface-level "[Sn] is in the registry" check missed an entire class of
hallucinations: the writer cites a real source but invents the percentage
or author attribution. _check_quantitative_claims closes this loop by
extracting every \\d+% and "Author Year" pattern and verifying the cited
source's key_claim/authors actually contains the claimed value.

This is one of three antibodies (cf. Universal Methodology #3, immune system)
this module deploys against the LLM hallucination class.
"""
import re
from typing import Optional
from src.guardrails.safety_manager import SafetyEvent

# PII patterns (output check)
EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")
PHONE_PATTERN = re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")
SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
CC_PATTERN = re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b")

# Citation pattern
CITATION_PATTERN = re.compile(r"\[(S\d+)\]")

# Heuristic: sentences with these markers usually need citations
FACTUAL_CLAIM_MARKERS = [
    r"\b(?:study|studies|research|paper|report|analysis|survey|finding|findings)\s+(?:show|found|suggest|indicate|demonstrate|reveal|conclude)",
    r"\baccording to\b",
    r"\b\d{4}\b",  # year
    r"\b\d+(?:\.\d+)?\s*%\b",  # percentage
    r"\b(?:has|have|had)\s+been\s+(?:shown|demonstrated|found)",
    r"\b(?:researchers?|scientists?|experts?)\s+(?:argue|claim|propose|note)",
]


class OutputGuardrail:
    def __init__(self, config: dict):
        self.config = config
        # Informal sections where unsourced prose is acceptable
        self.allow_unsourced_in_sections = {
            "introduction", "open questions", "future work", "bottom line"
        }

    def validate(self, text: str, source_registry) -> tuple:
        """
        Returns (events, sanitized_text).
        - events: all guardrail violations
        - sanitized_text: cleaned version if any PII was redacted, else None
        """
        events = []
        sanitized = text

        # === PII check ===
        pii_findings = self._check_pii(text)
        if pii_findings:
            for kind, matches in pii_findings.items():
                events.append(SafetyEvent(
                    category="pii_leakage", severity="warning", action="sanitize",
                    message=f"Detected {kind} in output, redacted",
                    evidence={"kind": kind, "count": len(matches), "samples": matches[:3]}
                ))
            sanitized = self._redact_pii(sanitized)

        # === Provenance verifier (★ bonus) ===
        prov_event = self._check_provenance(sanitized, source_registry)
        if prov_event:
            events.append(prov_event)
        else:
            events.append(SafetyEvent(
                category="unsourced_claims", severity="info", action="pass",
                message="Provenance verifier: all citations valid",
                evidence={"cited_ids": list(set(CITATION_PATTERN.findall(sanitized)))}
            ))

        # === Quantitative-claim + Author-Year content match (Path C Fix 1) ===
        # Closes the citation-content gap: "[S3]" being in registry doesn't mean
        # the source actually contains the claimed "37%" or "Sudhir et al. 2025".
        qc_findings = self._check_quantitative_claims(sanitized, source_registry)
        if qc_findings:
            high_findings = [f for f in qc_findings if f.get("severity") == "high"]
            # Severity: high if any unsupported claim found
            severity = "block" if high_findings else "warning"
            action = "revise"  # always request revise for unsupported quant claims
            events.append(SafetyEvent(
                category="unsupported_quantitative_claim",
                severity=severity,
                action=action,
                message=(
                    f"Found {len(qc_findings)} unsupported numerical or author-year "
                    f"claim{'s' if len(qc_findings) != 1 else ''} in output "
                    f"(claim cites a real source ID, but source content does not contain claim)"
                ),
                evidence={
                    "count": len(qc_findings),
                    "findings_sample": qc_findings[:5],
                },
            ))

        return events, (sanitized if sanitized != text else None)

    def _check_pii(self, text: str) -> dict:
        out = {}
        e = EMAIL_PATTERN.findall(text)
        if e:
            out["email"] = e
        p = PHONE_PATTERN.findall(text)
        if p:
            out["phone"] = p
        s = SSN_PATTERN.findall(text)
        if s:
            out["ssn"] = s
        c = CC_PATTERN.findall(text)
        if c:
            out["credit_card"] = c
        return out

    def _redact_pii(self, text: str) -> str:
        text = EMAIL_PATTERN.sub("[REDACTED-EMAIL]", text)
        text = PHONE_PATTERN.sub("[REDACTED-PHONE]", text)
        text = SSN_PATTERN.sub("[REDACTED-SSN]", text)
        text = CC_PATTERN.sub("[REDACTED-CC]", text)
        return text

    def _check_provenance(self, text: str, source_registry) -> Optional[SafetyEvent]:
        """Core ★ bonus innovation. Returns SafetyEvent if violation, None if pass."""
        if source_registry is None:
            return None

        # 1. Find all [S\d+] cited in text
        cited_ids = set(CITATION_PATTERN.findall(text))
        registered_ids = set(source_registry.as_dict().keys())

        # 2. Are any cited IDs MISSING from registry? (hallucinated cites)
        missing = cited_ids - registered_ids
        if missing:
            return SafetyEvent(
                category="unsourced_claims", severity="block", action="revise",
                message=f"Writer cited {len(missing)} non-existent source IDs",
                evidence={"missing_ids": sorted(missing), "valid_ids": sorted(registered_ids)[:10]}
            )

        # 3. Are factual-claim sentences MISSING a citation?
        unsourced_claims = self._find_unsourced_factual_sentences(text)
        if unsourced_claims:
            return SafetyEvent(
                category="unsourced_claims", severity="warning", action="revise",
                message=f"Found {len(unsourced_claims)} factual-sounding sentences without [S\\d+] citation",
                evidence={"sentences_sample": unsourced_claims[:3], "count": len(unsourced_claims)}
            )

        return None

    def _check_quantitative_claims(self, text: str, source_registry) -> list:
        """Find numerical/quantitative claims (percentages, sample sizes,
        'Author Year' attributions) and verify they appear in the cited
        source's key_claim/authors. Returns a list of unverified-claim dicts:
        {claim, snippet, citation_id, severity}.

        Path C Fix 1 (2026-05-08): closes the citation-content gap. Existing
        provenance verifier checks "[Sn] is in registry"; this verifier checks
        "the cited source actually contains the claimed number/author".
        """
        findings: list = []
        if source_registry is None:
            return findings

        # Pattern A: percentage claims followed by [Sn] within 60 chars
        pct_pat = re.compile(r"(\b\d{1,3}(?:\.\d+)?%)\s*(?:[^\[]{0,60}?)?\[(S\d+)\]")
        # Pattern B: "Author et al. YYYY [Sn]" or "Author and Other YYYY [Sn]"
        cite_pat = re.compile(
            r"\b([A-Z][a-z]+(?:\s+et\s+al\.|\s+and\s+[A-Z][a-z]+)?)\s+"
            r"(?:\(|)\s*(\d{4})\s*(?:\)|)\s*(?:[^\[]{0,80}?)?\[(S\d+)\]"
        )

        try:
            sources = source_registry.as_dict() if source_registry else {}
        except Exception:
            sources = {}

        for m in pct_pat.finditer(text):
            pct, sid = m.group(1), m.group(2)
            snippet = text[max(0, m.start() - 30):min(len(text), m.end() + 30)]
            src = sources.get(sid, {})
            key_claim = (src.get("key_claim") or "").lower()
            # Strip the % so "37%" matches "37 percent" too
            pct_num = pct.rstrip("%").strip()
            if pct_num not in key_claim and pct.lower() not in key_claim:
                findings.append({
                    "category": "unsupported_quantitative_claim",
                    "claim": pct,
                    "snippet": snippet.strip(),
                    "citation_id": sid,
                    "severity": "high",
                })

        for m in cite_pat.finditer(text):
            author_raw, year, sid = m.group(1), m.group(2), m.group(3)
            snippet = text[max(0, m.start() - 20):min(len(text), m.end() + 20)]
            src = sources.get(sid, {})
            src_authors = src.get("authors") or []
            if isinstance(src_authors, list):
                src_authors_str = " ".join(str(a) for a in src_authors).lower()
            else:
                src_authors_str = str(src_authors).lower()
            # Extract surname only — drop "et al." / "and X" suffix for comparison.
            # Author regex captures "Sudhir et al." as one group, but registry stores
            # ["Sudhir", "Smith"]. Match surname against the joined author string.
            surname = author_raw.split()[0].rstrip(",.").lower() if author_raw else ""
            if surname and surname not in src_authors_str:
                findings.append({
                    "category": "unsupported_author_attribution",
                    "claim": f"{author_raw} {year}",
                    "snippet": snippet.strip(),
                    "citation_id": sid,
                    "severity": "high",
                    "expected_in": src_authors_str[:120] if src_authors_str else "(empty author list)",
                })

        return findings

    def _find_unsourced_factual_sentences(self, text: str) -> list:
        """Heuristic: sentences with factual-claim markers but no [S\\d+] in the same sentence."""
        sections = self._split_into_sections(text)
        bad = []
        for section_name, body in sections:
            if section_name.lower().strip() in self.allow_unsourced_in_sections:
                continue
            sentences = re.split(r"(?<=[.!?])\s+", body)
            for s in sentences:
                if not s.strip():
                    continue
                # Skip markdown headings and blockquotes — not factual prose
                if s.lstrip().startswith("#") or s.lstrip().startswith(">"):
                    continue
                has_marker = any(re.search(p, s, re.IGNORECASE) for p in FACTUAL_CLAIM_MARKERS)
                if not has_marker:
                    continue
                has_cite = bool(CITATION_PATTERN.search(s))
                if not has_cite:
                    bad.append(s.strip()[:200])
        return bad

    @staticmethod
    def _split_into_sections(text: str) -> list:
        """Split markdown by ## headers. Returns [(section_name, body), ...]."""
        parts = re.split(r"\n##\s+", "\n" + text)
        if len(parts) <= 1:
            return [("body", text)]
        result = []
        if parts[0].strip():
            result.append(("preamble", parts[0]))
        for p in parts[1:]:
            lines = p.split("\n", 1)
            name = lines[0].strip()
            body = lines[1] if len(lines) > 1 else ""
            result.append((name, body))
        return result
