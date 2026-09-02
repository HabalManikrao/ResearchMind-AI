import { describe, expect, it } from "vitest";
import {
  severityMeta,
  healthMeta,
  checkStatusLabel,
  FREQUENCY_LABEL,
  NOTIFY_POLICY_LABEL,
} from "./monitoring";

describe("severityMeta", () => {
  it("maps each severity to a label + icon", () => {
    expect(severityMeta("critical").label).toBe("Critical");
    expect(severityMeta("high").label).toBe("High");
    expect(severityMeta("medium").label).toBe("Medium");
    expect(severityMeta("low").label).toBe("Low");
  });

  it("falls back to low for null/garbage", () => {
    expect(severityMeta(null).label).toBe("Low");
    expect(severityMeta(undefined).label).toBe("Low");
    expect(severityMeta("nonsense" as never).label).toBe("Low");
  });
});

describe("healthMeta", () => {
  it("labels each monitor health state", () => {
    expect(healthMeta("healthy").label).toBe("Healthy");
    expect(healthMeta("degraded").label).toBe("Degraded");
    expect(healthMeta("failing").label).toBe("Failing");
    expect(healthMeta("disabled").label).toBe("Disabled");
  });

  it("falls back to offline for unknown", () => {
    expect(healthMeta("weird").label).toBe("Offline");
    expect(healthMeta(null).label).toBe("Offline");
  });
});

describe("checkStatusLabel", () => {
  it("humanizes check statuses", () => {
    expect(checkStatusLabel("no_change")).toMatch(/No meaningful change/);
    expect(checkStatusLabel("changes")).toMatch(/Changes detected/);
    expect(checkStatusLabel("suppressed")).toMatch(/suppressed/i);
    expect(checkStatusLabel("degraded")).toMatch(/retry/i);
    expect(checkStatusLabel("failed")).toMatch(/failed/i);
  });
});

describe("label maps", () => {
  it("covers frequency and notify policies", () => {
    expect(FREQUENCY_LABEL.daily).toBe("Daily");
    expect(FREQUENCY_LABEL.weekly).toBe("Weekly");
    expect(FREQUENCY_LABEL.monthly).toBe("Monthly");
    expect(NOTIFY_POLICY_LABEL.all).toMatch(/All meaningful/);
    expect(NOTIFY_POLICY_LABEL.important).toMatch(/Important/);
    expect(NOTIFY_POLICY_LABEL.critical).toMatch(/Critical/);
  });
});
