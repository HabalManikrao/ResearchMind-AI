import { describe, expect, it } from "vitest";
import {
  deriveEvidenceState,
  evidenceStateMeta,
  freshnessMeta,
} from "./evidence";

describe("evidenceStateMeta", () => {
  it("labels each known state", () => {
    expect(evidenceStateMeta("supported").label).toBe("Supported");
    expect(evidenceStateMeta("weak").label).toBe("Weak evidence");
    expect(evidenceStateMeta("conflicting").label).toBe("Conflicting evidence");
    expect(evidenceStateMeta("outdated").label).toBe("Outdated evidence");
    expect(evidenceStateMeta("unverified").label).toBe("Unverified");
  });

  it("falls back to unverified for unknown states", () => {
    expect(evidenceStateMeta("nonsense").label).toBe("Unverified");
  });
});

describe("freshnessMeta", () => {
  it("maps freshness to a dot + label", () => {
    expect(freshnessMeta("fresh").dot).toBe("🟢");
    expect(freshnessMeta("aging").dot).toBe("🟡");
    expect(freshnessMeta("stale").label).toBe("Potentially outdated");
    expect(freshnessMeta("unknown").dot).toBe("⚪");
    expect(freshnessMeta("garbage").label).toBe("Unknown date");
  });
});

describe("deriveEvidenceState", () => {
  it("prioritises contradictions over everything", () => {
    expect(deriveEvidenceState("verified", { contradiction_count: 1 })).toBe(
      "conflicting",
    );
    expect(deriveEvidenceState("conflicted", null)).toBe("conflicting");
  });

  it("flags outdated when evidence is stale but not contradicted", () => {
    expect(deriveEvidenceState("verified", { outdated: true })).toBe("outdated");
  });

  it("maps clean statuses", () => {
    expect(deriveEvidenceState("verified", { contradiction_count: 0 })).toBe(
      "supported",
    );
    expect(deriveEvidenceState("partially_verified", null)).toBe("weak");
    expect(deriveEvidenceState("unverified", null)).toBe("unverified");
    expect(deriveEvidenceState("insufficient_evidence", null)).toBe("unverified");
  });
});
