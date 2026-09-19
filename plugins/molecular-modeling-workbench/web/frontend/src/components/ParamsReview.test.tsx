import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ParamsReview } from "./ParamsReview";
import type { ParamsDiff } from "../api/types";

const PARAMS: ParamsDiff = {
  mdp: [
    {
      key: "nsteps",
      default: "50000000",
      current: "60000000",
      changed: true,
      explanation: "Default md_prod.mdp value from SKILL.md template.",
      protected: false,
    },
    {
      key: "dt",
      default: "0.002",
      current: "0.002",
      changed: false,
      explanation: "Default md_prod.mdp value from SKILL.md template.",
      protected: false,
    },
  ],
  force_field: {
    default: "CHARMM36",
    current: "CHARMM36",
    protected: true,
    explanation: "Prepared protein force field is read-only.",
  },
  water_model: {
    default: "TIP3P",
    current: "TIP3P",
    protected: true,
    explanation: "Prepared water model is read-only.",
  },
  topology: {
    current: { path: "/work/topology.top" },
    protected: true,
  },
  protected_fields: ["force_field", "water_model", "topology"],
};

describe("ParamsReview", () => {
  it("renders the mdp diff with changed flags", () => {
    render(<ParamsReview params={PARAMS} />);
    expect(screen.getByTestId("mdp-nsteps")).toHaveTextContent("已变更");
    expect(screen.getByTestId("mdp-dt")).toHaveTextContent("未变更");
  });

  it("has no edit entry for protected fields and explains the boundary", () => {
    render(<ParamsReview params={PARAMS} />);
    const container = screen.getByTestId("protected-fields");
    expect(container.querySelector("input, textarea, select")).toBeNull();
    expect(screen.getByTestId("protected-fields")).toHaveTextContent("只读");
    expect(screen.getByTestId("protected-force_field-note")).toHaveTextContent(
      "read-only",
    );
    expect(screen.getByTestId("protected-topology-note")).toHaveTextContent(
      "重新准备体系",
    );
  });
});
