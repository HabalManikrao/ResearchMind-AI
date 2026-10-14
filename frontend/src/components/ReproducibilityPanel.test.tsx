import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const api = vi.hoisted(() => ({
  reproducibility: vi.fn(),
  updateReproducibility: vi.fn(),
}));
vi.mock("../api/client", () => ({ api }));

import ReproducibilityPanel from "./ReproducibilityPanel";

const record = (over = {}) => ({
  id: "rr1", project_id: "p1", experiment_id: null, dataset_id: null, dataset_version: null,
  model_name: "llama3.1:8b", model_version: null, model_provider: "ollama",
  embedding_model: "nomic-embed-text", embedding_model_version: null, search_provider: "tavily",
  provider_config_id: "tavily", search_date: null, software: null, software_versions: null,
  hardware: null, os: null, environment: null, configuration: null, seed: null,
  git_commit: null, git_branch: null, git_dirty: null, raw_data_reference: null,
  processed_data_reference: null, as_of: "2026-01-01", verdict: "not_assessed", rationale: "",
  assessed_by: null, assessed_at: null, origin: "agent", notes: "", ...over,
});

beforeEach(() => {
  Object.values(api).forEach((f) => f.mockReset());
  api.reproducibility.mockResolvedValue(record());
});

describe("ReproducibilityPanel", () => {
  it("shows Not assessed honestly and separates captured metadata from the verdict", async () => {
    render(<ReproducibilityPanel projectId="p1" />);
    // Verdict badge + the honesty note.
    expect((await screen.findAllByText("Not assessed")).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/imply the research was reproduced/i)).toBeInTheDocument();
    // Captured metadata section shows safe identifiers; unavailable → "—".
    expect(screen.getByText("Captured Metadata")).toBeInTheDocument();
    expect(screen.getByText("llama3.1:8b")).toBeInTheDocument();
    expect(screen.getByText("nomic-embed-text")).toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThan(0); // nulls rendered as dashes
  });

  it("records an explicit verdict with rationale", async () => {
    const user = userEvent.setup();
    api.updateReproducibility.mockResolvedValue(record({
      verdict: "partially_reproducible", rationale: "model pinned; dataset unversioned" }));
    render(<ReproducibilityPanel projectId="p1" />);
    await screen.findByText("Captured Metadata");
    await user.selectOptions(screen.getByLabelText("Reproducibility verdict"), "partially_reproducible");
    await user.type(screen.getByPlaceholderText(/Why this verdict/), "model pinned; dataset unversioned");
    await user.click(screen.getByRole("button", { name: /Save assessment/ }));
    await waitFor(() =>
      expect(api.updateReproducibility).toHaveBeenCalledWith("p1", {
        verdict: "partially_reproducible", rationale: "model pinned; dataset unversioned",
      }),
    );
    expect(await screen.findByText("Saved")).toBeInTheDocument();
  });

  it("does not display a positive verdict when the record is not_assessed", async () => {
    render(<ReproducibilityPanel projectId="p1" />);
    await screen.findByText("Captured Metadata");
    // "Reproducible" appears only as a <select> option, never as the current-verdict badge.
    const badges = screen.getAllByText("Reproducible");
    expect(badges.every((el) => el.tagName === "OPTION")).toBe(true);
  });
});
