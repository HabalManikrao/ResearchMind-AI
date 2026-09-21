import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const api = vi.hoisted(() => ({
  experiments: vi.fn(),
  datasets: vi.fn(),
  results: vi.fn(),
  createExperiment: vi.fn(),
  updateExperiment: vi.fn(),
  deleteExperiment: vi.fn(),
  createDataset: vi.fn(),
  deleteDataset: vi.fn(),
}));
vi.mock("../api/client", () => ({ api }));

import ExperimentsPanel from "./ExperimentsPanel";

const experiment = (over = {}) => ({
  id: "e1", name: "Latency benchmark", description: "", question_id: null, objective_id: null,
  hypothesis_id: null, method_id: null, dataset_id: null, dataset_version: null,
  independent_variables: [], dependent_variables: [], controlled_variables: [], controls: "",
  assumptions: [], expected_result: "p95 < 50ms", failure_conditions: "", procedure: "",
  inputs: [], outputs: [], metrics: [], hardware: "", software: "", software_versions: [],
  environment: "", configuration: {}, seed: null, status: "proposed", planned_at: null,
  started_at: null, completed_at: null, actual_result_summary: null, raw_data_reference: null,
  processed_data_reference: null, execution_notes: "", origin: "user", ...over,
});
const dataset = (over = {}) => ({
  id: "d1", name: "WorkloadZ", description: "", version: "1", supersedes_id: null, source: "internal",
  source_url: null, license: "", data_type: "", size: "2 GB", record_count: null, features: [],
  collection_method: "", collection_date: null, preprocessing: "", bias: [],
  limitations: ["synthetic"], quality: "", access_information: "", checksum: null, meta: {},
  origin: "user", ...over,
});
const result = (over = {}) => ({
  id: "r1", experiment_id: "e1", dataset_id: "d1", name: "p95", description: "",
  result_type: "benchmark",
  metrics: [{ name: "p95", value: 42, unit: "ms", lower_bound: 40, upper_bound: 45, conditions: "warm" }],
  measurements: [], benchmark: "", error_rate: null, latency: "42ms", throughput: null,
  accuracy: null, cost: null, resource_usage: "", observations: "stable", anomalies: "",
  raw_data_reference: null, processed_data_reference: null, conditions: "", confidence: 80,
  origin: "user", notes: "", ...over,
});

beforeEach(() => {
  Object.values(api).forEach((f) => f.mockReset());
  api.experiments.mockResolvedValue([experiment()]);
  api.datasets.mockResolvedValue([dataset()]);
  api.results.mockResolvedValue([result()]);
});

describe("ExperimentsPanel", () => {
  it("renders experiments/datasets/results; a proposed experiment shows 'Not executed'", async () => {
    render(<ExperimentsPanel projectId="p1" />);
    expect(await screen.findByText("Latency benchmark")).toBeInTheDocument();
    expect(screen.getByText("Not executed")).toBeInTheDocument(); // planned != executed
    expect(screen.getByText("WorkloadZ")).toBeInTheDocument();
    expect(screen.getByText("v1")).toBeInTheDocument();
    // Structured metric value + unit + bounds shown as data.
    expect(screen.getByText(/p95: 42 ms \[40–45\] \(warm\)/)).toBeInTheDocument();
  });

  it("does not show execution details for a non-executed experiment", async () => {
    api.experiments.mockResolvedValue([
      experiment({ actual_result_summary: "should be hidden while proposed" }),
    ]);
    render(<ExperimentsPanel projectId="p1" />);
    await screen.findByText("Latency benchmark");
    // actual_result_summary is only rendered for executed statuses.
    expect(screen.queryByText(/should be hidden/)).not.toBeInTheDocument();
  });

  it("reveals the recorded outcome once the experiment is executed", async () => {
    api.experiments.mockResolvedValue([
      experiment({ status: "completed", completed_at: "2026-02-01",
        actual_result_summary: "recorded: p95=42ms" }),
    ]);
    render(<ExperimentsPanel projectId="p1" />);
    expect(await screen.findByText(/Recorded outcome: recorded: p95=42ms/)).toBeInTheDocument();
    expect(screen.getByText(/Completed: 2026-02-01/)).toBeInTheDocument();
  });

  it("creates an experiment", async () => {
    const user = userEvent.setup();
    api.createExperiment.mockResolvedValue(experiment({ id: "e2", name: "Throughput test" }));
    render(<ExperimentsPanel projectId="p1" />);
    await screen.findByText("Latency benchmark");
    await user.type(screen.getByPlaceholderText("Experiment name…"), "Throughput test");
    await user.click(screen.getAllByRole("button", { name: /Add/ })[0]);
    await waitFor(() =>
      expect(api.createExperiment).toHaveBeenCalledWith("p1", { name: "Throughput test" }),
    );
    expect(await screen.findByText("Throughput test")).toBeInTheDocument();
  });
});
