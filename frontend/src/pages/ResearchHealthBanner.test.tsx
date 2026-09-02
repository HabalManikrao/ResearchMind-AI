import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ResearchHealthBanner } from "./LiveResearch";
import type { SourceHealth } from "../api/types";

function health(over: Partial<SourceHealth> = {}): SourceHealth {
  return {
    live: 0, cached: 0, local: 0, stale: 0, unknown: 0, unavailable: 0,
    provider_failures: 0, fallback_count: 0, retry_count: 0,
    connectivity_state: "online", research_mode: "live", research_health: "fully_live",
    ...over,
  };
}

describe("ResearchHealthBanner", () => {
  it("stays quiet for a clean fully-live run", () => {
    const { container } = render(
      <ResearchHealthBanner health={health({ live: 5, research_health: "fully_live" })} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when no health data", () => {
    const { container } = render(<ResearchHealthBanner health={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("discloses cache-assisted sourcing with counts", () => {
    render(
      <ResearchHealthBanner
        health={health({
          live: 2, cached: 3, research_mode: "cache", research_health: "cache_assisted",
        })}
      />,
    );
    expect(screen.getByText(/Cache-assisted/)).toBeInTheDocument();
    expect(screen.getByText(/Cached: 3/)).toBeInTheDocument();
  });

  it("warns about unavailable external sources and local-only mode", () => {
    render(
      <ResearchHealthBanner
        health={health({
          local: 4, unavailable: 2, research_mode: "local",
          research_health: "local_only",
        })}
      />,
    );
    expect(screen.getByText(/Local only/)).toBeInTheDocument();
    expect(screen.getByText(/live web verification was unavailable/i)).toBeInTheDocument();
    expect(screen.getByText(/coverage is incomplete/i)).toBeInTheDocument();
  });
});
