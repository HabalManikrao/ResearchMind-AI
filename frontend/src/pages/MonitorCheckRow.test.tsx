import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { MonitorCheckRow } from "./LiveResearch";
import type { MonitorCheck } from "../api/types";

function check(over: Partial<MonitorCheck> = {}): MonitorCheck {
  return {
    id: "c1",
    monitor_id: "m1",
    baseline_run_id: "run-a",
    new_run_id: "run-b",
    status: "changes",
    provenance_mode: "live",
    meaningful_changes: [],
    suppressed_count: 0,
    notification_id: "n1",
    source_health: null,
    detail: null,
    max_impact: "critical",
    escalated: true,
    started_at: null,
    finished_at: null,
    created_at: new Date().toISOString(),
    ...over,
  };
}

function renderRow(c: MonitorCheck) {
  return render(
    <MemoryRouter>
      <MonitorCheckRow check={c} />
    </MemoryRouter>,
  );
}

describe("MonitorCheckRow", () => {
  it("shows the status, severity, and a diff link when a run was created", () => {
    renderRow(
      check({
        max_impact: "critical",
        meaningful_changes: [
          {
            kind: "recommendation_reversed",
            impact: "critical",
            title: "Recommendation changed",
            detail: "OptX → OptY",
            dedup_key: "k1",
            reasons: [],
            refs: {},
            notified: true,
          },
        ],
      }),
    );
    expect(screen.getByText(/Changes detected/)).toBeInTheDocument();
    expect(screen.getByText(/Critical/)).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /View diff/i });
    expect(link).toHaveAttribute("href", "/research/run-b/diff/run-a");
  });

  it("expands to reveal the underlying changes on click", () => {
    renderRow(
      check({
        meaningful_changes: [
          {
            kind: "claim_contradicted",
            impact: "high",
            title: "A supported claim is now contradicted",
            detail: "Some claim detail",
            dedup_key: "k2",
            reasons: [],
            refs: {},
            notified: true,
          },
        ],
      }),
    );
    // Collapsed initially — the change detail is not shown.
    expect(screen.queryByText(/Some claim detail/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByText(/Changes detected/));
    expect(screen.getByText(/A supported claim is now contradicted/)).toBeInTheDocument();
    expect(screen.getByText(/Some claim detail/)).toBeInTheDocument();
  });

  it("marks a no-change check plainly with no diff link", () => {
    renderRow(
      check({ status: "no_change", max_impact: null, new_run_id: null, baseline_run_id: null }),
    );
    expect(screen.getByText(/No meaningful change/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /View diff/i })).not.toBeInTheDocument();
  });
});
