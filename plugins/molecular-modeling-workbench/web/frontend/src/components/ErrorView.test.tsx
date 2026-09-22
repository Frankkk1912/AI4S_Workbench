import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ErrorView } from "./ErrorView";
import { humanizeError } from "../lib/errors";

describe("ErrorView", () => {
  it("translates a non-zero returncode into a human-readable error", () => {
    render(
      <ErrorView
        receipt={{
          returncode: 1,
          stderr: "Segmentation fault (core dumped)",
        }}
      />,
    );
    expect(screen.getByTestId("error-title")).toHaveTextContent("退出码 1");
    expect(screen.getByTestId("error-detail")).toHaveTextContent(
      "Segmentation fault",
    );
    expect(screen.getAllByTestId("error-suggestion").length).toBeGreaterThan(0);
  });

  it("returns null without a receipt", () => {
    const { container } = render(<ErrorView receipt={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("suggests retry with a reason", () => {
    const error = humanizeError({
      returncode: 2,
      stderr: "Step size too small",
    });
    expect(error.suggestions.join(" ")).toMatch(/重试/);
  });
});
