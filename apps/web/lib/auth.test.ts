import { describe, expect, it } from "vitest";

import { getDisplayName } from "./auth";

describe("getDisplayName", () => {
  it("uses a non-empty display name", () => {
    expect(getDisplayName("运营管理员", "admin@example.com")).toBe(
      "运营管理员",
    );
  });

  it("falls back to email for a blank display name", () => {
    expect(getDisplayName("   ", "admin@example.com")).toBe(
      "admin@example.com",
    );
  });
});
