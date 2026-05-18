import { render } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { Mark } from "@/components/brand/Mark";

describe("<Mark /> Split-D monogram", () => {
  it("renders outer circle with text stroke", () => {
    const { container } = render(<Mark size={48} />);
    const circle = container.querySelector("circle");
    expect(circle).not.toBeNull();
    expect(circle!.getAttribute("stroke")).toBe("#f5ebe0");
    expect(circle!.getAttribute("fill")).toBe("none");
  });

  it("renders peach left half (#f97316)", () => {
    const { container } = render(<Mark size={48} />);
    const peach = container.querySelector('path[fill="#f97316"]');
    expect(peach).not.toBeNull();
  });

  it("renders mint right half (#4ade80)", () => {
    const { container } = render(<Mark size={48} />);
    const mint = container.querySelector('path[fill="#4ade80"]');
    expect(mint).not.toBeNull();
  });

  it("respects size prop", () => {
    const { container } = render(<Mark size={64} />);
    const svg = container.querySelector("svg");
    expect(svg!.getAttribute("width")).toBe("64");
    expect(svg!.getAttribute("height")).toBe("64");
  });
});
