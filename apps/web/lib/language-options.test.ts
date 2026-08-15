import { describe, expect, it } from "vitest";

import {
  defaultSubtitleLanguagePair,
  subtitleLanguageLabel,
  subtitleTrackLabel,
} from "./language-options";

describe("subtitle language labels", () => {
  it("renders common subtitle codes as Chinese labels", () => {
    expect(subtitleLanguageLabel("en-orig")).toBe("英语（原始）");
    expect(subtitleLanguageLabel("zh-Hans")).toBe("中文（简体）");
    expect(subtitleLanguageLabel("ja")).toBe("日语");
    expect(subtitleLanguageLabel("pt-BR")).toBe("葡萄牙语（pt-BR）");
    expect(subtitleLanguageLabel("und-auto")).toBe("源字幕");
  });

  it("defaults to English then Chinese regardless of storage order", () => {
    expect(defaultSubtitleLanguagePair(["pt", "en-orig", "en", "zh"])).toEqual({
      primary: "en",
      secondary: "zh",
    });
  });

  it("keeps automatic/manual provenance in Chinese", () => {
    expect(subtitleTrackLabel("en", "automatic")).toBe("英语（自动）");
    expect(subtitleTrackLabel("en", "manual")).toBe("英语（人工）");
  });
});
