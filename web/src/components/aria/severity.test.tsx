import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SeverityBadge, SeverityScale } from "./severity";

describe("severity components", () => {
  it("describes the instrument in words, not only bars", () => {
    render(
      <SeverityScale
        probabilities={{ SEV1: 0.03, SEV2: 0.15, SEV3: 0.7, SEV4: 0.12 }}
        predictionSet={["SEV3"]}
        decided="SEV3"
        floor="SEV3"
      />,
    );
    const figure = screen.getByRole("figure");
    expect(figure.getAttribute("aria-label")).toBe(
      "Model probabilities: SEV1 3%, SEV2 15%, SEV3 70%, SEV4 12%. 90% prediction set: SEV3. Decided: SEV3. Safety floor: SEV3.",
    );
  });

  it("says when no class reached the prediction set", () => {
    render(
      <SeverityScale
        probabilities={{ SEV1: 0.05, SEV2: 0.28, SEV3: 0.34, SEV4: 0.33 }}
        predictionSet={["SEV3"]}
        decided="SEV3"
        setEmpty
      />,
    );
    expect(screen.getByRole("figure").getAttribute("aria-label")).toContain(
      "No class is likely enough for the 90% prediction set.",
    );
    expect(screen.getByText(/Dashed bracket/)).toBeTruthy();
  });

  it("always writes the severity as text", () => {
    render(<SeverityBadge severity="SEV1" withMeaning />);
    expect(screen.getByText("SEV1")).toBeTruthy();
    expect(screen.getByText("Critical")).toBeTruthy();
    render(<SeverityBadge severity={null} />);
    expect(screen.getByText("Not rated")).toBeTruthy();
  });
});
