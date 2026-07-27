import { describe, expect, it } from "vitest";

import type { GenerationRun } from "@sio/shared-types";

import {
  generationInputTypeLabel,
  generationProgress,
  generationSourceTitle,
  generationStatusLabel,
  generationVerificationLabel,
  outputList,
  outputText,
} from "./generation-presentation";

const run = {
  input_type: "news",
  input_payload: { title: "A late-race comeback" },
  status: "running",
  current_step: "editorial_review",
  steps: [
    { status: "completed" },
    { status: "completed" },
    { status: "running" },
  ],
} as unknown as GenerationRun;

describe("generation presentation", () => {
  it("classifies fixed output fields for creator-facing cards", () => {
    const output = {
      tts_en: "One clean line.",
      search_keywords: ["final lap", "comeback"],
      story_value: { score: 91 },
    };
    expect(outputText(output, "tts_en")).toBe("One clean line.");
    expect(outputList(output, "search_keywords")).toEqual([
      "final lap",
      "comeback",
    ]);
    expect(outputText(output, "story_value")).toContain('"score": 91');
  });

  it("summarizes technical workflow state in creator language", () => {
    expect(generationSourceTitle(run)).toBe("A late-race comeback");
    expect(generationStatusLabel(run.status)).toBe("正在生成");
    expect(generationInputTypeLabel("news")).toBe("热点新闻");
    expect(generationVerificationLabel("verification_incomplete")).toBe(
      "核实未完成",
    );
    expect(generationProgress(run)).toMatchObject({
      completed: 2,
      total: 3,
      percent: 67,
      current: "正在生成和编辑文案",
    });
  });
});
