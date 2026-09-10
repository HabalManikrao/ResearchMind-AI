import type { ComponentProps } from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// LiveResearch imports the api client at module load; stub it so the component renders.
vi.mock("../api/client", () => ({ api: {} }));

import { FailedResearchCard } from "./LiveResearch";

function setup(over: Partial<ComponentProps<typeof FailedResearchCard>> = {}) {
  const onRetry = vi.fn();
  render(
    <FailedResearchCard
      status="failed"
      error="Ollama is unavailable."
      retrying={false}
      retryErr={null}
      onRetry={onRetry}
      {...over}
    />,
  );
  return { onRetry };
}

describe("FailedResearchCard", () => {
  it("shows Retry Research on a FAILED run, with the failure reason", () => {
    setup();
    expect(screen.getByText("Research Failed")).toBeInTheDocument();
    expect(screen.getByText("Ollama is unavailable.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Retry Research/ })).toBeEnabled();
  });

  it("renders nothing for a completed run (no Retry button)", () => {
    const { container } = render(
      <FailedResearchCard
        status="completed"
        error={null}
        retrying={false}
        retryErr={null}
        onRetry={vi.fn()}
      />,
    );
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByRole("button", { name: /Retry Research/ })).not.toBeInTheDocument();
  });

  it("disables the button and shows a spinner label while retrying", () => {
    setup({ retrying: true });
    const btn = screen.getByRole("button", { name: /Retrying/ });
    expect(btn).toBeDisabled();
  });

  it("calls onRetry when clicked", async () => {
    const user = userEvent.setup();
    const { onRetry } = setup();
    await user.click(screen.getByRole("button", { name: /Retry Research/ }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("surfaces a retry error if the retry itself fails", () => {
    setup({ retryErr: "Research is already running" });
    expect(screen.getByText("Research is already running")).toBeInTheDocument();
  });
});
