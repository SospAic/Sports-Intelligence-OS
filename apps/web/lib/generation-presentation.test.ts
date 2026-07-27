import { describe, expect, it } from "vitest";

import type { GenerationRun } from "@sio/shared-types";

import {
  generationInputTypeLabel,
  generationProgress,
  generationSourceTitle,
  generationStatusLabel,
  generationVerificationLabel,
  outputLabels,
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

  it("has a label for every A-group output field", () => {
    const aGroup: string[] = [
      "event_fact_summary", "fact_sources", "story_value",
      "tts_en", "translation_zh",
      "video_title_en", "video_title_zh",
      "search_keywords", "material_keywords", "tags",
      "project_filename", "qa_report", "used_rules", "rewrite_reasons",
    ];
    for (const key of aGroup) {
      expect(outputLabels).toHaveProperty(key);
      expect(outputLabels[key as keyof typeof outputLabels].length).toBeGreaterThan(0);
    }
  });

  it("has a label for every B-group 7.9 full-package field", () => {
    const bGroup: string[] = [
      "spoken_char_count", "event_identity", "story_format",
      "story_format_reason", "central_question", "selected_hook",
      "cmssml", "ev3", "story_architecture",
      "lcr_enabled", "lcr_reason", "hook_candidates",
      "answer_word_map", "reaction_relay", "evidence_rewards",
      "exclusion_ladder", "dialogue_notes",
    ];
    for (const key of bGroup) {
      expect(outputLabels).toHaveProperty(key);
      expect(outputLabels[key as keyof typeof outputLabels].length).toBeGreaterThan(0);
    }
  });

  it("has a label for every C-group ambiguous field", () => {
    const cGroup: string[] = [
      "audio_performance_map", "tts_settings", "video_material_plan",
      "edit_map", "caption_map", "original_audio_plan", "srt_output",
    ];
    for (const key of cGroup) {
      expect(outputLabels).toHaveProperty(key);
      expect(outputLabels[key as keyof typeof outputLabels].length).toBeGreaterThan(0);
    }
  });

  it("renders B-group scalar and object fields via outputText", () => {
    const output = {
      spoken_char_count: 1195,
      story_format: "consequence-first-decision",
      lcr_enabled: false,
      story_architecture: { primary_format: "consequence-first-decision", lcr_enabled: false },
      cmssml: "Single line CMSSML narration.",
      ev3: "Single line EV3 narration.",
    };
    // numeric → string
    expect(outputText(output, "spoken_char_count")).toBe("1195");
    // plain string passthrough
    expect(outputText(output, "story_format")).toBe("consequence-first-decision");
    // boolean → string
    expect(outputText(output, "lcr_enabled")).toBe("false");
    // object → pretty JSON
    expect(outputText(output, "story_architecture")).toContain("primary_format");
    // single-line TTS variants
    expect(outputText(output, "cmssml")).toBe("Single line CMSSML narration.");
    expect(outputText(output, "ev3")).toBe("Single line EV3 narration.");
  });

  it("returns empty string for null or missing B-group optional fields", () => {
    const output: Record<string, unknown> = {
      reaction_relay: null,
      evidence_rewards: undefined,
    };
    expect(outputText(output, "reaction_relay")).toBe("");
    expect(outputText(output, "evidence_rewards")).toBe("");
    expect(outputText(output, "exclusion_ladder")).toBe("");
  });
});
