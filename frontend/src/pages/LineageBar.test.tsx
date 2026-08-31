import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

// LineageBar itself calls no API (the action is a prop), but LiveResearch imports
// the client at module scope, so provide a stub.
vi.mock("../api/client", () => ({ api: {} }));

import { LineageBar } from "./LiveResearch";
import type { ProjectDetail, RunSummary } from "../api/types";

const project: ProjectDetail = {
  id: "r2", title: "t", query: "q", mode: "deep", status: "completed",
  progress: 100, current_stage: null, created_at: "2026-02-01T00:00:00Z",
  updated_at: "2026-02-01T00:00:00Z", parent_id: "r1", root_id: "r1",
  run_number: 2, run_intent: "refresh", completed_at: "2026-02-01T00:00:00Z",
  objective: "obj", constraints: {}, sources_enabled: ["web"], error: null, report_meta: null,
};

const runs: RunSummary[] = [
  { id: "r1", run_number: 1, run_intent: "original", status: "completed", created_at: "2026-01-01T00:00:00Z", completed_at: null, parent_id: null, source_count: 5, claim_count: 3, evidence_count: 4, avg_confidence: 70 },
  { id: "r2", run_number: 2, run_intent: "refresh", status: "completed", created_at: "2026-02-01T00:00:00Z", completed_at: null, parent_id: "r1", source_count: 6, claim_count: 4, evidence_count: 5, avg_confidence: 75 },
];

describe("LineageBar", () => {
  it("shows the run position and a compare link to the previous run", () => {
    render(
      <MemoryRouter>
        <LineageBar project={project} runs={runs} onAgain={vi.fn()} />
      </MemoryRouter>
    );
    expect(screen.getByText(/Run #2 of 2/)).toBeInTheDocument();
    const compare = screen.getByRole("link", { name: /Compare with Run #1/ });
    expect(compare).toHaveAttribute("href", "/research/r2/diff/r1");
  });

  it("posts the chosen intent when Research Again is clicked", async () => {
    const user = userEvent.setup();
    const onAgain = vi.fn().mockResolvedValue(undefined);
    render(
      <MemoryRouter>
        <LineageBar project={project} runs={runs} onAgain={onAgain} />
      </MemoryRouter>
    );
    await user.selectOptions(screen.getByRole("combobox"), "verify");
    await user.click(screen.getByRole("button", { name: /Research Again/ }));
    expect(onAgain).toHaveBeenCalledWith("verify");
  });
});
