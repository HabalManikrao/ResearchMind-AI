import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const api = vi.hoisted(() => ({
  comparisons: vi.fn(),
  limitations: vi.fn(),
  gaps: vi.fn(),
  createComparison: vi.fn(),
  deleteComparison: vi.fn(),
  createLimitation: vi.fn(),
  updateLimitation: vi.fn(),
  deleteLimitation: vi.fn(),
  createGap: vi.fn(),
  updateGap: vi.fn(),
  deleteGap: vi.fn(),
}));
vi.mock("../api/client", () => ({ api }));

import SynthesisPanel from "./SynthesisPanel";

const comparison = (over = {}) => ({
  id: "c1", title: "", description: "", subject_a: "Model A", subject_b: "Model B",
  criterion: "accuracy", value: "91", unit: "%", conditions: "", grounded: false,
  source_ids: [], experiment_ids: [], result_ids: [], confidence: null, origin: "user", notes: "",
  ...over,
});
const limitation = (over = {}) => ({
  id: "l1", ltype: "dataset", title: "", description: "synthetic data only", severity: "high",
  affected_kind: null, affected_id: null, impact: "", mitigation: "collect real data",
  status: "open", source_ids: [], claim_ids: [], confidence: null, origin: "user", notes: "", ...over,
});
const gap = (over = {}) => ({
  id: "g1", question: "How does it scale to 10M vectors?", reason: "", followup_query: "",
  round: 0, resolved: false, importance: "high", impact: null, potential_investigation: null,
  status: "open", confidence: null, origin: "agent", ...over,
});

beforeEach(() => {
  Object.values(api).forEach((f) => f.mockReset());
  api.comparisons.mockResolvedValue([comparison()]);
  api.limitations.mockResolvedValue([limitation()]);
  api.gaps.mockResolvedValue([gap()]);
});

describe("SynthesisPanel", () => {
  it("renders comparisons/limitations/gaps; ungrounded comparison + gap-as-open-question shown", async () => {
    render(<SynthesisPanel projectId="p1" />);
    expect(await screen.findByText(/Model A vs\. Model B/)).toBeInTheDocument();
    expect(screen.getByText("ungrounded")).toBeInTheDocument(); // no evidence links
    expect(screen.getByText("synthetic data only")).toBeInTheDocument();
    expect(screen.getByText("How does it scale to 10M vectors?")).toBeInTheDocument();
    // A gap is explicitly an open question, never a verified finding.
    expect(screen.getByText("Open question")).toBeInTheDocument();
    expect(screen.getByText(/verified findings/i)).toBeInTheDocument();
  });

  it("flags a grounded comparison", async () => {
    api.comparisons.mockResolvedValue([comparison({ grounded: true, result_ids: ["r1"] })]);
    render(<SynthesisPanel projectId="p1" />);
    expect(await screen.findByText("grounded")).toBeInTheDocument();
  });

  it("creates a limitation", async () => {
    const user = userEvent.setup();
    api.createLimitation.mockResolvedValue(limitation({ id: "l2", description: "small sample" }));
    render(<SynthesisPanel projectId="p1" />);
    await screen.findByText("synthetic data only");
    await user.type(screen.getByPlaceholderText("Limitation description…"), "small sample");
    // The Limitation adder's Add button is the 2nd (comparison adder is 1st).
    await user.click(screen.getAllByRole("button", { name: /Add/ })[1]);
    await waitFor(() => expect(api.createLimitation).toHaveBeenCalled());
    expect(api.createLimitation.mock.calls[0][1].description).toBe("small sample");
    expect(await screen.findByText("small sample")).toBeInTheDocument();
  });

  it("changes a gap status", async () => {
    const user = userEvent.setup();
    api.updateGap.mockResolvedValue(gap({ status: "investigating" }));
    render(<SynthesisPanel projectId="p1" />);
    await screen.findByText("How does it scale to 10M vectors?");
    await user.selectOptions(screen.getByLabelText("Gap status"), "investigating");
    await waitFor(() =>
      expect(api.updateGap).toHaveBeenCalledWith("p1", "g1", { status: "investigating" }),
    );
  });
});
