import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const api = vi.hoisted(() => ({
  methods: vi.fn(),
  hypotheses: vi.fn(),
  createMethod: vi.fn(),
  updateMethod: vi.fn(),
  deleteMethod: vi.fn(),
  createHypothesis: vi.fn(),
  updateHypothesis: vi.fn(),
  deleteHypothesis: vi.fn(),
}));
vi.mock("../api/client", () => ({ api }));

import LabPanel from "./LabPanel";

const method = (over = {}) => ({
  id: "m1", name: "Benchmark harness", description: "run workload Z", procedure: "",
  inputs: [], outputs: [], assumptions: [], advantages: [], disadvantages: [], limitations: [],
  applicability: "", status: "proposed", origin: "user", source_ids: [], claim_ids: [],
  notes: "", version: 1, ...over,
});
const hyp = (over = {}) => ({
  id: "h1", statement: "Qdrant beats Chroma", reasoning: "HNSW tuning", status: "proposed",
  confidence: null, origin: "user", question_ids: [], objective_ids: [], claim_ids: [],
  source_ids: [], method_id: null, variables: [], expected_result: "", assumptions: [], notes: "",
  ...over,
});

beforeEach(() => {
  Object.values(api).forEach((f) => f.mockReset());
  api.methods.mockResolvedValue([method()]);
  api.hypotheses.mockResolvedValue([hyp()]);
});

describe("LabPanel", () => {
  it("renders Methods and Hypotheses with the proposed hypothesis marked unvalidated", async () => {
    render(<LabPanel projectId="p1" />);
    expect(await screen.findByText("Benchmark harness")).toBeInTheDocument();
    expect(screen.getByText("Qdrant beats Chroma")).toBeInTheDocument();
    // A proposed hypothesis must be visibly "Not yet validated" — distinct from a claim.
    expect(screen.getByText("Not yet validated")).toBeInTheDocument();
    expect(screen.getByText(/Propositions awaiting validation/)).toBeInTheDocument();
  });

  it("creates a method", async () => {
    const user = userEvent.setup();
    api.createMethod.mockResolvedValue(method({ id: "m2", name: "Eval method" }));
    render(<LabPanel projectId="p1" />);
    await screen.findByText("Benchmark harness");
    await user.type(screen.getByPlaceholderText("Method name…"), "Eval method");
    await user.click(screen.getAllByRole("button", { name: /Add/ })[0]);
    await waitFor(() =>
      expect(api.createMethod).toHaveBeenCalledWith("p1", { name: "Eval method", description: "" }),
    );
    expect(await screen.findByText("Eval method")).toBeInTheDocument();
  });

  it("creates a hypothesis", async () => {
    const user = userEvent.setup();
    api.createHypothesis.mockResolvedValue(hyp({ id: "h2", statement: "X reduces cost" }));
    render(<LabPanel projectId="p1" />);
    await screen.findByText("Qdrant beats Chroma");
    await user.type(screen.getByPlaceholderText("Hypothesis statement…"), "X reduces cost");
    await user.click(screen.getAllByRole("button", { name: /Add/ })[1]);
    await waitFor(() =>
      expect(api.createHypothesis).toHaveBeenCalledWith("p1", {
        statement: "X reduces cost",
        reasoning: "",
      }),
    );
    expect(await screen.findByText("X reduces cost")).toBeInTheDocument();
  });

  it("changes a hypothesis status", async () => {
    const user = userEvent.setup();
    api.updateHypothesis.mockResolvedValue(hyp({ status: "rejected" }));
    render(<LabPanel projectId="p1" />);
    await screen.findByText("Qdrant beats Chroma");
    await user.selectOptions(screen.getByLabelText("Status for hypothesis"), "rejected");
    await waitFor(() =>
      expect(api.updateHypothesis).toHaveBeenCalledWith("p1", "h1", { status: "rejected" }),
    );
    // Rejected hypotheses remain visible (historical knowledge). "Rejected" appears both as
    // the status badge and as a <select> option, so assert the badge <span> specifically.
    const badge = (await screen.findAllByText("Rejected")).find((el) => el.tagName === "SPAN");
    expect(badge).toBeInTheDocument();
  });
});
