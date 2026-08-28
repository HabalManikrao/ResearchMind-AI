"""R&D Report generation (spec §13).

The LLM writes the narrative sections (executive summary, analysis, comparison,
recommendation, roadmap) strictly from the verified evidence. The Sources list and
Research Confidence block are assembled deterministically from stored data so they
are always accurate and traceable (spec rules §23.2, §23.9).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.llm.base import AIProvider
from app.models.enums import ClaimStatus

_SYSTEM = (
    "You are an R&D analyst writing an evidence-based research report. Use ONLY the "
    "provided findings and verified claims. Never invent facts or sources. Clearly "
    "state uncertainty. Write in clean Markdown. Make recommendations traceable to "
    "the evidence. Do not fabricate a Sources section — it is appended separately."
)

# The LLM writes only the interpretive prose. Comparison, Recommendation, Why,
# Alternatives, Risks, PoC, Roadmap, and Conflicting Information are injected
# deterministically from structured R&D/conflict data so recommendations stay
# traceable to evidence and conflicts can't be hidden (spec rules §23.2, §23.10).
_SECTIONS = (
    "Write these sections as Markdown (## headings), and ONLY these:\n"
    "## Executive Summary\n## Key Findings\n## Detailed Analysis\n## Knowledge Gaps\n"
    "Do not write a recommendation, comparison, roadmap, or sources section — those "
    "are added separately."
)

_MARKET_SECTIONS = (
    "Write these sections as Markdown (## headings), and ONLY these:\n"
    "## Market Snapshot\n## Current State & Key Players\n## Recent Developments\n"
    "## Trends & Outlook\n## Knowledge Gaps\n"
    "Do not write a recommendation, comparison, roadmap, or sources section — those "
    "are added separately."
)

# Extra grounding rules for Market Intelligence mode. The whole point is a picture
# of the CURRENT market, so the model must not fall back on stale training data.
_MARKET_SYSTEM_EXTRA = (
    " This is a CURRENT-MARKET report. Report only what the provided (recent) sources "
    "support — do NOT rely on prior knowledge. Attribute time-sensitive claims to when "
    "their source was published. If the sources don't establish the current state of "
    "something, say so explicitly rather than guessing."
)


@dataclass
class ReportInput:
    objective: str
    query: str
    questions: list[str]
    findings: list[str]
    claims: list[dict]  # {text, status, confidence}
    sources: list[dict]  # {title, url, source_type, reliability_score, published_date}
    conflicts: list[dict] = field(default_factory=list)  # {statement_a, statement_b, explanation, severity}
    solutions: list[dict] = field(default_factory=list)  # comparison options
    recommendation: dict | None = None  # structured R&D recommendation
    mode: str = ""  # ResearchMode value; "market" switches to the market layout
    as_of: str | None = None  # snapshot date for Market Intelligence mode


async def generate_report(provider: AIProvider, data: ReportInput) -> tuple[str, dict]:
    is_market = data.mode == "market"
    verified = [c for c in data.claims if c["status"] == ClaimStatus.VERIFIED.value]

    claims_block = "\n".join(
        f"- [{c['status']}] ({c['confidence']}%) {c['text']}" for c in data.claims
    ) or "(no claims consolidated)"
    findings_block = "\n".join(f"- {f}" for f in data.findings[:60]) or "(none)"

    date_line = f"Today's date is {data.as_of}.\n" if (is_market and data.as_of) else ""
    prompt = (
        f"Research objective: {data.objective}\n"
        f"Original request: {data.query}\n{date_line}\n"
        f"Research questions:\n" + "\n".join(f"- {q}" for q in data.questions) + "\n\n"
        f"Verified & other claims:\n{claims_block}\n\n"
        f"Findings:\n{findings_block}\n\n"
        f"{_MARKET_SECTIONS if is_market else _SECTIONS}"
    )
    system = _SYSTEM + (_MARKET_SYSTEM_EXTRA if is_market else "")
    narrative = await provider.generate(prompt, system=system)

    report_md = _assemble(data, narrative)
    meta = _confidence_meta(
        data, verified_count=len(verified), conflicted_count=len(data.conflicts)
    )
    return report_md, meta


def _assemble(data: ReportInput, narrative: str) -> str:
    is_market = data.mode == "market"
    title = "Market Intelligence Report" if is_market else "Research Report"
    header = f"# {title}: {data.objective}\n\n"
    if is_market and data.as_of:
        header += f"_Market snapshot as of {data.as_of}. Reflects sources available at that time._\n\n"
    header += "## Research Objective\n" + data.objective + "\n\n"
    header += "## Research Questions\n"
    header += "\n".join(f"{i+1}. {q}" for i, q in enumerate(data.questions)) + "\n\n"

    conflicts_md = "\n## Conflicting Information\n\n"
    if data.conflicts:
        conflicts_md += (
            "The following contradictions were detected and remain unresolved; "
            "weigh them when acting on the recommendation.\n\n"
        )
        for c in data.conflicts:
            conflicts_md += (
                f"- **[{c.get('severity', 'medium')}]** {c['statement_a']} "
                f"**vs.** {c['statement_b']}\n"
                f"  - {c.get('explanation', '')}\n"
            )
    else:
        conflicts_md += "_No contradictions were detected across sources._\n"

    sources_md = "\n## Sources\n\n"
    if data.sources:
        sources_md += "| # | Title | Type | Reliability | Date | URL |\n"
        sources_md += "|---|-------|------|-------------|------|-----|\n"
        for i, s in enumerate(data.sources, 1):
            title = (s["title"] or "Untitled").replace("|", "\\|")[:80]
            sources_md += (
                f"| {i} | {title} | {s['source_type']} | "
                f"{s['reliability_score']} | {s.get('published_date') or '—'} | "
                f"{s['url']} |\n"
            )
    else:
        sources_md += "_No sources collected._\n"

    conf = _confidence_meta(
        data,
        verified_count=sum(1 for c in data.claims if c["status"] == ClaimStatus.VERIFIED.value),
        conflicted_count=len(data.conflicts),
    )
    breakdown = conf["source_breakdown"]
    breakdown_md = "".join(
        f"  - {_TYPE_LABELS.get(k, k)}: {v}\n" for k, v in breakdown.items() if v
    )
    conf_md = (
        "\n## Research Confidence\n\n"
        f"- **Overall Confidence:** {conf['overall_confidence']}%\n"
        f"- **Sources Analyzed:** {conf['sources_analyzed']}\n"
        f"{breakdown_md}"
        f"- **Verified Claims:** {conf['verified_claims']}\n"
        f"- **Conflicted Claims:** {conf['conflicted_claims']}\n"
        f"- **Total Claims:** {conf['total_claims']}\n"
    )
    return (
        header
        + narrative.strip()
        + "\n"
        + _rd_md(data)
        + conflicts_md
        + sources_md
        + conf_md
    )


def _rd_md(data: ReportInput) -> str:
    """Deterministic Comparison / Recommendation / Roadmap sections from structured
    R&D data. Nothing here is model-generated prose, so it stays evidence-traceable."""
    md = ""

    # Solution comparison table.
    if data.solutions:
        criteria: list[str] = []
        for s in data.solutions:
            for sc in s.get("scores", []):
                c = sc.get("criterion")
                if c and c not in criteria:
                    criteria.append(c)
        md += "\n## Technology / Solution Comparison\n\n"
        header_cells = ["Option", *criteria, "Key Pros", "Key Cons"]
        md += "| " + " | ".join(header_cells) + " |\n"
        md += "|" + "|".join(["---"] * len(header_cells)) + "|\n"
        for s in data.solutions:
            score_map = {sc.get("criterion"): sc.get("rating", "—") for sc in s.get("scores", [])}
            name = s["name"] + (" ⭐" if s.get("is_recommended") else "")
            row = [name.replace("|", "\\|")]
            row += [str(score_map.get(c, "—")).replace("|", "\\|") for c in criteria]
            row.append(("; ".join(s.get("pros", [])[:2]) or "—").replace("|", "\\|"))
            row.append(("; ".join(s.get("cons", [])[:2]) or "—").replace("|", "\\|"))
            md += "| " + " | ".join(row) + " |\n"

    rec = data.recommendation
    if rec and rec.get("recommended_option"):
        md += "\n## Recommended Solution\n\n"
        md += f"**{rec['recommended_option']}** — {rec.get('rationale', '')}\n"
        md += f"\n_Recommendation confidence: {round(rec.get('confidence', 0))}%_\n"
        if rec.get("why"):
            md += "\n## Why This Recommendation\n\n" + rec["why"] + "\n"
        if rec.get("alternatives"):
            md += "\n## Alternative Solutions\n\n"
            md += "".join(f"- {a}\n" for a in rec["alternatives"])
        if rec.get("risks"):
            md += "\n## Risks\n\n"
            md += "".join(f"- {r}\n" for r in rec["risks"])
        if rec.get("proof_of_concept"):
            md += "\n## Proof of Concept\n\n" + rec["proof_of_concept"] + "\n"
        if rec.get("roadmap"):
            md += "\n## Implementation Roadmap\n\n"
            for i, step in enumerate(rec["roadmap"], 1):
                detail = f" — {step['detail']}" if step.get("detail") else ""
                md += f"{i}. **{step.get('step', '')}**{detail}\n"
    return md


_TYPE_LABELS = {
    "web": "Web",
    "docs": "Official Docs",
    "github": "GitHub",
    "papers": "Research Papers",
    "news": "News",
    "community": "Community",
}


def _confidence_meta(data: ReportInput, *, verified_count: int, conflicted_count: int) -> dict:
    total_claims = len(data.claims)
    avg_conf = (
        round(sum(c["confidence"] for c in data.claims) / total_claims, 1)
        if total_claims
        else 0.0
    )
    breakdown: dict[str, int] = {}
    for s in data.sources:
        breakdown[s["source_type"]] = breakdown.get(s["source_type"], 0) + 1
    return {
        "overall_confidence": avg_conf,
        "sources_analyzed": len(data.sources),
        "source_breakdown": breakdown,
        "verified_claims": verified_count,
        "conflicted_claims": conflicted_count,
        "total_claims": total_claims,
    }
