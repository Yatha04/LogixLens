import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Ladder } from "./Ladder";
import {
  RUNG9_ELEMENTS,
  RUNG9_GUARD_VALUES,
  RUNG9_HEALTHY_VALUES,
} from "../lib/fixtures";

// Each tag renders both a visible <text> label and a <title> tooltip, so
// getAllByText finds >= 1 nodes; we assert presence rather than uniqueness.
const hasText = (t: string) => expect(screen.getAllByText(t).length).toBeGreaterThan(0);

describe("<Ladder /> smoke", () => {
  it("renders an SVG with tag operands as labels", () => {
    render(<Ladder elements={RUNG9_ELEMENTS} />);
    const ladder = screen.getByTestId("ladder");
    expect(ladder.querySelector("svg")).toBeInTheDocument();
    hasText("Safety_OK");
    hasText("Press_Cycle_Start");
    // no values -> unknown state
    expect(ladder.getAttribute("data-rung-state")).toBe("unknown");
  });

  it("marks the rung blocked under guard_door_open values", () => {
    render(<Ladder elements={RUNG9_ELEMENTS} values={RUNG9_GUARD_VALUES} />);
    expect(screen.getByTestId("ladder").getAttribute("data-rung-state")).toBe("blocked");
  });

  it("marks the rung conducting under healthy values", () => {
    render(<Ladder elements={RUNG9_ELEMENTS} values={RUNG9_HEALTHY_VALUES} />);
    expect(screen.getByTestId("ladder").getAttribute("data-rung-state")).toBe("conducting");
  });

  it("renders a branch with both parallel legs' tags", () => {
    render(<Ladder elements={RUNG9_ELEMENTS} values={RUNG9_HEALTHY_VALUES} />);
    hasText("Cycle_Start_PB");
    hasText("Auto_Sequence_Run");
  });
});
