import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const api = vi.hoisted(() => ({
  brief: vi.fn(),
  objectives: vi.fn(),
  constraints: vi.fn(),
  terminology: vi.fn(),
  updateBrief: vi.fn(),
  createObjective: vi.fn(),
  deleteObjective: vi.fn(),
  createConstraint: vi.fn(),
  deleteConstraint: vi.fn(),
  createTerm: vi.fn(),
  deleteTerm: vi.fn(),
}));
vi.mock("../api/client", () => ({ api }));

import BriefPanel from "./BriefPanel";

function brief(over = {}) {
  return {
    id: "b1", project_id: "p1", problem_statement: "", background: "", expected_outcome: "",
    scope_included: [], scope_excluded: [], assumptions: [], target_users: [],
    success_criteria: [], version: 1, ...over,
  };
}

beforeEach(() => {
  Object.values(api).forEach((f) => f.mockReset());
  api.brief.mockResolvedValue(brief({ problem_statement: "Pick a vector DB", version: 2 }));
  api.objectives.mockResolvedValue([
    { id: "o1", description: "Find fastest offline DB", priority: 1, status: "in_progress",
      completion_pct: 40, question_ids: [], notes: "" },
  ]);
  api.constraints.mockResolvedValue([{ id: "c1", ctype: "hardware", text: "CPU only" }]);
  api.terminology.mockResolvedValue([
    { id: "t1", term: "HNSW", definition: "graph index", synonyms: [], acronyms: [], related: [] },
  ]);
});

describe("BriefPanel", () => {
  it("loads and renders brief, objectives, constraints, terminology", async () => {
    render(<BriefPanel projectId="p1" />);
    expect(await screen.findByDisplayValue("Pick a vector DB")).toBeInTheDocument();
    expect(screen.getByText("v2")).toBeInTheDocument();
    expect(screen.getByText("Find fastest offline DB")).toBeInTheDocument();
    expect(screen.getByText("CPU only")).toBeInTheDocument();
    expect(screen.getByText("HNSW")).toBeInTheDocument();
  });

  it("saves the brief with the edited problem statement", async () => {
    const user = userEvent.setup();
    api.updateBrief.mockResolvedValue(brief({ problem_statement: "Pick a vector DB!", version: 3 }));
    render(<BriefPanel projectId="p1" />);
    const box = await screen.findByDisplayValue("Pick a vector DB");
    await user.type(box, "!");
    await user.click(screen.getByRole("button", { name: /Save brief/ }));
    await waitFor(() => expect(api.updateBrief).toHaveBeenCalledTimes(1));
    expect(api.updateBrief.mock.calls[0][1].problem_statement).toBe("Pick a vector DB!");
    expect(await screen.findByText(/Saved \(v3\)/)).toBeInTheDocument();
  });

  it("adds an objective", async () => {
    const user = userEvent.setup();
    api.createObjective.mockResolvedValue({
      id: "o2", description: "New obj", priority: 3, status: "not_started",
      completion_pct: 0, question_ids: [], notes: "" });
    render(<BriefPanel projectId="p1" />);
    await screen.findByText("Find fastest offline DB");
    await user.type(screen.getByPlaceholderText("New objective…"), "New obj");
    await user.click(screen.getAllByRole("button", { name: /Add/ })[0]);
    await waitFor(() => expect(api.createObjective).toHaveBeenCalledWith("p1", { description: "New obj" }));
    expect(await screen.findByText("New obj")).toBeInTheDocument();
  });
});
