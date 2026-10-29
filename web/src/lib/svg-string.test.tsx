import { describe, expect, it } from "vitest";

import { NoiseScene } from "@/components/illustrations/scenes";

import { renderSvg } from "./svg-string";

function Dot({ x }: { x: number }) {
  return <circle cx={x} cy={2} r={1} fill="#8ed462" />;
}

describe("renderSvg", () => {
  it("writes SVG attribute names, keeping the camel-cased ones SVG spells that way", () => {
    expect(
      renderSvg(
        <svg viewBox="0 0 4 4" preserveAspectRatio="none" aria-hidden className="art">
          <path
            d="M0 0h4"
            strokeWidth={2}
            strokeLinecap="round"
            vectorEffect="non-scaling-stroke"
          />
        </svg>,
      ),
    ).toBe(
      '<svg viewBox="0 0 4 4" preserveAspectRatio="none" aria-hidden="true" class="art">' +
        '<path d="M0 0h4" stroke-width="2" stroke-linecap="round" vector-effect="non-scaling-stroke"/>' +
        "</svg>",
    );
  });

  it("draws function components, fragments and arrays, and skips empty values", () => {
    expect(
      renderSvg(
        <g>
          <>
            {[1, 2].map((x) => (
              <Dot key={x} x={x} />
            ))}
          </>
          {null}
          {false}
        </g>,
      ),
    ).toBe(
      '<g><circle cx="1" cy="2" r="1" fill="#8ed462"/><circle cx="2" cy="2" r="1" fill="#8ed462"/></g>',
    );
  });

  it("escapes text and attribute values", () => {
    expect(renderSvg(<text fontFamily={'"A" & B'}>{"<SEV2> & more"}</text>)).toBe(
      '<text font-family="&quot;A&quot; &amp; B">&lt;SEV2> &amp; more</text>',
    );
  });

  it("draws a whole scene from the illustration kit", () => {
    const svg = renderSvg(<NoiseScene />);
    expect(svg.startsWith('<svg viewBox="0 0 520 440"')).toBe(true);
    expect(svg).toContain('stroke-linecap="round"');
    expect(svg).not.toContain("strokeWidth");
    expect(svg).not.toContain("[object Object]");
  });
});
