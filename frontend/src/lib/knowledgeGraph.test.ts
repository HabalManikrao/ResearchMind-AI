import { describe, expect, it } from "vitest";
import {
  entityTypeLabel,
  entityTypeClass,
  predicateLabel,
  provenanceKindMeta,
  relationshipStatusLabel,
} from "./knowledgeGraph";

describe("entityTypeLabel", () => {
  it("capitalizes and defaults", () => {
    expect(entityTypeLabel("software")).toBe("Software");
    expect(entityTypeLabel("company")).toBe("Company");
    expect(entityTypeLabel("")).toBe("Other");
  });
});

describe("entityTypeClass", () => {
  it("returns a class per type with an other fallback", () => {
    expect(entityTypeClass("technology")).toContain("indigo");
    expect(entityTypeClass("company")).toContain("emerald");
    expect(entityTypeClass("nonsense")).toBe(entityTypeClass("other"));
  });
});

describe("predicateLabel", () => {
  it("humanizes underscored predicates", () => {
    expect(predicateLabel("alternative_to")).toBe("alternative to");
    expect(predicateLabel("related_to")).toBe("related to");
  });
});

describe("provenanceKindMeta", () => {
  it("labels explicit/derived/inferred with a default", () => {
    expect(provenanceKindMeta("explicit").label).toBe("Explicit");
    expect(provenanceKindMeta("derived").label).toBe("Derived");
    expect(provenanceKindMeta("inferred").label).toBe("Inferred");
    expect(provenanceKindMeta("weird").label).toBe("Derived");
  });
});

describe("relationshipStatusLabel", () => {
  it("labels temporal statuses", () => {
    expect(relationshipStatusLabel("disputed")).toBe("Disputed");
    expect(relationshipStatusLabel("superseded")).toBe("Superseded");
    expect(relationshipStatusLabel("active")).toBe("Active");
  });
});
