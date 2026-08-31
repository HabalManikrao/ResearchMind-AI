import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

const { listResearch } = vi.hoisted(() => ({ listResearch: vi.fn() }));
vi.mock("../api/client", () => ({ api: { listResearch } }));

import History from "./History";
import type { ProjectSummary } from "../api/types";

function proj(over: Partial<ProjectSummary>): ProjectSummary {
  return {
    id: "p", title: "t", query: "q", mode: "deep", status: "completed",
    progress: 100, current_stage: null, created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z", parent_id: null, root_id: null,
    run_number: 1, run_intent: "original", completed_at: null, ...over,
  };
}

describe("History (lineage grouping)", () => {
  beforeEach(() => {
    listResearch.mockReset().mockResolvedValue([
      proj({ id: "r1", title: "Containers", root_id: "r1", run_number: 1, run_intent: "original", created_at: "2026-01-01T00:00:00Z" }),
      proj({ id: "r2", title: "Containers", root_id: "r1", parent_id: "r1", run_number: 2, run_intent: "refresh", created_at: "2026-02-01T00:00:00Z" }),
      proj({ id: "s1", title: "Standalone topic", root_id: "s1", run_number: 1, created_at: "2026-03-01T00:00:00Z" }),
    ]);
  });

  it("groups runs of one investigation into a single card", async () => {
    render(<MemoryRouter><History /></MemoryRouter>);
    // Two investigations: one multi-run, one standalone.
    expect(await screen.findByText("Standalone topic")).toBeInTheDocument();
    expect(screen.getByText(/latest of 2 runs/)).toBeInTheDocument();
    // The individual runs are hidden until expanded.
    expect(screen.queryByText("Run #2")).not.toBeInTheDocument();
  });

  it("expands a lineage to reveal each run", async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><History /></MemoryRouter>);
    await screen.findByText(/latest of 2 runs/);
    await user.click(screen.getByTitle("Show all runs"));
    expect(await screen.findByText("Run #2")).toBeInTheDocument();
    expect(screen.getByText("Run #1")).toBeInTheDocument();
  });
});
