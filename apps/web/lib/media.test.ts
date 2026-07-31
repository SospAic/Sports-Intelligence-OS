import { describe, expect, it } from "vitest";

import { normalizeExternalImageUrl } from "./media";

describe("normalizeExternalImageUrl", () => {
  it("upgrades Bilibili media to HTTPS", () => {
    expect(
      normalizeExternalImageUrl(
        "http://i2.hdslb.com/bfs/archive/example.jpg",
      ),
    ).toBe("https://i2.hdslb.com/bfs/archive/example.jpg");
  });

  it("keeps other HTTP and HTTPS sources unchanged", () => {
    expect(normalizeExternalImageUrl("http://images.example.com/a.jpg")).toBe(
      "http://images.example.com/a.jpg",
    );
    expect(normalizeExternalImageUrl("https://images.example.com/a.jpg")).toBe(
      "https://images.example.com/a.jpg",
    );
  });

  it("rejects missing, malformed, and unsafe sources", () => {
    expect(normalizeExternalImageUrl(null)).toBeNull();
    expect(normalizeExternalImageUrl("not-a-url")).toBeNull();
    expect(normalizeExternalImageUrl("javascript:alert(1)")).toBeNull();
  });
});
