import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

const { capabilities, apiVersion } = vi.hoisted(() => ({
  capabilities: vi.fn(),
  apiVersion: vi.fn(),
}));
vi.mock("../api/client", () => ({ api: { capabilities, apiVersion } }));

import Integrations from "./Integrations";
import type { ApiVersion, CapabilityInfo } from "../api/types";

const CAPS: CapabilityInfo[] = [
  {
    name: "research_start", group: "research",
    description: "Start a new research run.",
    requires_network: true, may_invoke_llm: true, long_running: true, mutating: true,
  },
  {
    name: "knowledge_search", group: "knowledge",
    description: "Search entities.",
    requires_network: false, may_invoke_llm: false, long_running: false, mutating: false,
  },
];

const VERSION: ApiVersion = {
  name: "ResearchMind AI", api_version: "1.0",
  interfaces: { rest: "/v1", mcp: true }, auth_enabled: true, capabilities: 20,
};

beforeEach(() => {
  capabilities.mockReset();
  apiVersion.mockReset();
});

describe("Integrations", () => {
  it("lists capabilities grouped, with version and MCP setup", async () => {
    capabilities.mockResolvedValue({ capabilities: CAPS });
    apiVersion.mockResolvedValue(VERSION);
    render(<Integrations />);

    await waitFor(() => expect(screen.getByText("research_start")).toBeInTheDocument());
    expect(screen.getByText("knowledge_search")).toBeInTheDocument();
    // group headers
    expect(screen.getByText("research")).toBeInTheDocument();
    expect(screen.getByText("knowledge")).toBeInTheDocument();
    // version card
    expect(screen.getByText("/v1")).toBeInTheDocument();
    // MCP setup snippet with a placeholder, never a real token
    expect(screen.getByText(/YOUR_API_TOKEN/)).toBeInTheDocument();
  });

  it("renders an error state on failure", async () => {
    capabilities.mockRejectedValue(new Error("nope"));
    apiVersion.mockRejectedValue(new Error("nope"));
    render(<Integrations />);
    await waitFor(() => expect(screen.getByText("nope")).toBeInTheDocument());
  });
});
