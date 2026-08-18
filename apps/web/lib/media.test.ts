import { describe, expect, it } from "vitest";

import { contentCoverUrl, normalizeExternalImageUrl } from "./media";

describe("normalizeExternalImageUrl", () => {
  it("upgrades Bilibili media to HTTPS", () => {
    expect(
      normalizeExternalImageUrl("http://i2.hdslb.com/bfs/archive/example.jpg"),
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

  it("passes through same-origin /api/v1/media paths", () => {
    expect(
      normalizeExternalImageUrl("/api/v1/media/abc-123/abc-123.jpg"),
    ).toBe("/api/v1/media/abc-123/abc-123.jpg");
  });

  it("still rejects other relative or unsafe paths", () => {
    expect(normalizeExternalImageUrl("/some/other/path.png")).toBeNull();
  });
});

describe("contentCoverUrl", () => {
  it("prefers the locally-archived thumbnail", () => {
    expect(
      contentCoverUrl({
        id: "cid",
        cover_url: "https://expired.example.com/cover.jpg",
        media: { thumbnail: "cid.jpg" },
      }),
    ).toBe("/api/v1/media/cid/cid.jpg");
  });

  it("falls back to the external cover URL when no thumbnail is archived", () => {
    expect(
      contentCoverUrl({
        id: "cid",
        cover_url: "https://i.ytimg.com/xyz.jpg",
        media: null,
      }),
    ).toBe("https://i.ytimg.com/xyz.jpg");
  });

  it("returns null when neither source is available", () => {
    expect(
      contentCoverUrl({ id: "cid", cover_url: null, media: null }),
    ).toBeNull();
    expect(contentCoverUrl(null)).toBeNull();
  });

  it("uses the stable YouTube thumbnail endpoint when metadata has no cover", () => {
    expect(
      contentCoverUrl({
        id: "cid",
        cover_url: null,
        canonical_url: "https://www.youtube.com/watch?v=abc123",
        media: null,
      }),
    ).toBe("https://i.ytimg.com/vi/abc123/hqdefault.jpg");
  });
});
