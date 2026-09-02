import { describe, expect, it } from "vitest";
import {
  availabilityMeta,
  connectivityMeta,
  deriveAvailability,
  researchHealthMeta,
} from "./provenance";

describe("availabilityMeta", () => {
  it("maps each availability to a dot + label", () => {
    expect(availabilityMeta("live").dot).toBe("🟢");
    expect(availabilityMeta("cached").dot).toBe("🔵");
    expect(availabilityMeta("local").dot).toBe("📄");
    expect(availabilityMeta("stale").dot).toBe("🟡");
    expect(availabilityMeta("unavailable").dot).toBe("🔴");
    expect(availabilityMeta("unknown").dot).toBe("⚪");
  });

  it("falls back to unknown for garbage", () => {
    expect(availabilityMeta("nonsense").label).toBe("Unknown");
  });
});

describe("deriveAvailability", () => {
  it("stale freshness overrides provenance", () => {
    expect(deriveAvailability("live_web", "stale")).toBe("stale");
    expect(deriveAvailability("local_document", "stale")).toBe("stale");
  });

  it("maps provenance straight through when not stale", () => {
    expect(deriveAvailability("live_web", "fresh")).toBe("live");
    expect(deriveAvailability("cached_web", "fresh")).toBe("cached");
    expect(deriveAvailability("local_document", "aging")).toBe("local");
    expect(deriveAvailability("local_memory", "fresh")).toBe("local");
  });

  it("returns unknown for unrecognised provenance", () => {
    expect(deriveAvailability("bogus", "fresh")).toBe("unknown");
  });
});

describe("researchHealthMeta", () => {
  it("labels the health states", () => {
    expect(researchHealthMeta("fully_live").label).toBe("Fully live");
    expect(researchHealthMeta("cache_assisted").label).toBe("Cache-assisted");
    expect(researchHealthMeta("local_only").label).toBe("Local only");
    expect(researchHealthMeta("external_unavailable").label).toBe(
      "External sources unavailable",
    );
  });
});

describe("connectivityMeta", () => {
  it("maps connectivity states", () => {
    expect(connectivityMeta("online").label).toBe("Online");
    expect(connectivityMeta("degraded").label).toBe("Degraded");
    expect(connectivityMeta("local_only").label).toBe("Local only");
    expect(connectivityMeta("offline").label).toBe("Offline");
    expect(connectivityMeta("weird").label).toBe("Unknown");
  });
});
