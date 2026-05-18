import { describe, it, expect } from "vitest";
import { theme } from "@/lib/theme";

describe("theme tokens — spec §3.1", () => {
  it("bg is #1a1410", () => expect(theme.color.bg).toBe("#1a1410"));
  it("primary peach is #f97316", () => expect(theme.color.primary).toBe("#f97316"));
  it("secondary mint is #4ade80", () => expect(theme.color.secondary).toBe("#4ade80"));
  it("text cream is #f5ebe0", () => expect(theme.color.text).toBe("#f5ebe0"));
});
