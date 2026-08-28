import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// Mock the API client before importing the component under test. `vi.hoisted`
// lets the mock fn exist above the hoisted vi.mock factory.
const { claimEvidence } = vi.hoisted(() => ({ claimEvidence: vi.fn() }));
vi.mock("../api/client", () => ({ api: { claimEvidence } }));

import { ClaimsTab } from "./LiveResearch";
import type { Claim, ClaimEvidenceResponse } from "../api/types";

const claim: Claim = {
  id: "c1",
  text: "Podman is a drop-in replacement for Docker.",
  status: "verified",
  confidence: 88,
  supporting_source_ids: ["s1"],
  confidence_meta: {
    support_count: 2,
    contradiction_count: 1,
    avg_reliability: 84,
    freshness: "fresh",
    outdated: false,
    reasons: ["2 independent sources support this claim."],
  },
  evidence_state: "conflicting",
};

const evidenceResponse: ClaimEvidenceResponse = {
  claim,
  evidence: [
    {
      source_id: "s1",
      title: "architecture.pdf",
      url: "document://d1",
      source_type: "documents",
      publisher: null,
      published_date: null,
      reliability_score: 78,
      freshness: "unknown",
      stance: "supports",
      passage: "Podman provides a Docker-compatible CLI.",
      page_number: 17,
    },
    {
      source_id: "s2",
      title: "Migration pitfalls",
      url: "https://blog.example/pitfalls",
      source_type: "web",
      publisher: null,
      published_date: "2024-01-01",
      reliability_score: 55,
      freshness: "aging",
      stance: "contradicts",
      passage: "Rootless networking differs and breaks some compose setups.",
      page_number: null,
    },
  ],
};

describe("ClaimsTab", () => {
  beforeEach(() => {
    claimEvidence.mockReset();
    claimEvidence.mockResolvedValue(evidenceResponse);
  });

  it("shows the evidence-state badge and confidence without expanding", () => {
    render(<ClaimsTab claims={[claim]} projectId="p1" />);
    expect(screen.getByText("Conflicting evidence")).toBeInTheDocument();
    expect(screen.getByText("88%")).toBeInTheDocument();
    // Evidence is not fetched until the row is expanded.
    expect(claimEvidence).not.toHaveBeenCalled();
  });

  it("fetches and reveals supporting + contradicting passages on expand", async () => {
    const user = userEvent.setup();
    render(<ClaimsTab claims={[claim]} projectId="p1" />);

    await user.click(screen.getByText(/Podman is a drop-in replacement/));

    await waitFor(() => expect(claimEvidence).toHaveBeenCalledWith("p1", "c1"));
    expect(
      await screen.findByText(/Podman provides a Docker-compatible CLI/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Rootless networking differs/),
    ).toBeInTheDocument();
    // The "why this confidence" reasons are shown.
    expect(
      screen.getByText(/2 independent sources support this claim/),
    ).toBeInTheDocument();
    // Grouped headings reflect the stance split.
    expect(screen.getByText(/Supporting evidence \(1\)/)).toBeInTheDocument();
    expect(screen.getByText(/Contradicting evidence \(1\)/)).toBeInTheDocument();
    // Document evidence renders with the 📄 filename and page number (no web link).
    expect(screen.getByText(/architecture\.pdf/)).toBeInTheDocument();
    expect(screen.getByText(/p\.17/)).toBeInTheDocument();
  });

  it("renders an empty-state when there are no claims", () => {
    render(<ClaimsTab claims={[]} projectId="p1" />);
    expect(screen.getByText(/No claims verified yet/)).toBeInTheDocument();
  });
});
