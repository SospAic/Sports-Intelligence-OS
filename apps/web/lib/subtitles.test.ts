import { describe, expect, it } from "vitest";
import { parseInlineWordTimeline, parseSubtitles, subtitleDisplayText } from "./subtitles";

describe("subtitle parsing", () => {
  it("decodes entities, removes YouTube markers, and keeps one text flow", () => {
    expect(subtitleDisplayText("What's happening? &gt;&gt; In\n<c>the middle</c>")).toBe(
      "What's happening? In the middle",
    );
  });

  it("preserves inline VTT timestamps for word-level highlighting", () => {
    const words = parseInlineWordTimeline(
      "What's<00:00:01.200><c> happening?</c>",
      1,
      2,
    );
    expect(words.map((word) => word.text)).toEqual(["What's", "happening?"]);
    expect(words[1]?.start).toBeCloseTo(1.2);
    expect(words[0]?.end).toBeCloseTo(1.2);
  });

  it("parses a YouTube cue without exposing timing markup", () => {
    const cues = parseSubtitles(
      "WEBVTT\n\n00:00.000 --> 00:02.000\nWhat's<00:00:00.500><c> happening?</c><00:00:01.000><c> &gt;&gt; In</c><00:00:01.500><c> the</c><00:00:01.700><c> middle</c>\n",
    );
    expect(cues).toHaveLength(1);
    expect(cues[0]?.text).toBe("What's happening? In the middle");
    expect(cues[0]?.words).toHaveLength(5);
  });
});
