import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";

const { entity, entityClaims } = vi.hoisted(() => ({
  entity: vi.fn(),
  entityClaims: vi.fn(),
}));
vi.mock("../api/client", () => ({ api: { entity, entityClaims } }));

import EntityDetail from "./EntityDetail";
import type { EntityDetail as EntityDetailT, EntityClaim } from "../api/types";

function detail(over: Partial<EntityDetailT> = {}): EntityDetailT {
  return {
    entity: {
      id: "e1",
      canonical_name: "Unreal Engine 5",
      normalized_name: "unreal engine 5",
      entity_type: "software",
      description: "A game engine.",
      aliases: ["UE5"],
      mention_count: 7,
      first_observed_at: "2026-01-01T00:00:00Z",
      last_observed_at: "2026-06-01T00:00:00Z",
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-06-01T00:00:00Z",
    },
    related: [
      {
        relationship_id: "r1",
        predicate: "alternative_to",
        direction: "out",
        confidence: 0.6,
        provenance_kind: "derived",
        status: "active",
        entity: { id: "e2", canonical_name: "Unity", entity_type: "software", mention_count: 3 },
      },
    ],
    current_claims: 1,
    historical_claims: 1,
    source_count: 4,
    run_count: 2,
    ...over,
  };
}

function claim(over: Partial<EntityClaim> = {}): EntityClaim {
  return {
    claim_id: "c1",
    text: "UE5 improves Nanite.",
    status: "verified",
    confidence: 82,
    evidence_state: "supported",
    project_id: "p1",
    run_number: 2,
    disputed: false,
    superseded: false,
    ...over,
  };
}

function renderAt() {
  return render(
    <MemoryRouter initialEntries={["/knowledge/entities/e1"]}>
      <Routes>
        <Route path="/knowledge/entities/:id" element={<EntityDetail />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  entity.mockReset();
  entityClaims.mockReset();
});

describe("EntityDetail", () => {
  it("renders the entity, related entities, and current vs historical claims", async () => {
    entity.mockResolvedValue(detail());
    entityClaims.mockImplementation((_id: string, scope: string) =>
      Promise.resolve(
        scope === "current"
          ? [claim({ claim_id: "cur", text: "UE5 is fast now." })]
          : [claim({ claim_id: "old", text: "UE5 was slow.", superseded: true })],
      ),
    );
    renderAt();

    await waitFor(() => expect(screen.getByText("Unreal Engine 5")).toBeInTheDocument());
    expect(screen.getByText(/A game engine/)).toBeInTheDocument();
    expect(screen.getByText(/Also known as: UE5/)).toBeInTheDocument(); // alias
    // Related entity with a humanized predicate + link.
    expect(screen.getByText(/alternative to/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Unity" })).toHaveAttribute(
      "href",
      "/knowledge/entities/e2",
    );
    // Current + historical sections.
    expect(screen.getByText("UE5 is fast now.")).toBeInTheDocument();
    expect(screen.getByText(/Historical knowledge/)).toBeInTheDocument();
    expect(screen.getByText("UE5 was slow.")).toBeInTheDocument();
    // Evidence drill-down link points to the owning run.
    expect(screen.getAllByRole("link", { name: /View evidence/ })[0]).toHaveAttribute(
      "href",
      "/research/p1",
    );
  });

  it("shows a disputed badge for a contradicted claim", async () => {
    entity.mockResolvedValue(detail({ historical_claims: 0 }));
    entityClaims.mockImplementation((_id: string, scope: string) =>
      Promise.resolve(scope === "current" ? [claim({ disputed: true })] : []),
    );
    renderAt();
    await waitFor(() => expect(screen.getByText("Disputed")).toBeInTheDocument());
  });

  it("renders an error state when the fetch fails", async () => {
    entity.mockRejectedValue(new Error("boom"));
    entityClaims.mockResolvedValue([]);
    renderAt();
    await waitFor(() => expect(screen.getByText("boom")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: /Back to Knowledge/ })).toBeInTheDocument();
  });
});
