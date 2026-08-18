import { describe, expect, it } from "vitest";

import { evidenceLocatorUrl, evidenceWindowFromMs, formatEvidenceTime } from "./video-evidence";

describe("video evidence helpers", () => {
  it("formats subtitle windows as readable timestamps", () => {
    expect(formatEvidenceTime(0)).toBe("0:00");
    expect(formatEvidenceTime(65_000)).toBe("1:05");
    expect(formatEvidenceTime(3_725_000)).toBe("1:02:05");
  });

  it("rejects incomplete or reversed evidence windows", () => {
    expect(evidenceWindowFromMs(null, 1_000, "字幕")).toBeUndefined();
    expect(evidenceWindowFromMs(2_000, 1_000, "字幕")).toBeUndefined();
    expect(evidenceWindowFromMs(1_000, 2_000, "字幕", "track-1")).toEqual({
      startMs: 1_000,
      endMs: 2_000,
      label: "字幕",
      sourceRef: "track-1",
    });
  });

  it("preserves the source URL and adds a platform-appropriate locator", () => {
    expect(evidenceLocatorUrl("https://www.youtube.com/watch?v=abc", 65_000)).toBe(
      "https://www.youtube.com/watch?v=abc&t=65s",
    );
    expect(evidenceLocatorUrl("https://example.com/video/1?source=search", 65_000)).toBe(
      "https://example.com/video/1?source=search#t=65",
    );
  });
});
