import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const api = vi.hoisted(() => ({
  analyses: vi.fn(),
  conclusions: vi.fn(),
  claims: vi.fn(),
  createAnalysis: vi.fn(),
  updateAnalysis: vi.fn(),
  deleteAnalysis: vi.fn(),
  createConclusion: vi.fn(),
  updateConclusion: vi.fn(),
  deleteConclusion: vi.fn(),
}));
vi.mock("../api/client", () => ({ api }));

import AnalysisPanel from "./AnalysisPanel";

const analysis = (over = {}) => ({
  id: "a1", title: "", statement: "p95 supports the latency claim", classification: "fact",
  reasoning: "", confidence: 80, origin: "user", claim_ids: ["c1"], source_ids: [],
  result_ids: ["r1"], experiment_ids: [], notes: "", ...over,
});
const conclusion = (over = {}) => ({
  id: "k1", title: "", statement: "Adopt Qdrant", classification: "strongly_supported",
  confidence: null, reasoning: "", origin: "user", analysis_ids: ["a1"], claim_ids: [],
  source_ids: [], question_ids: [], contradicting_claim_ids: [], notes: "", ...over,
});
const claim = () => ({
  id: "c1", text: "Qdrant is fast", status: "verified", confidence: 90,
  supporting_source_ids: [], evidence_state: "supported",
});

beforeEach(() => {
  Object.values(api).forEach((f) => f.mockReset());
  api.analyses.mockResolvedValue([analysis()]);
  api.conclusions.mockResolvedValue([conclusion()]);
  api.claims.mockResolvedValue([claim()]);
});

describe("AnalysisPanel", () => {
  it("renders analysis + conclusions with classification badges and grounding", async () => {
    render(<AnalysisPanel projectId="p1" />);
    expect((await screen.findAllByText("p95 supports the latency claim")).length).toBeGreaterThanOrEqual(1);
    // "fact" appears both as the badge and as a <select> option → at least one present.
    expect(screen.getAllByText("fact").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("grounded in 1 claim(s), 1 result(s)")).toBeInTheDocument();
    expect(screen.getByText("Adopt Qdrant")).toBeInTheDocument();
    expect(screen.getAllByText("strongly supported").length).toBeGreaterThanOrEqual(1);
  });

  it("keeps the Add-analysis button disabled until a grounding claim is chosen", async () => {
    const user = userEvent.setup();
    render(<AnalysisPanel projectId="p1" />);
    await screen.findAllByText("p95 supports the latency claim");
    await user.type(screen.getByPlaceholderText("Analysis statement…"), "New interpretation");
    const addBtns = screen.getAllByRole("button", { name: /Add/ });
    expect(addBtns[0]).toBeDisabled(); // grounding not yet selected
    await user.selectOptions(screen.getByLabelText("Ground in claim"), "c1");
    expect(addBtns[0]).toBeEnabled();
  });

  it("creates a grounded analysis", async () => {
    const user = userEvent.setup();
    api.createAnalysis.mockResolvedValue(analysis({ id: "a2", statement: "New interpretation",
      classification: "inference", confidence: null }));
    render(<AnalysisPanel projectId="p1" />);
    await screen.findAllByText("p95 supports the latency claim");
    await user.type(screen.getByPlaceholderText("Analysis statement…"), "New interpretation");
    await user.selectOptions(screen.getByLabelText("New analysis classification"), "inference");
    await user.selectOptions(screen.getByLabelText("Ground in claim"), "c1");
    await user.click(screen.getAllByRole("button", { name: /Add/ })[0]);
    await waitFor(() =>
      expect(api.createAnalysis).toHaveBeenCalledWith("p1", {
        statement: "New interpretation", classification: "inference", claim_ids: ["c1"],
      }),
    );
    expect((await screen.findAllByText("New interpretation")).length).toBeGreaterThanOrEqual(1);
  });

  it("changes a conclusion classification", async () => {
    const user = userEvent.setup();
    api.updateConclusion.mockResolvedValue(conclusion({ classification: "contradicted" }));
    render(<AnalysisPanel projectId="p1" />);
    await screen.findByText("Adopt Qdrant");
    await user.selectOptions(screen.getByLabelText("Conclusion classification"), "contradicted");
    await waitFor(() =>
      expect(api.updateConclusion).toHaveBeenCalledWith("p1", "k1", { classification: "contradicted" }),
    );
  });
});
