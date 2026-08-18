import { describe, expect, it } from "vitest";

import {
  existingSubtitleGenerationLanguages,
  missingSubtitleGenerationLanguages,
} from "./subtitle-generation-options";

describe("subtitle generation language coverage", () => {
  it("treats source and translated tracks as already available by language", () => {
    expect(existingSubtitleGenerationLanguages(["en-orig", "zh-Hans", "ja"])).toEqual([
      "zh",
      "en",
      "ja",
    ]);
  });

  it("returns only languages that still need generation", () => {
    expect(missingSubtitleGenerationLanguages(["en", "zh"])).toEqual([
      "ja",
      "ko",
      "es",
      "fr",
      "de",
      "pt",
    ]);
  });
});
