import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route } from "react-router-dom";

const { diff } = vi.hoisted(() => ({ diff: vi.fn() }));
vi.mock("../api/client", () => ({ api: { diff } }));

import RunDiff from "./RunDiff";
import type { ResearchDiff } from "../api/types";

const sample: ResearchDiff = {
  old_run: { id: "r1", run_number: 1, run_intent: "original", completed_at: null },
  new_run: { id: "r2", run_number: 2, run_intent: "refresh", completed_at: null },
  sources: {
    new: 3, removed: 1, unchanged: 4, changed: 1,
    items: [
      { kind: "new", url: "https://x.example", title: "New source", source_type: "web", changes: [] },
      { kind: "changed", url: "https://y.example", title: "Shifted", source_type: "web", changes: ["reliability 60 → 80"] },
    ],
  },
  claims: {
    new: 1, removed: 0, unchanged: 2, strengthened: 1, weakened: 0, contradicted: 1,
    items: [
      {
        kind: "contradicted",
        old_text: "The library is production ready",
        new_text: "The library is production ready",
        old_confidence: 82,
        new_confidence: 55,
        confidence_delta: -27,
        direction: "down",
        reason: "contradictions 0 → 2; confidence 82 → 55",
        match_score: 1.0,
        old_evidence: [
          { title: "Docs", url: "https://docs.example", source_type: "web", stance: "supports", passage: "It is stable.", page_number: null },
        ],
        new_evidence: [
          { title: "Bug tracker", url: "https://bugs.example", source_type: "web", stance: "contradicts", passage: "Crashes under load.", page_number: null },
        ],
      },
    ],
  },
  confidence: { increased: 1, decreased: 1, unchanged: 2 },
  recommendation: {
    kind: "reversed",
    old: { option: "Option A", confidence: 80 },
    new: { option: "Option B", confidence: 75 },
  },
  documents: { new: 0, removed: 0, unchanged: 1, changed: 0, items: [] },
};

function renderDiff() {
  return render(
    <MemoryRouter initialEntries={["/research/r2/diff/r1"]}>
      <Routes>
        <Route path="/research/:id/diff/:otherId" element={<RunDiff />} />
      </Routes>
    </MemoryRouter>
  );
}

describe("RunDiff", () => {
  beforeEach(() => {
    diff.mockReset().mockResolvedValue(sample);
  });

  it("renders the run header and summary counts", async () => {
    renderDiff();
    expect(await screen.findByText("Research Changes")).toBeInTheDocument();
    expect(screen.getByText(/Run #1/)).toBeInTheDocument();
    expect(screen.getByText(/Run #2/)).toBeInTheDocument();
    // contradicted claims surfaced in the summary
    expect(screen.getByText(/1 contradicted/)).toBeInTheDocument();
    // recommendation reversed
    expect(screen.getByText("reversed")).toBeInTheDocument();
    expect(diff).toHaveBeenCalledWith("r2", "r1");
  });

  it("shows a changed claim with its confidence delta and reason", async () => {
    renderDiff();
    expect(await screen.findByText(/The library is production ready/)).toBeInTheDocument();
    // "82 → 55" shows in both the confidence badge and the reason line.
    expect(screen.getAllByText(/82 → 55/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/contradictions 0 → 2/)).toBeInTheDocument();
  });

  it("drills into a changed claim to show previous vs current evidence", async () => {
    const user = userEvent.setup();
    renderDiff();
    await user.click(await screen.findByText(/The library is production ready/));
    expect(await screen.findByText(/Previous evidence/)).toBeInTheDocument();
    expect(screen.getByText(/Current evidence/)).toBeInTheDocument();
    expect(screen.getByText(/It is stable/)).toBeInTheDocument();
    expect(screen.getByText(/Crashes under load/)).toBeInTheDocument();
  });
});
