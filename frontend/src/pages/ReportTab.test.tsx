import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// api is only used by the export links; stub it so the component renders in isolation.
vi.mock("../api/client", () => ({ api: { exportUrl: (id: string, fmt: string) => `/x/${id}.${fmt}` } }));

import { ReportTab } from "./LiveResearch";
import type { Report } from "../api/types";

function report(over: Partial<Report["meta"]> = {}, markdown = "# Research Report\n\nBody."): Report {
  return {
    project_id: "p1",
    markdown,
    meta: {
      overall_confidence: 0, sources_analyzed: 0, verified_claims: 0,
      conflicted_claims: 0, total_claims: 0, ...over,
    },
  } as Report;
}

describe("ReportTab evidence-incomplete banner", () => {
  it("shows the incomplete banner when a run collected zero evidence", () => {
    render(<ReportTab report={report({ evidence_incomplete: true })} isActive={false} />);
    expect(screen.getByText(/Research incomplete/)).toBeInTheDocument();
    expect(screen.getByText(/not an evidence-backed conclusion/)).toBeInTheDocument();
  });

  it("does NOT show the banner for a normal evidence-backed report", () => {
    render(
      <ReportTab
        report={report({ evidence_incomplete: false, overall_confidence: 88, sources_analyzed: 5 })}
        isActive={false}
      />,
    );
    expect(screen.queryByText(/Research incomplete/)).not.toBeInTheDocument();
    expect(screen.getByText("88%")).toBeInTheDocument();
  });

  it("treats a missing flag as a normal report (backward compatible)", () => {
    render(<ReportTab report={report({})} isActive={false} />);
    expect(screen.queryByText(/Research incomplete/)).not.toBeInTheDocument();
  });
});
